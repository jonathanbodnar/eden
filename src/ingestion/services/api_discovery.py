"""API-based discovery adapters for sources with public REST APIs.

Each adapter is an async generator that yields batches of DiscoveredPage
entries, allowing the discovery worker to stream results to the DB
instead of buffering everything in memory.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import NamedTuple

import httpx

from src.ingestion.services.discovery import CrawlResult, DiscoveredPage

logger = logging.getLogger(__name__)

TIMEOUT = 30.0
USER_AGENT = "EdenBot/1.0 (research ingestion platform)"


class DiscoveryBatch(NamedTuple):
    pages: list[DiscoveredPage]
    pages_visited: int
    errors: int
    done: bool


# ---------------------------------------------------------------------------
# CDLI  —  Cuneiform Digital Library Initiative
# ---------------------------------------------------------------------------

async def stream_cdli(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Paginate through GET /artifacts.json, yielding batches of 100."""
    page = 1
    per_page = 100
    total_found = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while total_found < max_pages:
            url = f"https://cdli.earth/artifacts.json?page={page}&per_page={per_page}"
            try:
                resp = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )

                if resp.status_code != 200:
                    logger.warning("CDLI API returned %d on page %d", resp.status_code, page)
                    yield DiscoveryBatch([], 1, 1, True)
                    return

                artifacts = resp.json()
                if isinstance(artifacts, dict):
                    artifacts = artifacts.get("data", artifacts.get("artifacts", []))
                if not isinstance(artifacts, list) or not artifacts:
                    yield DiscoveryBatch([], 1, 0, True)
                    return

                batch: list[DiscoveredPage] = []
                for art in artifacts:
                    art_id = art.get("id") or art.get("artifact_id")
                    if not art_id:
                        continue
                    title = art.get("designation", f"CDLI P{art_id:06d}" if isinstance(art_id, int) else f"CDLI {art_id}")
                    batch.append(DiscoveredPage(
                        url=f"https://cdli.earth/artifacts/{art_id}",
                        external_id=f"cdli-{art_id}",
                        title=str(title)[:300],
                        content_hint="cuneiform artifact",
                        depth=0,
                    ))
                    total_found += 1
                    if total_found >= max_pages:
                        break

                is_last = len(artifacts) < per_page or total_found >= max_pages
                yield DiscoveryBatch(batch, 1, 0, is_last)

                if is_last:
                    return

                logger.info("CDLI page %d: %d artifacts (total: %d)", page, len(artifacts), total_found)
                page += 1
                await asyncio.sleep(0.3)

            except Exception as exc:
                logger.error("CDLI API error on page %d: %s", page, exc)
                yield DiscoveryBatch([], 1, 1, True)
                return

    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Met Museum  —  The Metropolitan Museum of Art Collection API
# ---------------------------------------------------------------------------

MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"

MET_DEPARTMENTS = [
    (3, "Ancient Near Eastern Art"),
    (5, "Arts of Africa, Oceania, and the Americas"),
    (10, "Egyptian Art"),
    (13, "Greek and Roman Art"),
]


async def stream_met_museum(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Search returns pre-BC object IDs; yield in batches of 500."""
    total_found = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for dept_id, dept_name in MET_DEPARTMENTS:
            if total_found >= max_pages:
                break
            try:
                search_url = (
                    f"{MET_BASE}/search?"
                    f"departmentId={dept_id}"
                    f"&dateBegin=-10000&dateEnd=0"
                    f"&hasImages=true&q=*"
                )
                resp = await client.get(search_url, headers={"User-Agent": USER_AGENT})

                if resp.status_code != 200:
                    logger.warning("Met search returned %d for dept %d", resp.status_code, dept_id)
                    yield DiscoveryBatch([], 1, 1, False)
                    continue

                data = resp.json()
                object_ids = data.get("objectIDs") or []
                logger.info("Met dept %d (%s): %d pre-BC objects with images", dept_id, dept_name, len(object_ids))

                batch_size = 500
                for i in range(0, len(object_ids), batch_size):
                    if total_found >= max_pages:
                        break
                    chunk = object_ids[i:i + batch_size]
                    batch: list[DiscoveredPage] = []
                    for oid in chunk:
                        batch.append(DiscoveredPage(
                            url=f"https://www.metmuseum.org/art/collection/search/{oid}",
                            external_id=f"met-{oid}",
                            title=f"Met Object {oid} ({dept_name})",
                            content_hint=dept_name,
                            depth=0,
                        ))
                        total_found += 1
                        if total_found >= max_pages:
                            break

                    yield DiscoveryBatch(batch, 1, 0, False)

            except Exception as exc:
                logger.error("Met API error for dept %d: %s", dept_id, exc)
                yield DiscoveryBatch([], 1, 1, False)

    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Europeana  —  Search API  (requires wskey)
# ---------------------------------------------------------------------------

EUROPEANA_QUERIES = [
    "cuneiform tablet",
    "Mesopotamia ancient artifact",
    "Egyptian hieroglyph inscription",
    "Sumerian inscription tablet",
    "Assyrian relief sculpture",
    "Babylonian cylinder seal",
    "ancient Near East artifact",
    "Egyptian papyrus ancient",
    "Greek pottery ancient vase",
]


async def stream_europeana(api_key: str, max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Cursor-based pagination over Europeana Search API."""
    if not api_key:
        logger.warning("No Europeana API key configured — skipping")
        yield DiscoveryBatch([], 0, 0, True)
        return

    base = "https://api.europeana.eu/record/v2/search.json"
    total_found = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for query in EUROPEANA_QUERIES:
            if total_found >= max_pages:
                break

            cursor = "*"
            while total_found < max_pages and cursor:
                try:
                    params: dict = {
                        "wskey": api_key,
                        "query": query,
                        "rows": 100,
                        "cursor": cursor,
                        "profile": "standard",
                        "media": "true",
                    }
                    resp = await client.get(base, params=params, headers={"User-Agent": USER_AGENT})

                    if resp.status_code != 200:
                        logger.warning("Europeana returned %d for '%s'", resp.status_code, query)
                        yield DiscoveryBatch([], 1, 1, False)
                        break

                    data = resp.json()
                    items = data.get("items", [])
                    cursor = data.get("nextCursor")

                    if not items:
                        break

                    batch: list[DiscoveredPage] = []
                    for item in items:
                        item_id = item.get("id", "")
                        titles = item.get("title", [])
                        title = titles[0] if titles else f"Europeana {item_id}"
                        page_url = item.get("guid") or f"https://www.europeana.eu/item{item_id}"

                        batch.append(DiscoveredPage(
                            url=page_url,
                            external_id=f"europeana-{item_id.lstrip('/').replace('/', '-')}",
                            title=str(title)[:300],
                            content_hint=query,
                            depth=0,
                        ))
                        total_found += 1
                        if total_found >= max_pages:
                            break

                    yield DiscoveryBatch(batch, 1, 0, False)
                    await asyncio.sleep(0.5)

                    if not cursor or len(items) < 100:
                        break

                except Exception as exc:
                    logger.error("Europeana error for '%s': %s", query, exc)
                    yield DiscoveryBatch([], 1, 1, False)
                    break

    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Sefaria — Hebrew Bible, Talmud, Mishnah, Midrash
# ---------------------------------------------------------------------------

TANAKH_BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "I Samuel", "II Samuel", "I Kings", "II Kings",
    "Isaiah", "Jeremiah", "Ezekiel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Psalms", "Proverbs", "Job",
    "Song of Songs", "Ruth", "Lamentations", "Ecclesiastes", "Esther",
    "Daniel", "Ezra", "Nehemiah", "I Chronicles", "II Chronicles",
]

async def stream_sefaria(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover whole Tanakh books from Sefaria (BC-era texts only)."""
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for book in TANAKH_BOOKS:
            if total >= max_pages:
                break
            try:
                resp = await client.get(
                    f"https://www.sefaria.org/api/v2/index/{book.replace(' ', '_')}",
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                num_chapters = 1
                if resp.status_code == 200:
                    info = resp.json()
                    schema = info.get("schema", {})
                    length = schema.get("lengths", [0])
                    num_chapters = length[0] if length else 1

                slug = book.replace(" ", "_")
                chapter_range = f"1-{num_chapters}" if num_chapters > 1 else "1"
                batch_item = DiscoveredPage(
                    url=f"https://www.sefaria.org/{slug}",
                    external_id=f"sefaria-{book}.{chapter_range}",
                    title=book,
                    content_hint="tanakh",
                    depth=0,
                )
                yield DiscoveryBatch([batch_item], 1, 0, False)
                total += 1
                logger.info("Sefaria: discovered %s (%d chapters)", book, num_chapters)
                await asyncio.sleep(0.3)
            except Exception as exc:
                logger.error("Sefaria error for %s: %s", book, exc)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Dead Sea Scrolls — dssenglishbible.com (HTML scrape)
# ---------------------------------------------------------------------------

DSS_SCROLLS = [
    "1Q1", "1Q2", "1Q3", "1Q4", "1Q5", "1Q6", "1Q7", "1QIsaa", "1QIsab",
    "1Q9", "1Q10", "1Q11", "1Q12", "1Q71", "1Q72",
    "2Q1", "2Q2", "2Q3", "2Q4", "2Q5", "2Q6", "2Q7", "2Q8", "2Q9",
    "2Q10", "2Q11", "2Q12", "2Q13", "2Q14", "2Q15", "2Q16", "2Q17",
    "3Q1", "3Q2", "3Q3",
    "4Q1", "4Q2", "4Q3", "4Q4", "4Q5", "4Q6", "4Q7", "4Q8", "4Q8a",
    "4Q8b", "4Q9", "4Q10", "4Q11", "4Q12", "4Q13", "4Q14", "4Q15",
    "4Q16", "4Q17", "4Q18", "4Q19", "4Q20", "4Q21", "4Q22",
    "4Q23", "4Q24", "4Q25", "4Q26", "4Q26a", "4Q26b", "4Q27",
    "4Q28", "4Q29", "4Q30", "4Q31", "4Q32", "4Q33", "4Q34", "4Q35",
    "4Q36", "4Q37", "4Q38", "4Q38a", "4Q38b", "4Q39", "4Q40", "4Q41",
    "4Q42", "4Q43", "4Q44", "4Q45", "4Q46",
    "4Q47", "4Q48", "4Q49", "4Q50", "4Q51", "4Q52", "4Q53", "4Q54",
    "4Q55", "4Q56", "4Q57", "4Q58", "4Q59", "4Q60", "4Q61", "4Q62",
    "4Q62a", "4Q63", "4Q64", "4Q65", "4Q66", "4Q67", "4Q68", "4Q69",
    "4Q69a", "4Q69b",
    "4Q70", "4Q71", "4Q72", "4Q72a", "4Q72b",
    "4Q73", "4Q74", "4Q75",
    "4Q76", "4Q77", "4Q78", "4Q79", "4Q80", "4Q81", "4Q82",
    "4Q83", "4Q84", "4Q85", "4Q86", "4Q87", "4Q88", "4Q89", "4Q90",
    "4Q91", "4Q92", "4Q93", "4Q94", "4Q95", "4Q96", "4Q97", "4Q98",
    "4Q98a", "4Q98b", "4Q98c", "4Q98d", "4Q98e", "4Q98f", "4Q98g",
    "4Q99", "4Q100", "4Q101", "4Q102", "4Q103", "4Q104", "4Q105",
    "4Q106", "4Q107", "4Q108", "4Q109", "4Q110", "4Q111",
    "4Q112", "4Q113", "4Q114", "4Q115", "4Q116", "4Q117", "4Q118",
    "4Q119", "4Q120", "4Q121", "4Q122",
    "4Q483", "4Q522", "4Q576",
    "5Q1", "5Q2", "5Q3", "5Q4", "5Q5", "5Q6", "5Q7",
    "6Q1", "6Q2", "6Q3", "6Q4", "6Q5", "6Q6", "6Q7",
    "7QExodus",
    "8Q1", "8Q2",
    "11Q1", "11Q2", "11Q3", "11Q4", "11Q6", "11Q7", "11Q8", "11Q9", "11Q11",
    "masgen", "masdeut", "masleva", "maslevb", "maspsa", "maspsb", "masez",
    "NHnuma", "NHnumb", "NHdeut", "NHminor", "NHps",
    "MurGen", "MurEx", "MurIsa", "MurNum", "MurDeut", "MurMinor",
    "wadiGen",
]

async def stream_dss_bible(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    import re
    total = 0
    seen = set()
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get("https://dssenglishbible.com/index.htm", headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                book_pages = re.findall(r'href="(Scrolls?\w+\.htm)"', resp.text, re.IGNORECASE)
                for bp in book_pages:
                    try:
                        bp_resp = await client.get(f"https://dssenglishbible.com/{bp}", headers={"User-Agent": USER_AGENT})
                        if bp_resp.status_code != 200:
                            continue
                        scroll_links = re.findall(r'href="(scroll\w+\.htm)"', bp_resp.text, re.IGNORECASE)
                        for sl in scroll_links:
                            scroll_id = sl.replace("scroll", "").replace("Scroll", "").replace(".htm", "")
                            if scroll_id in seen:
                                continue
                            seen.add(scroll_id)
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass
        except Exception as exc:
            logger.error("DSS index scrape error: %s", exc)

    for scroll_id in DSS_SCROLLS:
        seen.add(scroll_id)

    batch: list[DiscoveredPage] = []
    for scroll_id in sorted(seen):
        if total >= max_pages:
            break
        url = f"https://dssenglishbible.com/scroll{scroll_id}.htm"
        batch.append(DiscoveredPage(
            url=url,
            external_id=f"dss-{scroll_id}",
            title=f"Dead Sea Scroll {scroll_id}",
            content_hint="dead_sea_scroll",
            depth=0,
        ))
        total += 1
        if len(batch) >= 100:
            yield DiscoveryBatch(batch, 1, 0, False)
            batch = []

    if batch:
        yield DiscoveryBatch(batch, 1, 0, False)
    logger.info("DSS Bible: discovered %d scrolls", total)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# CText — Chinese Text Project (Pre-Qin classics)
# ---------------------------------------------------------------------------

CTEXT_PRE_QIN = [
    "analects", "mengzi", "dao-de-jing", "zhuangzi", "mozi", "xunzi",
    "han-feizi", "shang-jun-shu", "sun-tzu-the-art-of-war",
    "book-of-changes", "book-of-poetry", "book-of-documents",
    "rites-of-zhou", "book-of-rites", "yi-li",
    "guo-yu", "zuo-zhuan", "gongyang-zhuan", "guliang-zhuan",
    "chu-ci", "spring-and-autumn-annals", "erya",
    "liezi", "wenzi", "huainanzi", "lv-shi-chun-qiu",
    "shan-hai-jing", "guanzi",
    "shiji", "warring-states-strategies", "bamboo-annals",
    "yijing", "classic-of-filial-piety", "nei-ye",
    "wen-xuan", "shenzi", "gongsun-longzi", "yin-wenzi",
    "he-guanzi", "deng-xizi", "kongcongzi",
]

async def stream_ctext(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0

    async def _get_leaves(client: httpx.AsyncClient, urn: str, depth: int = 0) -> list[str]:
        """Recursively get leaf-level chapters via gettext endpoint."""
        if depth > 5:
            return [urn]
        try:
            resp = await client.get(
                f"https://api.ctext.org/gettext?urn={urn}",
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return [urn]
            data = resp.json()
            subs = data.get("subsections", [])
            if not subs:
                return [urn]
            all_leaves: list[str] = []
            for sub in subs:
                if not isinstance(sub, str):
                    continue
                child_leaves = await _get_leaves(client, sub, depth + 1)
                all_leaves.extend(child_leaves)
                await asyncio.sleep(0.3)
            return all_leaves if all_leaves else [urn]
        except Exception as exc:
            logger.warning("CText subsection error for %s: %s", urn, exc)
            return [urn]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for text_id in CTEXT_PRE_QIN:
            if total >= max_pages:
                break
            try:
                urn = f"ctp:{text_id}"
                leaves = await _get_leaves(client, urn)
                batch: list[DiscoveredPage] = []
                for leaf_urn in leaves:
                    path = leaf_urn.removeprefix("ctp:")
                    batch.append(DiscoveredPage(
                        url=f"https://ctext.org/{path}",
                        external_id=f"ctext::{path}",
                        title=path[:300],
                        content_hint="chinese_classic",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                    logger.info("CText %s: %d chapters (total: %d)", text_id, len(batch), total)
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.error("CText error for %s: %s", text_id, exc)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# SuttaCentral — Pali Canon Buddhist texts
# ---------------------------------------------------------------------------

SUTTA_COLLECTIONS = ["dn", "mn", "sn", "an", "kp", "dhp", "ud", "iti", "snp", "vv", "pv", "thag", "thig"]

async def stream_suttacentral(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for coll in SUTTA_COLLECTIONS:
            if total >= max_pages:
                break
            try:
                resp = await client.get(
                    f"https://suttacentral.net/api/suttaplex/{coll}",
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not isinstance(data, list):
                    data = [data]

                batch: list[DiscoveredPage] = []
                for sutta in data:
                    uid = sutta.get("uid", "")
                    if not uid:
                        continue
                    batch.append(DiscoveredPage(
                        url=f"https://suttacentral.net/{uid}",
                        external_id=f"sc-{uid}",
                        title=(sutta.get("translated_title") or sutta.get("original_title") or uid)[:300],
                        content_hint="buddhist_text",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.error("SuttaCentral error for %s: %s", coll, exc)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# ORACC — Open Richly Annotated Cuneiform Corpus
# ---------------------------------------------------------------------------

async def stream_oracc(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    total = 0
    base = "https://oracc.museum.upenn.edu"
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, verify=ctx) as client:
        try:
            resp = await client.get(f"{base}/projects.json", headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                logger.warning("ORACC projects.json: HTTP %d", resp.status_code)
                yield DiscoveryBatch([], 1, 1, True); return
            projects_data = resp.json()
            project_slugs = projects_data.get("public", [])
            if not isinstance(project_slugs, list):
                project_slugs = list(projects_data.get("projects", {}).keys())
        except Exception as exc:
            logger.error("ORACC projects error: %s", exc)
            yield DiscoveryBatch([], 1, 1, True); return

        for proj in project_slugs:
            if total >= max_pages:
                break
            if "/" in proj:
                continue
            try:
                cat_resp = await client.get(
                    f"{base}/{proj}/catalogue.json",
                    headers={"User-Agent": USER_AGENT},
                )
                if cat_resp.status_code != 200:
                    continue
                raw = cat_resp.content
                if not raw:
                    continue
                try:
                    cat = cat_resp.json()
                except Exception:
                    import gzip
                    try:
                        cat = __import__("json").loads(gzip.decompress(raw))
                    except Exception:
                        continue
                members = cat.get("members", {})

                batch: list[DiscoveredPage] = []
                for text_id, text_info in members.items():
                    designation = text_info.get("designation", text_id) if isinstance(text_info, dict) else text_id
                    batch.append(DiscoveredPage(
                        url=f"{base}/{proj}/{text_id}",
                        external_id=f"oracc-{proj}-{text_id}",
                        title=f"{designation}"[:300],
                        content_hint="cuneiform_text",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                    logger.info("ORACC %s: %d texts (total: %d)", proj, len(batch), total)
                await asyncio.sleep(0.3)
            except Exception as exc:
                logger.error("ORACC catalogue error for %s: %s", proj, exc)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Library of Congress
# ---------------------------------------------------------------------------

LOC_COLLECTIONS = [
    "ancient-near-eastern-seals",
    "cuneiform-tablets",
]
LOC_QUERIES = [
    "cuneiform tablet", "ancient mesopotamia",
    "dead sea scrolls", "ancient egypt papyrus",
    "sumerian", "babylonian",
]

async def stream_loc(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        for query in LOC_QUERIES:
            if total >= max_pages:
                break
            page = 1
            while total < max_pages:
                try:
                    resp = await client.get(
                        "https://www.loc.gov/collections/",
                        params={"q": query, "fo": "json", "sp": page, "c": 100},
                        headers={
                            "User-Agent": "Mozilla/5.0 (compatible; EdenBot/1.0; research)",
                            "Accept": "application/json",
                        },
                    )
                    if resp.status_code == 403:
                        resp = await client.get(
                            f"https://www.loc.gov/search/?q={query}&fo=json&sp={page}&c=50",
                            headers={"User-Agent": "Mozilla/5.0 (compatible; EdenBot/1.0; research)"},
                        )
                    if resp.status_code != 200:
                        logger.warning("LoC HTTP %d for '%s'", resp.status_code, query)
                        break
                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break

                    batch: list[DiscoveredPage] = []
                    for item in results:
                        item_id = item.get("id", item.get("url", ""))
                        title = item.get("title", "")
                        if not item_id:
                            continue
                        ext_id = item_id.rstrip("/").rsplit("/", 1)[-1]
                        batch.append(DiscoveredPage(
                            url=item_id if item_id.startswith("http") else f"https://www.loc.gov{item_id}",
                            external_id=f"loc-{ext_id}",
                            title=str(title)[:300],
                            content_hint=query,
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break
                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)

                    pagination = data.get("pagination", {})
                    if page >= pagination.get("total", 1) or not results:
                        break
                    page += 1
                    await asyncio.sleep(2.0)
                except Exception as exc:
                    logger.error("LoC error for '%s' page %d: %s", query, page, exc)
                    break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Internet Archive
# ---------------------------------------------------------------------------

IA_QUERIES = [
    "subject:cuneiform", "subject:mesopotamia AND subject:ancient",
    "subject:dead sea scrolls", "subject:sumerian AND subject:tablet",
    "subject:ancient egypt AND subject:papyrus",
    "title:book of the dead AND subject:egypt",
    "title:pyramid texts", "title:coffin texts",
    "subject:hieroglyphic AND subject:translation",
    "subject:egyptian papyrus AND subject:translation",
    "title:papyrus of ani", "title:instruction of ptahhotep",
    "subject:popol vuh", "subject:maya codex OR title:maya codex",
    "subject:aztec codex OR title:codex borgia OR title:codex mendoza",
    "subject:mesoamerican AND subject:ancient",
    "subject:inca AND subject:ancient OR title:quipu",
    "subject:olmec OR subject:zapotec OR subject:mixtec",
    "subject:moche OR subject:nazca OR subject:chavin",
    "title:chilam balam", "title:florentine codex",
]

async def stream_internet_archive(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        for query in IA_QUERIES:
            if total >= max_pages:
                break
            page = 1
            while total < max_pages:
                try:
                    resp = await client.get(
                        "https://archive.org/advancedsearch.php",
                        params={"q": query, "output": "json", "rows": 100, "page": page,
                                "fl[]": "identifier,title,description,date,mediatype"},
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    docs = data.get("response", {}).get("docs", [])
                    if not docs:
                        break

                    batch: list[DiscoveredPage] = []
                    for doc in docs:
                        ident = doc.get("identifier", "")
                        if not ident:
                            continue
                        batch.append(DiscoveredPage(
                            url=f"https://archive.org/details/{ident}",
                            external_id=f"ia-{ident}",
                            title=(doc.get("title", ident) or ident)[:300],
                            content_hint=query,
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break
                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)
                    if len(docs) < 100:
                        break
                    page += 1
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    logger.error("IA error for '%s': %s", query, exc)
                    break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Wikidata — artifacts (cuneiform tablets, ancient manuscripts)
# ---------------------------------------------------------------------------

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WD_ARTIFACT_QUERY = """
SELECT ?item ?itemLabel ?itemDescription WHERE {{
  VALUES ?type {{ wd:Q46046 wd:Q13442814 wd:Q4006 wd:Q5398426 wd:Q860861 wd:Q131569 }}
  ?item wdt:P31 ?type .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT {limit} OFFSET {offset}
"""

async def stream_wikidata_artifacts(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    offset = 0
    limit = 500
    async with httpx.AsyncClient(timeout=90.0) as client:
        while total < max_pages:
            try:
                query = WD_ARTIFACT_QUERY.format(limit=limit, offset=offset)
                resp = await client.get(
                    WIKIDATA_SPARQL,
                    params={"query": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                )
                if resp.status_code != 200:
                    logger.warning("Wikidata SPARQL %d at offset %d", resp.status_code, offset)
                    break
                results = resp.json().get("results", {}).get("bindings", [])
                if not results:
                    break

                batch: list[DiscoveredPage] = []
                for r in results:
                    item_uri = r.get("item", {}).get("value", "")
                    qid = item_uri.rsplit("/", 1)[-1] if item_uri else ""
                    label = r.get("itemLabel", {}).get("value", qid)
                    if not qid:
                        continue
                    batch.append(DiscoveredPage(
                        url=item_uri,
                        external_id=f"wd-art-{qid}",
                        title=label[:300],
                        content_hint="wikidata_artifact",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                if len(results) < limit:
                    break
                offset += limit
                await asyncio.sleep(2.0)
            except Exception as exc:
                logger.error("Wikidata artifacts error: %s", exc)
                break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# BSB/MDZ — Bavarian State Library (IIIF)
# ---------------------------------------------------------------------------

BSB_SEARCHES = [
    "cuneiform", "keilschrift", "papyrus", "mesopotamia",
    "ancient near east", "sumerian", "akkadian", "hieroglyphic",
    "dead sea scrolls", "qumran",
]

async def stream_bsb_mdz(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        for query in BSB_SEARCHES:
            if total >= max_pages:
                break
            offset = 0
            while total < max_pages:
                try:
                    resp = await client.get(
                        "https://api.digitale-sammlungen.de/iiif/presentation/v2/collection/search",
                        params={"q": query, "start": offset, "rows": 100},
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code != 200:
                        resp = await client.get(
                            "https://api.digitale-sammlungen.de/search",
                            params={"q": query, "start": offset, "rows": 100, "format": "json"},
                            headers={"User-Agent": USER_AGENT},
                        )
                    if resp.status_code != 200:
                        logger.warning("BSB/MDZ %d for '%s'", resp.status_code, query)
                        break
                    data = resp.json()
                    manifests = data.get("manifests", data.get("members", data.get("items", data.get("results", []))))
                    if not manifests:
                        break

                    batch: list[DiscoveredPage] = []
                    for m in manifests:
                        m_id = m.get("@id", m.get("id", m.get("manifest", "")))
                        label = m.get("label", m.get("title", ""))
                        if isinstance(label, list):
                            label = label[0] if label else ""
                        if isinstance(label, dict):
                            label = label.get("@value", label.get("en", [label])[0] if "en" in label else "")
                        ext_id = m_id.rsplit("/", 1)[-1] if m_id else ""
                        if not ext_id:
                            continue
                        batch.append(DiscoveredPage(
                            url=m_id if m_id.startswith("http") else f"https://api.digitale-sammlungen.de/iiif/presentation/v2/{ext_id}/manifest",
                            external_id=f"bsb-{ext_id}",
                            title=str(label)[:300],
                            content_hint="iiif_manuscript",
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break
                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)
                    if len(manifests) < 100:
                        break
                    offset += 100
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    logger.error("BSB/MDZ error for '%s': %s", query, exc)
                    break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Gallica / BnF (SRU)
# ---------------------------------------------------------------------------

import xml.etree.ElementTree as ET

GALLICA_QUERIES = [
    ("dc.title", "papyrus"), ("dc.title", "cunéiforme"), ("dc.title", "hiéroglyphe"),
    ("dc.title", "mésopotamie"), ("dc.title", "babylone"), ("dc.title", "sumérien"),
    ("dc.title", "égypte ancienne"), ("dc.title", "manuscrit hébreu"),
    ("dc.title", "bible hébraïque"), ("dc.title", "torah"),
    ("dc.subject", "cunéiforme"), ("dc.subject", "papyrus"),
    ("dc.subject", "mésopotamie"), ("dc.subject", "hiéroglyphe"),
    ("dc.subject", "sumérien"), ("dc.subject", "babylonien"),
    ("dc.subject", "assyrien"), ("dc.subject", "qumran"),
    ("dc.subject", "égyptologie"), ("dc.subject", "archéologie"),
    ("dc.subject", "inscription"), ("dc.subject", "antiquité"),
]

async def stream_gallica(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        for field, query in GALLICA_QUERIES:
            if total >= max_pages:
                break
            start = 1
            while total < max_pages:
                try:
                    resp = await client.get(
                        "https://gallica.bnf.fr/SRU",
                        params={
                            "version": "1.2", "operation": "searchRetrieve",
                            "query": f'{field} all "{query}"',
                            "maximumRecords": 50, "startRecord": start,
                        },
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code != 200:
                        break

                    root = ET.fromstring(resp.content)
                    ns = {"srw": "http://www.loc.gov/zing/srw/", "dc": "http://purl.org/dc/elements/1.1/"}
                    records_el = root.findall(".//srw:record", ns)
                    if not records_el:
                        break

                    batch: list[DiscoveredPage] = []
                    for rec in records_el:
                        data_el = rec.find(".//srw:recordData", ns)
                        if data_el is None:
                            continue
                        identifier = ""
                        title_text = ""
                        for child in data_el.iter():
                            tag = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
                            if tag == "identifier" and child.text and "gallica" in child.text:
                                identifier = child.text.strip()
                            elif tag == "title" and child.text:
                                title_text = child.text.strip()
                        if not identifier:
                            continue
                        ext_id = identifier.rsplit("/", 1)[-1]
                        batch.append(DiscoveredPage(
                            url=identifier,
                            external_id=f"gallica-{ext_id}",
                            title=title_text[:300],
                            content_hint=query,
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break
                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)
                    if len(records_el) < 50:
                        break
                    start += 50
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    logger.error("Gallica error for '%s': %s", query, exc)
                    break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Pleiades — ancient world gazetteer
# ---------------------------------------------------------------------------

async def stream_pleiades(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    import csv, gzip, io
    total = 0
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            resp = await client.get(
                "https://atlantides.org/downloads/pleiades/dumps/pleiades-places-latest.csv.gz",
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                yield DiscoveryBatch([], 1, 1, True); return

            decompressed = gzip.decompress(resp.content)
            reader = csv.DictReader(io.StringIO(decompressed.decode("utf-8")))

            batch: list[DiscoveredPage] = []
            for row in reader:
                pid = row.get("id", "")
                if not pid:
                    continue
                batch.append(DiscoveredPage(
                    url=f"https://pleiades.stoa.org/places/{pid}",
                    external_id=f"pleiades-{pid}",
                    title=(row.get("title", "") or f"Pleiades {pid}")[:300],
                    content_hint="ancient_place",
                    depth=0,
                ))
                total += 1
                if total >= max_pages:
                    break
                if len(batch) >= 500:
                    yield DiscoveryBatch(batch, 1, 0, False)
                    batch = []
            if batch:
                yield DiscoveryBatch(batch, 1, 0, False)
        except Exception as exc:
            logger.error("Pleiades download error: %s", exc)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Open Context — archaeological sites
# ---------------------------------------------------------------------------

async def stream_open_context(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    start = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        while total < max_pages:
            try:
                resp = await client.get(
                    "https://opencontext.org/query/.json",
                    params={"type": "subjects", "cat": "oc-gen-cat-site", "rows": 100, "start": start},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                features = data.get("features", [])
                if not features:
                    break

                batch: list[DiscoveredPage] = []
                for feat in features:
                    props = feat.get("properties", {})
                    uri = props.get("uri", "")
                    label = props.get("label", "")
                    if not uri:
                        continue
                    ext_id = uri.rstrip("/").rsplit("/", 1)[-1]
                    batch.append(DiscoveredPage(
                        url=uri if uri.startswith("http") else f"https://opencontext.org{uri}",
                        external_id=f"oc-{ext_id}",
                        title=label[:300],
                        content_hint="archaeological_site",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                if len(features) < 100:
                    break
                start += 100
                await asyncio.sleep(1.0)
            except Exception as exc:
                logger.error("Open Context error at start=%d: %s", start, exc)
                break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# UNESCO World Heritage Sites
# ---------------------------------------------------------------------------

async def stream_unesco_whc(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    offset = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        while total < max_pages:
            try:
                resp = await client.get(
                    "https://data.unesco.org/api/explore/v2.1/catalog/datasets/whc-sites/records",
                    params={"limit": 100, "offset": offset},
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code != 200:
                    resp = await client.get(
                        "https://data.unesco.org/api/explore/v2.0/catalog/datasets/whc001/records",
                        params={"limit": 100, "offset": offset},
                        headers={"User-Agent": USER_AGENT},
                    )
                if resp.status_code != 200:
                    logger.warning("UNESCO API returned %d, trying WHC XML list", resp.status_code)
                    resp = await client.get(
                        "https://whc.unesco.org/en/list/xml/",
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code == 200:
                        import xml.etree.ElementTree as ET
                        try:
                            root = ET.fromstring(resp.content)
                            batch: list[DiscoveredPage] = []
                            for row in root.iter("row"):
                                site_el = row.find("site")
                                id_el = row.find("id_number")
                                if id_el is not None and id_el.text:
                                    site_id = id_el.text.strip()
                                    name = site_el.text.strip() if site_el is not None and site_el.text else f"Site {site_id}"
                                    batch.append(DiscoveredPage(
                                        url=f"https://whc.unesco.org/en/list/{site_id}",
                                        external_id=f"unesco-{site_id}",
                                        title=name[:300],
                                        content_hint="world_heritage_site",
                                        depth=0,
                                    ))
                                    total += 1
                                    if total >= max_pages:
                                        break
                            if batch:
                                yield DiscoveryBatch(batch, 1, 0, False)
                        except Exception as exc:
                            logger.error("UNESCO XML parse error: %s", exc)
                    break

                data = resp.json()
                records = data.get("results", data.get("records", []))
                if not records:
                    break

                batch_list: list[DiscoveredPage] = []
                for rec in records:
                    fields = rec.get("record", {}).get("fields", rec.get("fields", rec))
                    site_id = str(fields.get("id_number", fields.get("unique_number", fields.get("id_no", ""))))
                    name = fields.get("name_en", fields.get("site", fields.get("name", "")))
                    if not site_id or site_id == "None":
                        continue
                    batch_list.append(DiscoveredPage(
                        url=f"https://whc.unesco.org/en/list/{site_id}",
                        external_id=f"unesco-{site_id}",
                        title=str(name)[:300],
                        content_hint="world_heritage_site",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch_list:
                    yield DiscoveryBatch(batch_list, 1, 0, False)
                if len(records) < 100:
                    break
                offset += 100
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.error("UNESCO WHC error at offset %d: %s", offset, exc)
                break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Wikidata — ancient locations
# ---------------------------------------------------------------------------

WD_LOCATION_QUERIES = [
    # Archaeological sites (direct instance)
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q839954 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Pyramids
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q12516 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Ziggurats
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q104555 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Ancient temples
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q44539 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Megalithic monuments
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q1151419 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Ancient Roman buildings
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q24354 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Ruins
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q109607 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Ancient cities (town of the ancient world)
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q15661340 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Tell (archaeological mound)
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q194195 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Mesoamerican pyramids (step pyramids)
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q1636022 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
    # Pre-Columbian sites in Americas (archaeological site + country in Americas)
    """SELECT ?item ?itemLabel ?coord WHERE {{
      ?item wdt:P31 wd:Q839954 .
      ?item wdt:P625 ?coord .
      ?item wdt:P17 ?country .
      VALUES ?country {{ wd:Q96 wd:Q298 wd:Q241 wd:Q419 wd:Q414 wd:Q750 wd:Q736 wd:Q733 wd:Q717 wd:Q739 wd:Q774 wd:Q786 wd:Q800 }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }} LIMIT {limit} OFFSET {offset}""",
]

async def stream_wikidata_locations(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    seen_qids: set[str] = set()
    async with httpx.AsyncClient(timeout=120.0) as client:
        for query_template in WD_LOCATION_QUERIES:
            if total >= max_pages:
                break
            offset = 0
            limit = 200
            while total < max_pages:
                try:
                    query = query_template.format(limit=limit, offset=offset)
                    resp = await client.get(
                        WIKIDATA_SPARQL,
                        params={"query": query, "format": "json"},
                        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                    )
                    if resp.status_code == 429 or resp.status_code == 504:
                        logger.warning("Wikidata SPARQL %d, waiting 30s", resp.status_code)
                        await asyncio.sleep(30.0)
                        continue
                    if resp.status_code != 200:
                        logger.warning("Wikidata SPARQL %d for query, skipping", resp.status_code)
                        break
                    results = resp.json().get("results", {}).get("bindings", [])
                    if not results:
                        break

                    batch: list[DiscoveredPage] = []
                    for r in results:
                        item_uri = r.get("item", {}).get("value", "")
                        qid = item_uri.rsplit("/", 1)[-1] if item_uri else ""
                        label = r.get("itemLabel", {}).get("value", qid)
                        if not qid or qid in seen_qids:
                            continue
                        seen_qids.add(qid)
                        batch.append(DiscoveredPage(
                            url=item_uri,
                            external_id=f"wd-loc-{qid}",
                            title=label[:300],
                            content_hint="ancient_location",
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break
                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)
                    if len(results) < limit:
                        break
                    offset += limit
                    await asyncio.sleep(5.0)
                except Exception as exc:
                    logger.error("Wikidata locations error: %s", exc)
                    break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# OpenAlex — academic papers
# ---------------------------------------------------------------------------

async def stream_openalex(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    cursor = "*"
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        while total < max_pages and cursor:
            try:
                resp = await client.get(
                    "https://api.openalex.org/works",
                    params={
                        "filter": "concepts.id:C121332964|C15744967|C100970517",
                        "per-page": 100, "cursor": cursor,
                        "mailto": "research@projectedin.com",
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                results = data.get("results", [])
                cursor = data.get("meta", {}).get("next_cursor")

                if not results:
                    break

                batch: list[DiscoveredPage] = []
                for work in results:
                    work_id = work.get("id", "")
                    oa_id = work_id.rsplit("/", 1)[-1] if work_id else ""
                    title = work.get("display_name", oa_id)
                    if not oa_id:
                        continue
                    batch.append(DiscoveredPage(
                        url=work_id,
                        external_id=f"oa-{oa_id}",
                        title=str(title)[:300],
                        content_hint="academic_paper",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                if len(results) < 100 or not cursor:
                    break
                await asyncio.sleep(0.2)
            except Exception as exc:
                logger.error("OpenAlex error: %s", exc)
                break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# CORE — open access papers
# ---------------------------------------------------------------------------

async def stream_core(api_key: str = "", max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    if not api_key:
        logger.warning("No CORE API key — skipping")
        yield DiscoveryBatch([], 0, 0, True); return

    total = 0
    offset = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while total < max_pages:
            try:
                resp = await client.get(
                    "https://api.core.ac.uk/v3/search/works",
                    params={"q": "cuneiform OR mesopotamia OR ancient near east", "limit": 100, "offset": offset},
                    headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break

                batch: list[DiscoveredPage] = []
                for work in results:
                    core_id = str(work.get("id", ""))
                    title = work.get("title", core_id)
                    if not core_id:
                        continue
                    batch.append(DiscoveredPage(
                        url=f"https://core.ac.uk/works/{core_id}",
                        external_id=f"core-{core_id}",
                        title=str(title)[:300],
                        content_hint="academic_paper",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                if len(results) < 100:
                    break
                offset += 100
                await asyncio.sleep(1.0)
            except Exception as exc:
                logger.error("CORE error: %s", exc)
                break
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# TLA (Thesaurus Linguae Aegyptiae) – Hugging Face datasets
# ---------------------------------------------------------------------------

TLA_HF_DATASETS = [
    ("thesaurus-linguae-aegyptiae/tla-Earlier_Egyptian_original-v18-premium", "Earlier Egyptian"),
    ("thesaurus-linguae-aegyptiae/tla-late_egyptian-v19-premium", "Late Egyptian"),
    ("thesaurus-linguae-aegyptiae/tla-demotic-v18-premium", "Demotic"),
]

HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"


async def stream_tla(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover Egyptian hieroglyphic texts from TLA Hugging Face datasets."""
    total = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for dataset_id, period_label in TLA_HF_DATASETS:
            if total >= max_pages:
                break
            offset = 0
            page_size = 100
            while total < max_pages:
                try:
                    retries = 0
                    resp = None
                    while retries < 5:
                        resp = await client.get(
                            HF_ROWS_URL,
                            params={
                                "dataset": dataset_id,
                                "config": "default",
                                "split": "train",
                                "offset": offset,
                                "length": page_size,
                            },
                            headers={"User-Agent": USER_AGENT},
                        )
                        if resp.status_code == 429:
                            wait = 10 * (2 ** retries)
                            logger.warning("TLA HF 429, waiting %ds (retry %d)", wait, retries + 1)
                            await asyncio.sleep(wait)
                            retries += 1
                            continue
                        break
                    if resp is None or resp.status_code != 200:
                        logger.warning("TLA HF %d for %s offset %d", resp.status_code if resp else 0, dataset_id, offset)
                        break
                    data = resp.json()
                    rows = data.get("rows", [])
                    if not rows:
                        break
                    batch: list[DiscoveredPage] = []
                    for row_obj in rows:
                        row = row_obj.get("row", {})
                        row_idx = row_obj.get("row_idx", offset)
                        ds_short = dataset_id.rsplit("/", 1)[-1]
                        ext_id = f"tla-{ds_short}-{row_idx}"
                        title_parts = []
                        hieroglyphs = row.get("hieroglyphs", "")
                        if hieroglyphs:
                            title_parts.append(hieroglyphs[:60])
                        translation = row.get("translation", "")
                        if translation:
                            title_parts.append(translation[:120])
                        title = " — ".join(title_parts) if title_parts else f"TLA {period_label} #{row_idx}"
                        batch.append(DiscoveredPage(
                            url=f"https://huggingface.co/datasets/{dataset_id}",
                            external_id=ext_id,
                            title=title[:300],
                            content_hint="egyptian_text",
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break
                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)
                    if len(rows) < page_size:
                        break
                    offset += page_size
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    logger.error("TLA discovery error: %s", exc)
                    break
    logger.info("TLA discovery complete: %d texts", total)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Sacred Texts (via Wayback Machine) – BCE texts
# ---------------------------------------------------------------------------

SACRED_TEXTS_CATEGORIES = {
    "egy": ("Egyptian", -3000, -300),
    "ane": ("Ancient Near East", -3000, -300),
    "hin": ("Hindu (Vedic/Epic)", -1500, 0),
    "bud": ("Buddhism", -500, 0),
    "cfu": ("Confucianism", -600, 0),
    "tao": ("Taoism", -600, 0),
    "zor": ("Zoroastrianism", -1500, -300),
    "jai": ("Jainism", -600, 0),
    "jud": ("Judaism", -1200, 0),
    "cla": ("Classics (Greek/Roman)", -800, 0),
    "sbe": ("Sacred Books of the East", -1500, 0),
}

CDX_API = "https://web.archive.org/cdx/search/cdx"


async def stream_sacred_texts(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover BCE-era texts from sacred-texts.com via Wayback Machine CDX API."""
    total = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        for cat_path, (label, date_start, date_end) in SACRED_TEXTS_CATEGORIES.items():
            if total >= max_pages:
                break
            try:
                resp = await client.get(
                    CDX_API,
                    params={
                        "url": f"sacred-texts.com/{cat_path}/*",
                        "output": "json",
                        "filter": ["statuscode:200", "mimetype:text/html"],
                        "collapse": "urlkey",
                        "fl": "timestamp,original",
                        "limit": 20000,
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code != 200:
                    logger.warning("CDX %d for %s", resp.status_code, cat_path)
                    continue
                rows = resp.json()
                if not rows or len(rows) < 2:
                    continue

                batch: list[DiscoveredPage] = []
                for row in rows[1:]:
                    timestamp, original_url = row[0], row[1]
                    original_url = original_url.replace("http://", "https://").replace(":80/", "/")
                    if not original_url.endswith(".htm"):
                        continue
                    url_lower = original_url.lower()
                    if any(skip in url_lower for skip in ["/cdshop/", "/search", "contact.htm", "faq.htm", "/img/"]):
                        continue

                    filename = url_lower.rsplit("/", 1)[-1].replace(".htm", "")
                    if filename in ("index", "index2", "00", "errata"):
                        continue
                    if filename.endswith("00") and len(filename) <= 6:
                        continue

                    path = re.sub(r"https?://[^/]+/", "", original_url)
                    ext_id = f"st-{path.replace('/', '-').replace('.htm', '')}"
                    if len(ext_id) > 250:
                        ext_id = ext_id[:250]

                    title_parts = path.replace("/", " > ").replace(".htm", "").replace("_", " ")
                    title = f"{label}: {title_parts}"

                    batch.append(DiscoveredPage(
                        url=original_url,
                        external_id=ext_id,
                        title=title[:300],
                        content_hint="sacred_text",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break

                if batch:
                    for i in range(0, len(batch), 500):
                        yield DiscoveryBatch(batch[i:i + 500], 1, 0, False)
                logger.info("Sacred-texts %s: %d pages", cat_path, len(batch))
                await asyncio.sleep(2.0)

            except Exception as exc:
                logger.error("Sacred-texts CDX error for %s: %s", cat_path, exc)
                continue

    logger.info("Sacred-texts discovery complete: %d pages", total)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Wikipedia Ancient World — category-spider + search discovery
# ---------------------------------------------------------------------------

WIKI_API = "https://en.wikipedia.org/w/api.php"

WIKI_SEED_CATEGORIES = [
    # ── MESOPOTAMIA ──────────────────────────────────────────────────────────
    "Ancient_Mesopotamia", "Sumerian_mythology", "Akkadian_literature",
    "Babylonian_mythology", "Assyrian_mythology", "Cuneiform",
    "Sumerian_literature", "Mesopotamian_religion", "Ziggurats",
    "Ancient_Mesopotamian_cities", "Akkadian_Empire", "Babylonia",
    "Assyria", "Ur", "Uruk", "Eridu", "Nineveh", "Nippur", "Lagash",
    "Sumerian_language", "Akkadian_language", "Sumerian_King_List",
    "Enuma_Elish", "Epic_of_Gilgamesh", "Atrahasis_Epic",
    "Mesopotamian_astronomy", "Babylonian_astrology",
    "Mesopotamian_mythology", "Mesopotamian_law",
    "Code_of_Hammurabi", "Sumerian_temple_hymns",
    "Cylinder_seals", "Neo-Babylonian_Empire",
    "Neo-Assyrian_Empire", "Old_Babylonian_Empire",
    "Ancient_Mesopotamian_units_of_measurement",
    "Mesopotamian_omen_literature",
    # ── EGYPT ────────────────────────────────────────────────────────────────
    "Ancient_Egyptian_religion", "Ancient_Egyptian_texts",
    "Ancient_Egyptian_funerary_texts", "Egyptian_mythology",
    "Pyramids_of_Egypt", "Ancient_Egyptian_temples",
    "Ancient_Egyptian_tombs", "Pharaohs", "Hieroglyphs",
    "Ancient_Egyptian_literature", "Ancient_Egyptian_society",
    "Pyramid_Texts", "Coffin_Texts", "Book_of_the_Dead",
    "Ancient_Egyptian_deities", "Ancient_Egyptian_art",
    "Ancient_Egyptian_architecture", "Ancient_Egyptian_papyri",
    "Predynastic_Egypt", "Early_Dynastic_Period_(Egypt)",
    "Old_Kingdom_of_Egypt", "Middle_Kingdom_of_Egypt",
    "New_Kingdom_of_Egypt", "Late_Period_of_ancient_Egypt",
    "Thebes,_Egypt", "Memphis,_Egypt", "Heliopolis_(ancient)",
    "Karnak", "Valley_of_the_Kings", "Amarna",
    "Egyptian_cosmology", "Egyptian_sacred_geography",
    "Ancient_Egyptian_stelae", "Rosetta_Stone",
    "Coptic_literature", "Demotic_(Egyptian)", "Ancient_Egyptian_scripts",
    # ── LEVANT / CANAAN / PHOENICIA / UGARIT / ANCIENT ISRAEL ────────────────
    "Ancient_Canaanite_religion", "Ugarit", "Phoenicia",
    "Ancient_Israel_and_Judah", "Hebrew_Bible", "Dead_Sea_Scrolls",
    "Second_Temple_Judaism", "Israelite_religion",
    "Ancient_Levant", "Philistines", "Baal_Cycle",
    "Ugaritic_language", "Ugaritic_texts", "Phoenician_language",
    "Phoenician_inscriptions", "Ancient_Israelite_cuisine",
    "Temple_in_Jerusalem", "Solomon's_Temple",
    "Judah_(biblical_kingdom)", "Kingdom_of_Israel_(united_monarchy)",
    "Canaanite_languages", "Aramaic_language", "Nabataeans",
    "Edom", "Moab", "Ammon_(Transjordan)",
    # ── ANATOLIA ─────────────────────────────────────────────────────────────
    "Hittites", "Hittite_mythology_and_religion", "Urartu",
    "Phrygia", "Lydia", "Luwians", "Hittite_language",
    "Hittite_cuneiform", "Ancient_Anatolia", "Çatalhöyük",
    "Troy", "Gordion", "Hattusa",
    "Phrygian_language", "Lydian_language", "Hurrians",
    "Mitanni", "Kizzuwatna",
    # ── IRAN / PERSIA / ELAM / ZOROASTRIANISM ────────────────────────────────
    "Zoroastrianism", "Avesta", "Achaemenid_Empire",
    "Elamite_civilization", "Medes", "Ancient_Iranian_religion",
    "Persepolis", "Pasargadae", "Gathas",
    "Avestan_language", "Old_Persian_language",
    "Parthian_Empire", "Elamite_language",
    "Iranian_mythology", "Ahura_Mazda",
    "Behistun_Inscription", "Cyrus_the_Great",
    "Darius_the_Great", "Xerxes_I",
    # ── VEDIC INDIA / INDUS ──────────────────────────────────────────────────
    "Vedas", "Vedic_period", "Rigveda", "Upanishads",
    "Hindu_mythology", "Hindu_cosmology", "Brahmanas",
    "Indus_Valley_civilisation", "Ancient_Indian_history",
    "Samaveda", "Yajurveda", "Atharvaveda",
    "Aranyakas", "Sanskrit_literature",
    "Vedic_mythology", "Vedic_Sanskrit",
    "Harappa", "Mohenjo-daro", "Indus_script",
    "Ancient_Indian_philosophy", "Mimamsa",
    "Vedic_ritual", "Soma_(drink)",
    # ── EPIC INDIA / EARLY HINDUISM ──────────────────────────────────────────
    "Mahabharata", "Ramayana", "Puranas",
    "Hindu_texts", "Sanskrit_texts",
    "Hindu_epic_poetry", "Bhagavata_Purana",
    "Vishnu_Purana", "Shiva_Purana",
    "Ancient_Indian_epics", "Manu_Smriti",
    # ── BUDDHISM / JAINISM ───────────────────────────────────────────────────
    "Buddhist_texts", "Pali_Canon", "Early_Buddhism",
    "Buddhist_mythology", "Jain_texts", "Jainism",
    "Ashoka", "Stupas", "Tipitaka",
    "Theravada", "Jataka_tales", "Dhammapada",
    "Jain_philosophy", "Mahavira",
    "Buddhist_art", "Buddhist_pilgrimage_sites",
    "Pali_language", "Buddhist_cosmology",
    # ── SHANG / ZHOU CHINA ──────────────────────────────────────────────────
    "Shang_dynasty", "Zhou_dynasty", "Oracle_bones",
    "Chinese_classics", "Chinese_mythology",
    "Confucianism", "Taoism", "Warring_States_period",
    "Ancient_Chinese_texts", "I_Ching",
    "Spring_and_Autumn_period", "Eastern_Zhou_dynasty",
    "Chinese_Bronze_Age", "Zhou_ritual_bronzes",
    "Hundred_Schools_of_Thought",
    "Book_of_Songs", "Book_of_Documents",
    "Analects", "Tao_Te_Ching",
    "Chinese_oracle_bone_script", "Chinese_bronzeware_script",
    "Classic_of_Mountains_and_Seas", "Chinese_creation_myth",
    "Legalism_(Chinese_philosophy)", "Mohism",
    "Ancient_Chinese_astronomy",
    # ── ANCIENT KOREA / JAPAN ────────────────────────────────────────────────
    "Ancient_Korea", "Korean_mythology",
    "Gojoseon", "Three_Kingdoms_of_Korea",
    "Jōmon_period", "Yayoi_period", "Japanese_mythology",
    "Kojiki", "Nihon_Shoki", "Kofun_period",
    "Korean_Bronze_Age", "Korean_prehistoric_art",
    # ── CENTRAL ASIA / STEPPE ───────────────────────────────────────────────
    "Scythians", "Saka", "Bactria", "Sogdia",
    "Eurasian_Steppe", "Bronze_Age_Central_Asia",
    "Oxus_civilization", "BMAC",
    "Scythian_art", "Scythian_religion",
    "Pazyryk_culture", "Saka_people",
    "Kushan_Empire", "Sogdian_language",
    "Ancient_Bactria", "Achaemenid_Bactria",
    # ── MINOAN / MYCENAEAN / AEGEAN ──────────────────────────────────────────
    "Minoan_civilization", "Mycenaean_Greece",
    "Linear_A", "Linear_B", "Aegean_civilizations",
    "Minoan_religion", "Minoan_art",
    "Mycenaean_religion", "Bronze_Age_Greece",
    "Knossos", "Akrotiri,_Santorini", "Tiryns",
    "Mycenae", "Cyclopean_walls",
    # ── ARCHAIC / CLASSICAL GREECE ───────────────────────────────────────────
    "Ancient_Greek_religion", "Greek_mythology",
    "Homeric_epics", "Ancient_Greek_literature",
    "Ancient_Greek_temples", "Greek_tragedy",
    "Pre-Socratic_philosophy", "Ancient_Greek_cities",
    "Iliad", "Odyssey", "Theogony_(Hesiod)",
    "Works_and_Days", "Greek_lyric_poetry",
    "Eleusinian_Mysteries", "Orphism_(religion)",
    "Olympian_gods", "Greek_hero_cult",
    "Ancient_Greek_art", "Ancient_Greek_coinage",
    "Delphi", "Olympia,_Greece", "Acropolis_of_Athens",
    "Ancient_Sparta", "Ancient_Athens",
    "Classical_Athens", "Hellenistic_period",
    "Ancient_Greek_philosophy", "Plato", "Aristotle",
    "Stoicism", "Epicureanism",
    # ── ETRUSCAN / EARLY ROME / ITALIC ──────────────────────────────────────
    "Etruscan_civilization", "Etruscan_mythology",
    "Roman_mythology", "Roman_Republic",
    "Religion_in_ancient_Rome", "Italic_peoples",
    "Etruscan_language", "Etruscan_art",
    "Roman_religion", "Roman_augury",
    "Founding_of_Rome", "Seven_Kings_of_Rome",
    "Roman_Forum", "Roman_temples",
    "Ancient_Roman_literature", "Latin_literature",
    # ── CELTIC / IRON AGE EUROPE ────────────────────────────────────────────
    "Celtic_mythology", "Celts", "Gauls",
    "Iron_Age_Europe", "Celtic_religion",
    "Celtic_art", "Celtic_languages",
    "Druids", "Celtic_sacred_sites",
    "Hallstatt_culture", "La_Tène_culture",
    "Ancient_Ireland", "Insular_Celtic_languages",
    "Celtic_polytheism",
    # ── GERMANIC / NORDIC BRONZE & IRON AGE ─────────────────────────────────
    "Norse_mythology", "Germanic_paganism",
    "Nordic_Bronze_Age", "Scandinavian_archaeology",
    "Norse_cosmology", "Eddas",
    "Proto-Germanic_religion", "Germanic_tribes",
    "Rock_art_in_Scandinavia", "Vendel_period",
    # ── NUBIA / KUSH / NORTH AFRICA ─────────────────────────────────────────
    "Kingdom_of_Kush", "Nubia", "Meroë",
    "Carthage", "Phoenician_colonies",
    "Ancient_Sudan", "Kerma_culture",
    "Napatan_period", "Nubian_pyramids",
    "Punic_wars", "Punic_language",
    "Berber_history", "Ancient_Libya",
    "Cyrenaica", "Ancient_Carthage",
    # ── HORN OF AFRICA / SUB-SAHARAN ────────────────────────────────────────
    "Aksumite_Empire", "Horn_of_Africa", "Nok_culture",
    "African_archaeology", "African_mythology",
    "Pre-Aksumite_period", "D'mt",
    "Bantu_expansion", "Iron_Age_in_Africa",
    "West_African_Bronze_Age",
    # ── MESOAMERICA ─────────────────────────────────────────────────────────
    "Olmecs", "Maya_civilization", "Maya_mythology",
    "Zapotec_civilization", "Mixtec", "Teotihuacan",
    "Mesoamerican_writing_systems", "Mesoamerican_calendars",
    "Mesoamerican_pyramids", "Popol_Vuh",
    "Maya_script", "Maya_Long_Count_calendar",
    "Olmec_colossal_heads", "Olmec_religion",
    "Monte_Albán", "Zapotec_writing",
    "Izapa", "Tlatilco_culture",
    "Mesoamerican_cosmology", "Mesoamerican_religion",
    "Mesoamerican_literature",
    # ── SOUTH AMERICA / ANDES ───────────────────────────────────────────────
    "Norte_Chico_civilization", "Chavín_culture",
    "Paracas_culture", "Nazca_culture", "Moche_culture",
    "Pre-Columbian_era", "Andean_civilizations",
    "Inca_mythology", "Caral",
    "Nazca_Lines", "Cupisnique_culture",
    "Andean_cosmology", "Viracocha",
    "Tiwanaku", "Wari_Empire",
    # ── OCEANIA ──────────────────────────────────────────────────────────────
    "Australian_Aboriginal_mythology", "Dreamtime",
    "Aboriginal_Australians", "Lapita_culture",
    "Polynesian_mythology", "Polynesian_navigation",
    "Australian_Aboriginal_sacred_sites",
    "Pacific_mythology", "Melanesian_mythology",
    "Maori_mythology", "Hawaiian_mythology",
    # ── CROSS-CUTTING THEMES ─────────────────────────────────────────────────
    "Creation_myths", "Flood_myths", "Ancient_astronomy",
    "Ancient_cosmology", "Archaeological_sites",
    "Ancient_religions", "Ancient_literature",
    "Oral_tradition", "Ancient_law", "King_lists",
    "Ancient_trade", "Ancient_maps",
    "Undeciphered_writing_systems", "Sacred_texts",
    "Ancient_writing_systems", "Ancient_languages",
    "Bronze_Age", "Iron_Age", "Neolithic",
    "Chalcolithic", "Megalithic_architecture",
    "Ancient_oral_literature", "Ancient_sacred_sites",
    "Ancient_temples", "Ancient_inscriptions",
    "Archaeological_cultures", "Funerary_art",
    "Ritual_objects", "Ancient_cosmographies",
    "Sacred_geography", "Ancient_trade_routes",
    "Nomadic_pastoralism", "Ancient_agriculture",
    "Mythology_by_culture", "Flood_geology_in_mythology",
]

WIKI_SEARCH_QUERIES = [
    # Mesopotamia
    "ancient creation myth Mesopotamia", "Sumerian king list",
    "Epic of Gilgamesh", "Enuma Elish Babylonian creation",
    "Atrahasis flood myth", "Code of Hammurabi",
    "Sumerian temple hymn", "Sumerian flood myth",
    "Akkadian mythology", "Babylonian cosmology",
    "Assyrian royal annals", "Neo-Assyrian texts",
    "cuneiform tablet translation", "Mesopotamian omen text",
    "Uruk period archaeology", "Eridu ancient city",
    "ziggurat ancient Mesopotamia", "cylinder seal Mesopotamia",
    # Egypt
    "Pyramid Texts ancient Egypt", "Coffin Texts ancient Egypt",
    "Book of the Dead Egyptian", "Egyptian creation myth",
    "pharaoh inscription ancient Egypt", "Egyptian papyrus ancient",
    "hieroglyphic inscription translation", "ancient Egyptian tomb art",
    "Egyptian Book of Gates", "Amduat Egyptian underworld",
    "Karnak temple inscriptions", "Valley of the Kings burial",
    "Egyptian kingship divine", "Amarna period religion",
    # Levant
    "Baal Cycle Ugarit", "Dead Sea Scrolls translation",
    "Ugaritic mythology", "Phoenician inscription ancient",
    "ancient Israelite religion", "Canaanite mythology",
    "Hebrew Bible ancient layers", "Second Temple Judaism texts",
    "Tel Dan inscription", "Siloam inscription",
    # Anatolia
    "Hittite mythology storm god", "Hittite royal annals",
    "Hittite ritual texts", "Hittite cuneiform tablets",
    "Luwian hieroglyphic inscription", "Urartian inscription",
    "Troy archaeology Bronze Age", "Çatalhöyük ritual",
    # Iran / Persia
    "Avesta Zoroastrian texts", "Gathas Zarathustra",
    "Achaemenid royal inscription", "Behistun inscription",
    "Elamite cuneiform", "ancient Iranian cosmology",
    "Zoroastrian creation myth", "Persian sacred fire temple",
    # Vedic India
    "Rigveda hymns ancient", "Upanishad philosophy ancient",
    "Vedic ritual ancient India", "Atharva Veda",
    "Brahmana texts Vedic", "Vedic creation myth",
    "Indus Valley seal", "Harappa ritual archaeology",
    "Manu flood myth India", "Soma ritual Vedic",
    # Epic India
    "Mahabharata ancient layers", "Ramayana ancient epic",
    "Puranic cosmology", "Hindu flood myth Manu",
    "Mahabharata war archaeology",
    # Buddhism / Jainism
    "Pali Canon Tipitaka early Buddhism", "Jataka tales ancient",
    "Dhammapada ancient text", "Buddhist cosmology ancient",
    "Ashoka edict inscription", "early Jain texts Agamas",
    "stupa archaeology ancient India",
    # China
    "Oracle bone inscription Shang dynasty",
    "Tao Te Ching ancient", "Analects Confucius",
    "I Ching divination ancient", "Book of Songs Shijing",
    "Classic Mountains Seas Chinese mythology",
    "Zhou dynasty ritual bronze", "Chinese creation myth Pangu",
    "Huainanzi cosmology", "Shan Hai Jing",
    # Korea / Japan
    "Gojoseon ancient Korea mythology", "Dangun foundation myth",
    "Kojiki Japanese mythology", "Nihon Shoki ancient",
    "Yayoi period ritual Japan", "Jomon archaeology Japan",
    # Central Asia / Steppe
    "Scythian burial mound kurgan", "Scythian art animal style",
    "BMAC Oxus civilization Bronze Age",
    "Bactrian mythology ancient", "steppe nomad religion",
    "Pazyryk burial ritual", "Sogdian ancient texts",
    # Aegean
    "Linear A Minoan undeciphered", "Linear B Mycenaean",
    "Minoan religion bull cult", "Mycenaean shaft grave",
    "Bronze Age Aegean collapse",
    # Greece
    "Iliad Homer epic", "Odyssey Homer",
    "Theogony Hesiod creation", "Works and Days Hesiod",
    "Orphic mysteries ancient", "Eleusinian Mysteries initiation",
    "Greek oracle Delphi", "ancient Greek hero cult",
    "Greek lyric poetry archaic", "pre-Socratic cosmology",
    "Olympian gods Greek", "ancient Greek temple ritual",
    # Etruscans / Rome
    "Etruscan tomb inscription", "Etruscan haruspicy divination",
    "Roman foundation myth Romulus", "Roman augury religion",
    "Roman Republic religion sacred", "Latin literature ancient",
    # Celtic
    "Celtic sacred grove nemeton", "Druids ancient ritual",
    "Celtic mythology ancient", "La Tène ritual site",
    "Celtic oral tradition", "Irish mythology ancient layers",
    # Norse / Germanic
    "Norse creation myth Ymir", "Eddas cosmology",
    "runic inscription ancient", "Nordic Bronze Age rock art",
    "Germanic religion ancient", "Norse mythology ancient",
    # Nubia / North Africa
    "Nubian pyramid Meroe ancient", "Kingdom of Kush religion",
    "Napatan temple inscriptions", "Carthage Tophet sacrifice",
    "Punic religious inscription", "ancient Libya Berber",
    # Sub-Saharan Africa
    "Nok terracotta Nigeria ancient", "Aksumite inscription ancient",
    "Pre-Aksumite ritual Ethiopia", "West African oral tradition ancient",
    "Iron Age Africa archaeology",
    # Mesoamerica
    "Olmec colossal head sacred", "Popol Vuh creation myth",
    "Maya Long Count calendar ancient", "Zapotec Monte Alban inscription",
    "Teotihuacan pyramid cosmology", "Maya stela inscription",
    "Maya codex ancient", "Mesoamerican creation myth",
    "Olmec religion La Venta", "Maya astronomical text",
    # South America
    "Caral Supe Norte Chico ancient", "Chavin de Huantar cult",
    "Nazca Lines geoglyph ancient", "Viracocha creator Andes",
    "Paracas burial ritual", "Moche ritual sacrifice",
    "Andean flood myth Viracocha",
    # Oceania
    "Dreamtime Aboriginal sacred", "songlines Aboriginal Australia",
    "Aboriginal rock art ancient", "Lapita pottery Pacific archaeology",
    "Polynesian navigation ancient", "Maori creation myth ancient",
    "Hawaiian mythology creation",
    # Cross-cutting
    "ancient flood narrative worldwide", "sacred mountain ancient religion",
    "ancient astronomical observation", "megalith ancient ritual",
    "ancient oral tradition preserved", "undeciphered ancient script",
    "ancient king list", "ancient law code",
    "ancient trade route archaeology", "sacred geography ancient",
    "ancient burial ritual worldwide", "cosmogony ancient religion",
]


_WIKI_SKIP_TITLE_PREFIXES = (
    "List of ", "Lists of ", "Index of ", "Outline of ",
    "Template:", "Wikipedia:", "Portal:", "Draft:", "Category:",
    "File:", "Help:", "Module:", "MediaWiki:", "Talk:",
    "Timeline of ", "Bibliography of ", "Historiography of ",
)
_WIKI_SKIP_TITLE_KEYWORDS = {
    "video game", "film)", "movie)", "novel)", "TV series", "television",
    "album)", "song)", "band)", "manga)", "anime)", "comics)",
    "(game)", "card game", "board game", "role-playing game",
    "(character)", "in popular culture", "in fiction",
    "football", "soccer", "basketball", "baseball", "cricket",
    "rugby", "tennis", "hockey",
    "university", "school", "college", "institute",
    "company", "corporation", "airline",
    "ethnic", "diaspora", "cuisine", "restaurant",
    "modern", "contemporary",
    "municipality", "district", "county", "province",
    "disambiguation",
    # Musical instruments (modern/folk)
    "fiddle", "violin", "guitar", "banjo", "mandolin", "ukulele",
    "accordion", "harmonica", "piano", "drum kit", "bass guitar",
    "folk music", "folk dance", "folk song",
    # Modern people / scholars
    "archaeologist", "egyptologist", "assyriologist", "historian",
    "philologist", "orientalist", "antiquarian", "curator",
    "collector", "explorer", "expedition",
    "museum", "gallery",
    # Modern nations / politics
    "government", "politics", "political party", "election",
    "national team", "military of", "army of", "navy of",
    "war of independence", "civil war",
    # Modern infrastructure
    "airport", "railway", "highway", "stadium",
    # Biology / botany / zoology
    "(plant)", "(insect)", "(bird)", "(fish)", "(spider)", "(moth)",
    "(butterfly)", "(beetle)", "(genus)", "(species)", "(fungus)",
    "(lichen)", "(moss)", "(fern)", "(algae)", "(snake)", "(lizard)",
    "(frog)", "(crab)", "(snail)", "(worm)", "(fly)", "(wasp)",
    "(bee)", "(ant)", "cultivar", "hybrid)",
    # Geography / weather / geology
    "monsoon", "climate", "weather", "earthquake", "volcano",
    "river basin", "watershed", "glacier",
    # Astronomy (modern)
    "(asteroid)", "(comet)", "(mineral)", "crater)",
    # Sports / broadcasting
    "broadcaster", "sportscaster", "commentator",
    "championship", "tournament", "league",
    "f.c.", "a.f.c.", "fc)",
    # Modern religion
    "church)", "parish", "diocese", "congregation",
    "mosque)", "synagogue)",
}
_WIKI_SKIP_SUBCAT_KEYWORDS = {
    "video game", "film", "novel", "television", "sport",
    "football", "people by", "ethnic", "diaspora", "cuisine",
    "modern", "contemporary", "21st-century", "20th-century",
    "19th-century", "18th-century", "17th-century", "16th-century",
    "in popular culture", "in fiction", "in media",
    "companies", "organizations", "schools", "universities",
    "archaeologist", "egyptologist", "assyriologist", "historian",
    "scholars", "researchers", "academics", "professors",
    "births", "deaths", "alumni", "graduates",
    "collectors", "curators", "explorers", "expeditions",
    "museums", "galleries", "libraries",
    "politics", "political", "government", "military",
    "wars of", "battles of the",
    "national team", "airport", "railway",
    "populated places", "cities in", "towns in", "villages in",
    "neighborhoods", "streets in",
    "japanese legends", "japanese folklore",
}


def _wiki_title_ok(title: str) -> bool:
    """Return True if this Wikipedia title looks like relevant ancient/historical content."""
    if any(title.startswith(p) for p in _WIKI_SKIP_TITLE_PREFIXES):
        return False
    tl = title.lower()
    if any(kw in tl for kw in _WIKI_SKIP_TITLE_KEYWORDS):
        return False
    return True


async def stream_wikipedia_ancient(max_pages: int = 200_000) -> AsyncIterator[DiscoveryBatch]:
    """Spider Wikipedia categories (4 levels deep) and searches for ancient/BCE content."""
    import wikipediaapi

    wiki = wikipediaapi.AsyncWikipedia(
        user_agent="EdenIngestion/1.0 (https://projectedin.com; eden@projectedin.com)",
        language="en",
        max_retries=5,
        retry_wait=3.0,
    )

    total = 0
    seen_titles: set[str] = set()
    seen_cats: set[str] = set()

    async def _spider_category(
        cat_name: str, depth: int, max_depth: int = 4,
    ) -> AsyncIterator[DiscoveryBatch]:
        nonlocal total
        if total >= max_pages:
            return
        if cat_name in seen_cats:
            return
        seen_cats.add(cat_name)

        try:
            cat_page = wiki.page(f"Category:{cat_name}")
            try:
                members = await cat_page.categorymembers
            except Exception as exc:
                logger.warning("Wikipedia category %s fetch failed: %s", cat_name, exc)
                return

            batch: list[DiscoveredPage] = []
            subcats: list[str] = []

            for title, member in members.items():
                if total >= max_pages:
                    break
                if member.ns == wikipediaapi.Namespace.CATEGORY:
                    sub_name = title.removeprefix("Category:")
                    sub_lower = sub_name.lower()
                    if not any(skip in sub_lower for skip in _WIKI_SKIP_SUBCAT_KEYWORDS):
                        subcats.append(sub_name)
                    continue
                if member.ns != wikipediaapi.Namespace.MAIN:
                    continue
                if title in seen_titles or not _wiki_title_ok(title):
                    continue
                seen_titles.add(title)
                page_id = await member.pageid
                batch.append(DiscoveredPage(
                    url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    external_id=f"wp-{page_id}",
                    title=title[:300],
                    content_hint=f"cat:{cat_name}",
                    depth=depth,
                ))
                total += 1

            if batch:
                yield DiscoveryBatch(batch, 1, 0, False)

            if depth < max_depth:
                for sub_name in subcats:
                    if total >= max_pages:
                        break
                    async for sub_batch in _spider_category(sub_name, depth + 1, max_depth):
                        yield sub_batch

        except Exception as exc:
            logger.error("Wikipedia category %s error: %s", cat_name, exc)

    for seed_cat in WIKI_SEED_CATEGORIES:
        if total >= max_pages:
            break
        async for batch in _spider_category(seed_cat, depth=0):
            yield batch
        logger.info("Wikipedia discovery: %d articles after cat '%s' (%d cats visited)",
                     total, seed_cat, len(seen_cats))

    for query in WIKI_SEARCH_QUERIES:
        if total >= max_pages:
            break
        try:
            results = await wiki.search(query, limit=50)
            batch: list[DiscoveredPage] = []
            for title, page in results.pages.items():
                if title in seen_titles or not _wiki_title_ok(title):
                    continue
                seen_titles.add(title)
                page_id = await page.pageid
                batch.append(DiscoveredPage(
                    url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    external_id=f"wp-{page_id}",
                    title=title[:300],
                    content_hint=f"search:{query[:50]}",
                    depth=0,
                ))
                total += 1
            if batch:
                yield DiscoveryBatch(batch, 1, 0, False)
        except Exception as exc:
            logger.error("Wikipedia search '%s' error: %s", query, exc)
            continue

    logger.info("Wikipedia ancient discovery complete: %d articles, %d categories visited",
                total, len(seen_cats))
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Project Gutenberg — ancient and classical texts
# ---------------------------------------------------------------------------

GUTENBERG_SEARCH_URL = "https://gutendex.com/books"

GUTENBERG_ANCIENT_SUBJECTS = [
    "Ancient history", "Classical literature", "Greek literature",
    "Latin literature", "Mythology", "Ancient Rome", "Ancient Greece",
    "Egypt -- History", "Mesopotamia", "Sumerian", "Babylonia",
    "Assyria", "Persian Empire", "Vedic", "Sanskrit literature",
    "Hindu mythology", "Buddhism", "Zoroastrianism", "Bible",
    "Dead Sea scrolls", "Archaeology", "Cuneiform", "Hieroglyphics",
    "Epic poetry", "Homer", "Virgil", "Ovid", "Hesiod", "Plato",
    "Aristotle", "Herodotus", "Thucydides", "Plutarch", "Tacitus",
    "Julius Caesar", "Cicero", "Seneca", "Marcus Aurelius",
    "Confucius", "Taoism", "Mahabharata", "Ramayana",
    "Gilgamesh", "Beowulf",
]


async def stream_gutenberg(max_pages: int = 200_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover ancient/classical texts from Project Gutenberg via Gutendex API."""
    total = 0
    seen_ids: set[int] = set()
    async with httpx.AsyncClient(timeout=60.0) as client:
        for subject in GUTENBERG_ANCIENT_SUBJECTS:
            if total >= max_pages:
                break
            url: str | None = GUTENBERG_SEARCH_URL
            params: dict = {"topic": subject, "languages": "en", "mime_type": "text/plain"}
            page_num = 0
            while url and total < max_pages and page_num < 50:
                try:
                    resp = await client.get(url, params=params if page_num == 0 else None)
                    if resp.status_code != 200:
                        logger.warning("Gutenberg %d for %s", resp.status_code, subject)
                        break
                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break

                    batch: list[DiscoveredPage] = []
                    for book in results:
                        book_id = book.get("id")
                        if not book_id or book_id in seen_ids:
                            continue
                        seen_ids.add(book_id)

                        title = book.get("title", f"Gutenberg #{book_id}")
                        authors = ", ".join(
                            a.get("name", "") for a in book.get("authors", [])
                        )
                        if authors:
                            title = f"{title} — {authors}"

                        formats = book.get("formats", {})
                        text_url = (
                            formats.get("text/plain; charset=utf-8")
                            or formats.get("text/plain; charset=us-ascii")
                            or formats.get("text/plain")
                        )
                        if not text_url:
                            continue

                        batch.append(DiscoveredPage(
                            url=text_url,
                            external_id=f"gutenberg-{book_id}",
                            title=title[:300],
                            content_hint="classical_text",
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break

                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)

                    url = data.get("next")
                    params = {}
                    page_num += 1
                    await asyncio.sleep(0.5)
                except Exception as exc:
                    logger.error("Gutenberg discovery error for %s: %s", subject, exc)
                    break

            logger.info("Gutenberg subject '%s': %d total so far", subject, total)

    logger.info("Gutenberg discovery complete: %d books", total)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Perseus Digital Library — Greek/Latin texts with translations
# ---------------------------------------------------------------------------

PERSEUS_CATALOG_URL = "https://scaife-cts.perseus.org/api/cts"


async def stream_perseus(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover texts from the Perseus Digital Library via Scaife CTS API."""
    total = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.get(
                f"{PERSEUS_CATALOG_URL}?request=GetCapabilities",
                headers={"Accept": "application/xml"},
            )
            if resp.status_code != 200:
                logger.warning("Perseus CTS catalog returned %d", resp.status_code)
                yield DiscoveryBatch([], 0, 0, True)
                return

            xml = resp.text
            urns = re.findall(r'urn="([^"]+)"', xml)

            batch: list[DiscoveredPage] = []
            for urn in urns:
                if total >= max_pages:
                    break
                label_match = re.search(
                    rf'urn="{re.escape(urn)}"[^>]*>\s*<label[^>]*>([^<]+)',
                    xml, re.DOTALL,
                )
                label = label_match.group(1).strip() if label_match else urn.split(":")[-1]

                batch.append(DiscoveredPage(
                    url=f"{PERSEUS_CATALOG_URL}?request=GetPassage&urn={urn}",
                    external_id=f"perseus-{urn.replace(':', '-')}",
                    title=label[:300],
                    content_hint="classical_text",
                    depth=0,
                ))
                total += 1

                if len(batch) >= 500:
                    yield DiscoveryBatch(batch, 1, 0, False)
                    batch = []

            if batch:
                yield DiscoveryBatch(batch, 1, 0, False)
        except Exception as exc:
            logger.error("Perseus discovery error: %s", exc)

    logger.info("Perseus discovery complete: %d texts", total)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# British Museum — 4M+ objects via collection API
# ---------------------------------------------------------------------------

BM_SEARCH_URL = "https://www.britishmuseum.org/api/_search"

BM_ANCIENT_QUERIES = [
    "ancient egypt", "mesopotamia", "assyrian", "babylonian", "sumerian",
    "greek antiquities", "roman antiquities", "ancient near east",
    "cuneiform tablet", "egyptian mummy", "bronze age",
    "iron age", "minoan", "mycenaean", "etruscan",
    "phoenician", "persian empire", "hellenistic",
    "ancient china", "ancient india", "viking",
    "celtic", "anglo-saxon", "medieval manuscript",
]


async def stream_british_museum(max_pages: int = 200_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover objects from the British Museum collection API."""
    total = 0
    seen_ids: set[str] = set()
    async with httpx.AsyncClient(timeout=60.0) as client:
        for query in BM_ANCIENT_QUERIES:
            if total >= max_pages:
                break
            page_from = 0
            page_size = 100
            consecutive_empty = 0
            while total < max_pages and consecutive_empty < 3:
                try:
                    resp = await client.post(
                        BM_SEARCH_URL,
                        json={
                            "keyword": query,
                            "from": page_from,
                            "size": page_size,
                        },
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code != 200:
                        logger.warning("BM API %d for %s", resp.status_code, query)
                        break
                    data = resp.json()
                    hits = data.get("hits", {}).get("hits", [])
                    if not hits:
                        consecutive_empty += 1
                        break

                    consecutive_empty = 0
                    batch: list[DiscoveredPage] = []
                    for hit in hits:
                        src = hit.get("_source", {})
                        obj_id = hit.get("_id", "")
                        if not obj_id or obj_id in seen_ids:
                            continue
                        seen_ids.add(obj_id)

                        title = src.get("title", [{}])
                        if isinstance(title, list):
                            title = title[0].get("value", "") if title else ""
                        title = title or f"BM Object {obj_id}"

                        batch.append(DiscoveredPage(
                            url=f"https://www.britishmuseum.org/collection/object/{obj_id}",
                            external_id=f"bm-{obj_id}",
                            title=title[:300],
                            content_hint="museum_object",
                            depth=0,
                        ))
                        total += 1
                        if total >= max_pages:
                            break

                    if batch:
                        yield DiscoveryBatch(batch, 1, 0, False)

                    page_from += page_size
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    logger.error("BM discovery error for %s: %s", query, exc)
                    break

            logger.info("BM query '%s': %d total so far", query, total)

    logger.info("British Museum discovery complete: %d objects", total)
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Wikisource — full texts of public domain historical works
# ---------------------------------------------------------------------------

WIKISOURCE_API = "https://en.wikisource.org/w/api.php"

WIKISOURCE_SEED_CATEGORIES = [
    "Ancient_texts", "Classical_texts", "Egyptian_texts",
    "Mesopotamian_texts", "Buddhist_texts", "Hindu_texts",
    "Greek_texts", "Latin_texts", "Religious_texts",
    "Chinese_classics", "Confucian_texts", "Taoist_texts",
    "Jewish_texts", "Biblical_texts", "Zoroastrian_texts",
    "Vedic_texts", "Sanskrit_texts", "Ancient_history",
    "Ancient_Roman_texts", "Epic_poetry", "Mythological_texts",
    "Philosophical_texts", "Historical_texts",
]


async def stream_wikisource(max_pages: int = 200_000) -> AsyncIterator[DiscoveryBatch]:
    """Discover full-text historical works from Wikisource."""
    total = 0
    seen_titles: set[str] = set()
    seen_cats: set[str] = set()

    async with httpx.AsyncClient(timeout=60.0) as client:
        async def _spider_category(
            cat_name: str, depth: int, max_depth: int = 3,
        ) -> AsyncIterator[DiscoveryBatch]:
            nonlocal total
            if total >= max_pages or cat_name in seen_cats:
                return
            seen_cats.add(cat_name)

            cmcontinue: str | None = ""
            while cmcontinue is not None and total < max_pages:
                params: dict = {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": f"Category:{cat_name}",
                    "cmlimit": "500",
                    "cmtype": "page|subcat",
                    "format": "json",
                }
                if cmcontinue:
                    params["cmcontinue"] = cmcontinue

                try:
                    resp = await client.get(
                        WIKISOURCE_API, params=params,
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                except Exception:
                    break

                members = data.get("query", {}).get("categorymembers", [])
                batch: list[DiscoveredPage] = []
                subcats: list[str] = []

                for m in members:
                    ns = m.get("ns", 0)
                    page_title = m.get("title", "")

                    if ns == 14:
                        subcats.append(page_title.removeprefix("Category:"))
                    elif ns == 0 and page_title not in seen_titles:
                        seen_titles.add(page_title)
                        slug = page_title.replace(" ", "_")
                        batch.append(DiscoveredPage(
                            url=f"https://en.wikisource.org/wiki/{slug}",
                            external_id=f"ws-{slug[:200]}",
                            title=page_title[:300],
                            content_hint="historical_text",
                            depth=depth,
                        ))
                        total += 1
                        if total >= max_pages:
                            break

                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)

                cmcontinue = data.get("continue", {}).get("cmcontinue")
                await asyncio.sleep(0.3)

            if depth < max_depth:
                for sub in subcats:
                    if total >= max_pages:
                        break
                    async for sub_batch in _spider_category(sub, depth + 1, max_depth):
                        yield sub_batch

        for seed_cat in WIKISOURCE_SEED_CATEGORIES:
            if total >= max_pages:
                break
            async for batch in _spider_category(seed_cat, depth=0):
                yield batch
            logger.info("Wikisource: %d texts after cat '%s'", total, seed_cat)

    logger.info("Wikisource discovery complete: %d texts, %d categories", total, len(seen_cats))
    yield DiscoveryBatch([], 0, 0, True)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

API_ADAPTERS: dict[str, str] = {
    "cdli": "cdli",
    "met-museum": "met",
    "metmuseum": "met",
    "europeana": "europeana",
    "sefaria": "sefaria",
    "dss-bible": "dss",
    "ctext": "ctext",
    "suttacentral": "suttacentral",
    "oracc": "oracc",
    "loc": "loc",
    "internet-archive": "ia",
    "wikidata-artifacts": "wd-art",
    "bsb-mdz": "bsb",
    "gallica": "gallica",
    "pleiades": "pleiades",
    "open-context": "oc",
    "unesco-whc": "unesco",
    "wikidata-locations": "wd-loc",
    "openalex": "openalex",
    "core": "core",
    "tla-egyptian": "tla",
    "sacred-texts": "sacred-texts",
    "wikipedia-ancient": "wp-ancient",
    "gutenberg": "gutenberg",
    "perseus": "perseus",
    "british-museum": "bm",
    "wikisource": "wikisource",
}


def get_api_stream(slug: str, max_pages: int = 100_000, **kwargs) -> AsyncIterator[DiscoveryBatch] | None:
    """Return an async iterator for the given source slug, or None."""
    adapter = API_ADAPTERS.get(slug)
    if adapter == "cdli":
        return stream_cdli(max_pages=max_pages)
    if adapter == "met":
        return stream_met_museum(max_pages=max_pages)
    if adapter == "europeana":
        api_key = kwargs.get("europeana_api_key", "")
        return stream_europeana(api_key, max_pages=max_pages)
    if adapter == "sefaria":
        return stream_sefaria(max_pages=max_pages)
    if adapter == "dss":
        return stream_dss_bible(max_pages=max_pages)
    if adapter == "ctext":
        return stream_ctext(max_pages=max_pages)
    if adapter == "suttacentral":
        return stream_suttacentral(max_pages=max_pages)
    if adapter == "oracc":
        return stream_oracc(max_pages=max_pages)
    if adapter == "loc":
        return stream_loc(max_pages=max_pages)
    if adapter == "ia":
        return stream_internet_archive(max_pages=max_pages)
    if adapter == "wd-art":
        return stream_wikidata_artifacts(max_pages=max_pages)
    if adapter == "bsb":
        return stream_bsb_mdz(max_pages=max_pages)
    if adapter == "gallica":
        return stream_gallica(max_pages=max_pages)
    if adapter == "pleiades":
        return stream_pleiades(max_pages=max_pages)
    if adapter == "oc":
        return stream_open_context(max_pages=max_pages)
    if adapter == "unesco":
        return stream_unesco_whc(max_pages=max_pages)
    if adapter == "wd-loc":
        return stream_wikidata_locations(max_pages=max_pages)
    if adapter == "openalex":
        return stream_openalex(max_pages=max_pages)
    if adapter == "core":
        api_key = kwargs.get("core_api_key", "")
        return stream_core(api_key, max_pages=max_pages)
    if adapter == "tla":
        return stream_tla(max_pages=max_pages)
    if adapter == "sacred-texts":
        return stream_sacred_texts(max_pages=max_pages)
    if adapter == "wp-ancient":
        return stream_wikipedia_ancient(max_pages=max_pages)
    if adapter == "gutenberg":
        return stream_gutenberg(max_pages=max_pages)
    if adapter == "perseus":
        return stream_perseus(max_pages=max_pages)
    if adapter == "bm":
        return stream_british_museum(max_pages=max_pages)
    if adapter == "wikisource":
        return stream_wikisource(max_pages=max_pages)
    return None


async def discover_via_api(slug: str, max_pages: int = 100_000, **kwargs) -> CrawlResult | None:
    """Non-streaming fallback — collect all results into a CrawlResult."""
    stream = get_api_stream(slug, max_pages=max_pages, **kwargs)
    if stream is None:
        return None

    result = CrawlResult()
    async for batch in stream:
        result.pages.extend(batch.pages)
        result.pages_visited += batch.pages_visited
        result.errors += batch.errors
        if batch.done:
            break

    logger.info("%s discovery complete: %d objects", slug, len(result.pages))
    return result
