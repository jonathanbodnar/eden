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
# Dispatcher
# ---------------------------------------------------------------------------

API_ADAPTERS: dict[str, str] = {
    "cdli": "cdli",
    "met-museum": "met",
    "metmuseum": "met",
    "europeana": "europeana",
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
