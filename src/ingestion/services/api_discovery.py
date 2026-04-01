"""API-based discovery adapters for sources with public REST APIs.

Each adapter yields DiscoveredPage entries, fitting into the same pipeline
as the HTML crawler but pulling artifact lists from structured APIs.

Discovery only gathers IDs/URLs. Full details are fetched in the fetch phase.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import httpx

from src.ingestion.services.discovery import CrawlResult, DiscoveredPage

logger = logging.getLogger(__name__)

TIMEOUT = 30.0
USER_AGENT = "EdenBot/1.0 (research ingestion platform)"


# ---------------------------------------------------------------------------
# CDLI  —  Cuneiform Digital Library Initiative
# ---------------------------------------------------------------------------

async def discover_cdli(max_pages: int = 50_000) -> CrawlResult:
    """Paginate through GET /artifacts.json to list all artifact IDs."""
    result = CrawlResult()
    page = 1
    per_page = 100

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while len(result.pages) < max_pages:
            url = f"https://cdli.earth/artifacts.json?page={page}&per_page={per_page}"
            try:
                resp = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                result.pages_visited += 1

                if resp.status_code != 200:
                    logger.warning("CDLI API returned %d on page %d", resp.status_code, page)
                    result.errors += 1
                    break

                artifacts = resp.json()
                if isinstance(artifacts, dict):
                    artifacts = artifacts.get("data", artifacts.get("artifacts", []))
                if not isinstance(artifacts, list) or not artifacts:
                    break

                for art in artifacts:
                    art_id = art.get("id") or art.get("artifact_id")
                    if not art_id:
                        continue

                    title = art.get("designation", f"CDLI P{art_id:06d}" if isinstance(art_id, int) else f"CDLI {art_id}")

                    result.pages.append(DiscoveredPage(
                        url=f"https://cdli.earth/artifacts/{art_id}",
                        external_id=f"cdli-{art_id}",
                        title=str(title)[:300],
                        content_hint="cuneiform artifact",
                        depth=0,
                    ))
                    if len(result.pages) >= max_pages:
                        break

                logger.info(
                    "CDLI page %d: %d artifacts (running total: %d)",
                    page, len(artifacts), len(result.pages),
                )
                page += 1

                if len(artifacts) < per_page:
                    break

                await asyncio.sleep(0.5)

            except Exception as exc:
                logger.error("CDLI API error on page %d: %s", page, exc)
                result.errors += 1
                break

    logger.info("CDLI discovery complete: %d artifacts", len(result.pages))
    return result


# ---------------------------------------------------------------------------
# Met Museum  —  The Metropolitan Museum of Art Collection API
# ---------------------------------------------------------------------------

MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"

MET_DEPARTMENTS = [
    (3, "Ancient Near Eastern Art"),
    (10, "Egyptian Art"),
    (13, "Greek and Roman Art"),
]


async def discover_met_museum(max_pages: int = 50_000) -> CrawlResult:
    """Search endpoint returns object IDs filtered to pre-BC departments."""
    result = CrawlResult()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for dept_id, dept_name in MET_DEPARTMENTS:
            if len(result.pages) >= max_pages:
                break
            try:
                search_url = (
                    f"{MET_BASE}/search?"
                    f"departmentId={dept_id}"
                    f"&dateBegin=-10000&dateEnd=0"
                    f"&hasImages=true&q=*"
                )
                resp = await client.get(search_url, headers={"User-Agent": USER_AGENT})
                result.pages_visited += 1

                if resp.status_code != 200:
                    logger.warning("Met search returned %d for dept %d", resp.status_code, dept_id)
                    result.errors += 1
                    continue

                data = resp.json()
                object_ids = data.get("objectIDs") or []
                total = data.get("total", 0)
                logger.info(
                    "Met dept %d (%s): %d pre-BC objects with images",
                    dept_id, dept_name, total,
                )

                remaining = max_pages - len(result.pages)
                for oid in object_ids[:remaining]:
                    result.pages.append(DiscoveredPage(
                        url=f"https://www.metmuseum.org/art/collection/search/{oid}",
                        external_id=f"met-{oid}",
                        title=f"Met Object {oid} ({dept_name})",
                        content_hint=dept_name,
                        depth=0,
                    ))

            except Exception as exc:
                logger.error("Met API error for dept %d: %s", dept_id, exc)
                result.errors += 1

    logger.info("Met Museum discovery complete: %d objects", len(result.pages))
    return result


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


async def discover_europeana(api_key: str, max_pages: int = 50_000) -> CrawlResult:
    """Cursor-based pagination over Europeana Search API."""
    result = CrawlResult()
    if not api_key:
        logger.warning("No Europeana API key configured — skipping")
        return result

    base = "https://api.europeana.eu/record/v2/search.json"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for query in EUROPEANA_QUERIES:
            if len(result.pages) >= max_pages:
                break

            cursor = "*"
            while len(result.pages) < max_pages and cursor:
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
                    result.pages_visited += 1

                    if resp.status_code != 200:
                        logger.warning("Europeana returned %d for '%s'", resp.status_code, query)
                        result.errors += 1
                        break

                    data = resp.json()
                    items = data.get("items", [])
                    cursor = data.get("nextCursor")

                    if not items:
                        break

                    for item in items:
                        item_id = item.get("id", "")
                        titles = item.get("title", [])
                        title = titles[0] if titles else f"Europeana {item_id}"
                        page_url = item.get("guid") or f"https://www.europeana.eu/item{item_id}"

                        result.pages.append(DiscoveredPage(
                            url=page_url,
                            external_id=f"europeana-{item_id.lstrip('/').replace('/', '-')}",
                            title=str(title)[:300],
                            content_hint=query,
                            depth=0,
                        ))

                    logger.info(
                        "Europeana '%s': %d items (running total: %d)",
                        query, len(items), len(result.pages),
                    )
                    await asyncio.sleep(0.5)

                    if not cursor or len(items) < 100:
                        break

                except Exception as exc:
                    logger.error("Europeana error for '%s': %s", query, exc)
                    result.errors += 1
                    break

    logger.info("Europeana discovery complete: %d objects", len(result.pages))
    return result


# ---------------------------------------------------------------------------
# Dispatcher  —  called from discover_source
# ---------------------------------------------------------------------------

API_ADAPTERS: dict[str, str] = {
    "cdli": "cdli",
    "met-museum": "met",
    "metmuseum": "met",
    "europeana": "europeana",
}


async def discover_via_api(slug: str, max_pages: int = 50_000, **kwargs) -> CrawlResult | None:
    """Route to the correct API adapter by source slug.

    Returns None if no adapter is registered for this slug.
    """
    adapter = API_ADAPTERS.get(slug)

    if adapter == "cdli":
        return await discover_cdli(max_pages=max_pages)
    if adapter == "met":
        return await discover_met_museum(max_pages=max_pages)
    if adapter == "europeana":
        api_key = kwargs.get("europeana_api_key", "")
        return await discover_europeana(api_key, max_pages=max_pages)

    return None
