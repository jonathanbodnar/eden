"""API-based discovery adapters for sources with public REST APIs.

Each adapter is an async generator that yields batches of DiscoveredPage
entries, allowing the discovery worker to stream results to the DB
instead of buffering everything in memory.
"""

from __future__ import annotations

import asyncio
import logging
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

SEFARIA_CATEGORIES = ["Tanakh", "Mishnah", "Talmud", "Midrash", "Halakhah"]

async def stream_sefaria(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(
                "https://www.sefaria.org/api/index/",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                yield DiscoveryBatch([], 1, 1, True); return
            index = resp.json()
        except Exception as exc:
            logger.error("Sefaria index error: %s", exc)
            yield DiscoveryBatch([], 1, 1, True); return

        def _extract_titles(node, depth=0):
            titles = []
            if isinstance(node, dict):
                if "title" in node and "category" not in node:
                    titles.append(node["title"])
                for child in node.get("contents", []):
                    titles.extend(_extract_titles(child, depth + 1))
            elif isinstance(node, list):
                for item in node:
                    titles.extend(_extract_titles(item, depth + 1))
            return titles

        all_titles = []
        for cat in index:
            if isinstance(cat, dict) and cat.get("category") in SEFARIA_CATEGORIES:
                all_titles.extend(_extract_titles(cat))

        batch: list[DiscoveredPage] = []
        for title in all_titles:
            if total >= max_pages:
                break
            batch.append(DiscoveredPage(
                url=f"https://www.sefaria.org/{title.replace(' ', '_')}",
                external_id=f"sefaria-{title}",
                title=title[:300],
                content_hint="jewish_text",
                depth=0,
            ))
            total += 1
            if len(batch) >= 500:
                yield DiscoveryBatch(batch, 1, 0, False)
                batch = []
                await asyncio.sleep(0.1)

        if batch:
            yield DiscoveryBatch(batch, 1, 0, False)

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

    async def _get_subsections(client, text_id, depth=0):
        """Recursively get all leaf-level subsections."""
        if depth > 3:
            return [text_id]
        try:
            resp = await client.get(
                f"https://api.ctext.org/gettextinfo?urn=ctp:{text_id}",
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return [text_id]
            info = resp.json()
            subs = info.get("subsections", [])
            if not subs:
                return [text_id]
            all_leaves = []
            for sub in subs:
                sub_name = sub if isinstance(sub, str) else ""
                if not sub_name:
                    continue
                full_path = f"{text_id}/{sub_name}"
                child_subs = await _get_subsections(client, full_path, depth + 1)
                all_leaves.extend(child_subs)
                await asyncio.sleep(0.5)
            return all_leaves if all_leaves else [text_id]
        except Exception:
            return [text_id]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for text_id in CTEXT_PRE_QIN:
            if total >= max_pages:
                break
            try:
                leaves = await _get_subsections(client, text_id)
                batch: list[DiscoveredPage] = []
                for leaf in leaves:
                    batch.append(DiscoveredPage(
                        url=f"https://ctext.org/{leaf}",
                        external_id=f"ctext-{leaf.replace('/', '-')}",
                        title=leaf[:300],
                        content_hint="chinese_classic",
                        depth=0,
                    ))
                    total += 1
                    if total >= max_pages:
                        break
                if batch:
                    yield DiscoveryBatch(batch, 1, 0, False)
                    logger.info("CText %s: %d chapters found (total: %d)", text_id, len(batch), total)
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
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, verify=False) as client:
        try:
            resp = await client.get("http://oracc.org/projects.json", headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                yield DiscoveryBatch([], 1, 1, True); return
            projects = resp.json()
            project_list = projects.get("projects", {}).keys() if isinstance(projects.get("projects"), dict) else []
        except Exception as exc:
            logger.error("ORACC projects error: %s", exc)
            yield DiscoveryBatch([], 1, 1, True); return

        for proj in project_list:
            if total >= max_pages:
                break
            try:
                cat_resp = await client.get(
                    f"http://oracc.org/{proj}/catalogue.json",
                    headers={"User-Agent": USER_AGENT},
                )
                if cat_resp.status_code != 200:
                    continue
                cat = cat_resp.json()
                members = cat.get("members", {})

                batch: list[DiscoveredPage] = []
                for text_id, text_info in members.items():
                    designation = text_info.get("designation", text_id) if isinstance(text_info, dict) else text_id
                    batch.append(DiscoveredPage(
                        url=f"http://oracc.org/{proj}/{text_id}",
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
                await asyncio.sleep(0.5)
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
    "cunéiforme", "mésopotamie tablette", "papyrus égyptien",
    "manuscrit ancien", "hiéroglyphe", "sumérien",
    "babylonien", "assyrien", "qumran", "mer morte",
]

async def stream_gallica(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        for query in GALLICA_QUERIES:
            if total >= max_pages:
                break
            start = 1
            while total < max_pages:
                try:
                    resp = await client.get(
                        "https://gallica.bnf.fr/SRU",
                        params={
                            "version": "1.2", "operation": "searchRetrieve",
                            "query": f'dc.subject all "{query}"',
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

WD_LOCATION_QUERY = """
SELECT ?item ?itemLabel ?coord WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q839954 .
  ?item wdt:P625 ?coord .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT {limit} OFFSET {offset}
"""

async def stream_wikidata_locations(max_pages: int = 100_000) -> AsyncIterator[DiscoveryBatch]:
    total = 0
    offset = 0
    limit = 500
    async with httpx.AsyncClient(timeout=90.0) as client:
        while total < max_pages:
            try:
                query = WD_LOCATION_QUERY.format(limit=limit, offset=offset)
                resp = await client.get(
                    WIKIDATA_SPARQL,
                    params={"query": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                )
                if resp.status_code != 200:
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
                await asyncio.sleep(2.0)
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
