"""Fetch worker: retrieves raw source material and stores it in R2."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.config import settings
from src.ingestion.models.discovered_record import DiscoveredRecord
from src.ingestion.models.enums import DiscoveredRecordStatus, IngestionMethod, JobType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.object_image import ObjectImage
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.services.api_fetch import api_fetch_url, parse_api_metadata
from src.ingestion.storage.r2_client import R2Client, r2_client
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)

IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_IMAGES_PER_PAGE = 30


def _extract_image_urls(html: str, page_url: str) -> list[dict]:
    """Extract image URLs and metadata from HTML content."""
    images = []
    seen_urls = set()

    for match in re.finditer(
        r'<img\s[^>]*?src=["\']([^"\']+)["\']([^>]*)>',
        html, re.IGNORECASE | re.DOTALL,
    ):
        src = match.group(1).strip()
        attrs = match.group(0)

        if src.startswith("data:"):
            continue

        absolute = urljoin(page_url, src)
        parsed = urlparse(absolute)

        if not parsed.scheme.startswith("http"):
            continue

        ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""

        # Skip tiny icons/spacers
        width_m = re.search(r'width=["\']?(\d+)', attrs, re.IGNORECASE)
        height_m = re.search(r'height=["\']?(\d+)', attrs, re.IGNORECASE)
        if width_m and int(width_m.group(1)) < 50:
            continue
        if height_m and int(height_m.group(1)) < 50:
            continue

        if absolute in seen_urls:
            continue
        seen_urls.add(absolute)

        alt_m = re.search(r'alt=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        alt_text = alt_m.group(1).strip() if alt_m else None

        images.append({
            "url": absolute,
            "alt_text": alt_text,
            "order": len(images),
        })

        if len(images) >= MAX_IMAGES_PER_PAGE:
            break

    return images


class FetchWorker(BaseWorker):
    job_types = [JobType.FETCH]

    def __init__(self, worker_id: str | None = None, storage: R2Client | None = None) -> None:
        super().__init__(worker_id)
        self.storage = storage or r2_client

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        from src.ingestion.queue.manager import is_upstream_done

        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source or not source.active:
            logger.warning("Source %s not active, skipping fetch", job.trusted_source_id)
            return

        records_processed = 0
        bytes_processed = 0
        if checkpoint:
            records_processed = checkpoint.records_processed
            bytes_processed = checkpoint.bytes_processed
            logger.info("Resuming fetch (%d already done)", records_processed)

        is_api_source = source.ingestion_method == IngestionMethod.API
        empty_polls = 0

        rate_limited_slugs = {"wikidata-locations", "pleiades", "tla-egyptian", "sacred-texts", "wikipedia-ancient"}
        if source.slug in rate_limited_slugs:
            concurrency = 3
            batch_size = 20
        elif is_api_source:
            concurrency = 10
            batch_size = 100
        else:
            concurrency = 3
            batch_size = 50
        sem = asyncio.Semaphore(concurrency)

        ssl_verify = source.slug not in ("pleiades", "oracc", "unesco-whc")
        async with httpx.AsyncClient(timeout=60.0, verify=ssl_verify) as client:
            while True:
                result = await session.execute(
                    select(DiscoveredRecord).where(
                        DiscoveredRecord.trusted_source_id == source.id,
                        DiscoveredRecord.status == DiscoveredRecordStatus.NEW,
                    ).order_by(DiscoveredRecord.external_id).limit(batch_size)
                )
                batch = result.scalars().all()

                if not batch:
                    upstream_done = await is_upstream_done(session, job.source_run_id, job.job_type)
                    if upstream_done:
                        empty_polls += 1
                        if empty_polls >= 2:
                            logger.info("Fetch %s: upstream done, no more records", source.slug)
                            break
                    await asyncio.sleep(5.0)
                    continue

                empty_polls = 0

                async def _prefetch(record: DiscoveredRecord) -> tuple[DiscoveredRecord, httpx.Response | None, str | None]:
                    """Do the HTTP request concurrently, return (record, response, error)."""
                    async with sem:
                        if source.slug in rate_limited_slugs:
                            await asyncio.sleep(0.5)
                        fetch_url = None
                        if is_api_source:
                            fetch_url = api_fetch_url(source.slug, record.external_id)
                        if not fetch_url:
                            fetch_url = record.record_url
                        if source.slug == "sacred-texts" and fetch_url:
                            clean = fetch_url.replace("http://", "https://").replace(":80/", "/")
                            fetch_url = f"https://web.archive.org/web/2id_/{clean}"
                        if not fetch_url or not fetch_url.startswith(("http://", "https://")):
                            return (record, None, f"Invalid URL: {fetch_url}")

                        for attempt in range(3):
                            try:
                                resp = await client.get(
                                    fetch_url, follow_redirects=True,
                                    headers={"Accept": "application/json", "User-Agent": "EdenBot/1.0"} if is_api_source else {},
                                )
                            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                                if attempt < 2:
                                    await asyncio.sleep(2 ** (attempt + 1))
                                    continue
                                return (record, None, f"{type(exc).__name__} after 3 attempts for {fetch_url}")
                            except Exception as exc:
                                return (record, None, f"Unexpected error: {type(exc).__name__}: {exc}")

                            if resp.status_code in (429, 503):
                                retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                                if attempt < 2:
                                    await asyncio.sleep(retry_after)
                                    continue
                                return (record, None, f"HTTP {resp.status_code} after 3 attempts")

                            if resp.status_code in (403, 404, 410):
                                if resp.status_code == 404 and source.slug == "suttacentral":
                                    uid = record.external_id.removeprefix("sc-")
                                    fallback = f"https://suttacentral.net/api/bilarasuttas/{uid}"
                                    try:
                                        resp2 = await client.get(
                                            fallback, follow_redirects=True,
                                            headers={"Accept": "application/json", "User-Agent": "EdenBot/1.0"},
                                        )
                                        if resp2.status_code == 200:
                                            return (record, resp2, None)
                                    except Exception:
                                        pass
                                return (record, None, f"HTTP {resp.status_code} for {fetch_url}")

                            return (record, resp, None)

                        return (record, None, "exhausted retries")

                prefetched = await asyncio.gather(*[_prefetch(r) for r in batch])

                batch_ok = 0
                batch_fail = 0
                for record, response, error in prefetched:
                    if error or response is None:
                        batch_fail += 1
                        logger.error("Failed to fetch %s: %s", record.external_id, error)
                        await session.execute(
                            update(DiscoveredRecord)
                            .where(DiscoveredRecord.id == record.id)
                            .values(status=DiscoveredRecordStatus.FAILED)
                        )
                        continue

                    try:
                        await self._store_response(session, client, source, record, response)
                        batch_ok += 1
                        await session.execute(
                            update(DiscoveredRecord)
                            .where(DiscoveredRecord.id == record.id)
                            .values(status=DiscoveredRecordStatus.FETCHED)
                        )
                    except Exception as exc:
                        batch_fail += 1
                        logger.error("Failed to store %s: %s", record.external_id, exc)
                        await session.execute(
                            update(DiscoveredRecord)
                            .where(DiscoveredRecord.id == record.id)
                            .values(status=DiscoveredRecordStatus.FAILED)
                        )

                records_processed += batch_ok
                await update_source_progress(session, source.id, fetched_count=records_processed)
                await session.commit()
                logger.info("Fetch %s: %d done (+%d ok, %d fail)", source.slug, records_processed, batch_ok, batch_fail)

        await update_source_progress(
            session, source.id, fetched_count=records_processed,
        )

    async def _store_response(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient,
        source: TrustedSource,
        record: DiscoveredRecord,
        response: httpx.Response,
    ) -> RawObject:
        """Parse response and store in DB + R2 (must run serially on session)."""
        is_api = source.ingestion_method == IngestionMethod.API
        data = response.content
        content_type = response.headers.get("content-type", "")
        fetch_url = str(response.url)

        if is_api and "json" in content_type.lower():
            api_json = response.json()
            if isinstance(api_json, list) and len(api_json) == 1:
                api_json = api_json[0]
            if source.slug == "wikipedia-ancient":
                api_json = await self._enrich_wiki_infobox(client, record.external_id, api_json)
            metadata = parse_api_metadata(source.slug, api_json)
        elif source.slug == "dss-bible" and "text/html" in content_type.lower():
            from src.ingestion.services.api_fetch import parse_dss_html
            metadata = parse_dss_html(data.decode("utf-8", errors="replace"), record.external_id)
        elif source.slug == "sacred-texts" and "text/html" in content_type.lower():
            from src.ingestion.services.api_fetch import parse_sacred_texts_html
            metadata = parse_sacred_texts_html(data.decode("utf-8", errors="replace"), record.external_id)
        else:
            metadata = {"headers": dict(response.headers)}

        existing = await session.execute(
            select(RawObject).where(
                RawObject.trusted_source_id == source.id,
                RawObject.external_id == record.external_id,
                RawObject.checksum == R2Client.compute_checksum(data),
            )
        )
        if existing.scalar_one_or_none():
            logger.info("Duplicate content for %s, skipping upload", record.external_id)
            return existing.scalar_one()

        r2_key, checksum = self.storage.upload_raw(
            source_slug=source.slug,
            external_id=record.external_id,
            data=data,
            content_type=content_type,
            metadata={
                "source_url": fetch_url,
                "external_id": record.external_id,
                "http_status": response.status_code,
            },
        )

        raw_obj = RawObject(
            trusted_source_id=source.id,
            discovered_record_id=record.id,
            external_id=record.external_id,
            source_url=record.record_url,
            content_type=content_type,
            checksum=checksum,
            byte_size=len(data),
            r2_key=r2_key,
            http_status=response.status_code,
            raw_metadata_jsonb=metadata,
            parser_hint=source.parser_type.value,
        )
        session.add(raw_obj)
        await session.flush()

        if is_api:
            image_urls = metadata.get("image_urls", [])
            if image_urls and source.slug == "wikipedia-ancient":
                image_urls = await self._resolve_wiki_images(client, image_urls)
            if image_urls:
                await self._store_api_images(session, client, source, raw_obj, image_urls)
        elif "text/html" in content_type.lower() and source.slug not in ("sacred-texts",):
            await self._extract_and_store_images(
                session, client, source, raw_obj, data.decode("utf-8", errors="replace"),
                record.record_url,
            )

        return raw_obj

    @staticmethod
    async def _enrich_wiki_infobox(
        client: httpx.AsyncClient,
        external_id: str,
        api_json: dict,
    ) -> dict:
        """Fetch wikitext to extract structured infobox fields for Wikipedia articles."""
        page_id = external_id.removeprefix("wp-")
        try:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "parse",
                    "pageid": page_id,
                    "prop": "wikitext",
                    "format": "json",
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                wikitext = resp.json().get("parse", {}).get("wikitext", {}).get("*", "")
                if wikitext:
                    api_json["_infobox_wikitext"] = wikitext
        except Exception:
            pass
        return api_json

    @staticmethod
    async def _resolve_wiki_images(
        client: httpx.AsyncClient,
        raw_urls: list[str],
    ) -> list[str]:
        """Resolve Wikipedia File: titles to actual image URLs via imageinfo API."""
        resolved: list[str] = []
        file_titles = [u for u in raw_urls if u.startswith("File:")]
        direct_urls = [u for u in raw_urls if u.startswith("http")]
        resolved.extend(direct_urls)

        for batch_start in range(0, len(file_titles), 10):
            batch = file_titles[batch_start:batch_start + 10]
            titles = "|".join(batch)
            try:
                resp = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": titles,
                        "prop": "imageinfo",
                        "iiprop": "url|mime",
                        "iiurlwidth": 1200,
                        "format": "json",
                    },
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    continue
                pages = resp.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    infos = page.get("imageinfo", [])
                    if not infos:
                        continue
                    info = infos[0]
                    mime = info.get("mime", "")
                    if not mime.startswith("image/"):
                        continue
                    thumb = info.get("thumburl") or info.get("url", "")
                    if thumb:
                        resolved.append(thumb)
            except Exception:
                continue
            await asyncio.sleep(0.2)
        return resolved

    async def _store_api_images(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient,
        source: TrustedSource,
        raw_obj: RawObject,
        image_urls: list[str],
    ) -> int:
        """Download images and store in R2 for LLM training."""
        stored = 0
        seen = set()
        for i, url in enumerate(image_urls[:MAX_IMAGES_PER_PAGE]):
            if url in seen or not url.startswith("http"):
                continue
            seen.add(url)
            try:
                resp = await client.get(url, follow_redirects=True, timeout=30.0)
                if resp.status_code != 200:
                    logger.debug("Image HTTP %d: %s", resp.status_code, url)
                    continue
                img_data = resp.content
                if len(img_data) < 500:
                    continue
                if len(img_data) > MAX_IMAGE_SIZE:
                    logger.debug("Image too large (%d bytes): %s", len(img_data), url)
                    continue

                ct = resp.headers.get("content-type", "image/jpeg")
                r2_key, checksum = self.storage.upload_image(
                    source_slug=source.slug,
                    external_id=raw_obj.external_id,
                    image_index=stored,
                    data=img_data,
                    content_type=ct,
                )

                img = ObjectImage(
                    raw_object_id=raw_obj.id,
                    trusted_source_id=source.id,
                    image_url=url,
                    r2_key=r2_key,
                    content_type=ct,
                    byte_size=len(img_data),
                    image_order=stored,
                )
                session.add(img)
                stored += 1
                await asyncio.sleep(0.1)
            except Exception as exc:
                logger.debug("Failed to download image %s: %s", url, exc)

        if stored:
            await session.flush()
            logger.info("Downloaded %d images to R2 for %s", stored, raw_obj.external_id)
        return stored

    async def _extract_and_store_images(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient,
        source: TrustedSource,
        raw_obj: RawObject,
        html: str,
        page_url: str,
    ) -> int:
        """Extract images from HTML page, store URLs (and optionally fetch to R2)."""
        image_infos = _extract_image_urls(html, page_url)
        if not image_infos:
            return 0

        stored = 0
        for info in image_infos:
            try:
                img = ObjectImage(
                    raw_object_id=raw_obj.id,
                    trusted_source_id=source.id,
                    image_url=info["url"],
                    alt_text=info.get("alt_text"),
                    image_order=info["order"],
                )

                try:
                    head_resp = await client.head(
                        info["url"], follow_redirects=True, timeout=10.0,
                    )
                    if head_resp.status_code == 200:
                        img.content_type = head_resp.headers.get("content-type")
                        cl = head_resp.headers.get("content-length")
                        if cl and cl.isdigit():
                            img.byte_size = int(cl)
                except Exception:
                    pass

                session.add(img)
                stored += 1
            except Exception as exc:
                logger.debug("Failed to record image %s: %s", info["url"], exc)

        if stored:
            await session.flush()
            logger.info("Stored %d image references for %s", stored, raw_obj.external_id)

        return stored
