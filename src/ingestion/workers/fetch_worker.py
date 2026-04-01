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
        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source or not source.active:
            logger.warning("Source %s not active, skipping fetch", job.trusted_source_id)
            return

        last_external_id = None
        records_processed = 0
        bytes_processed = 0
        if checkpoint:
            last_external_id = checkpoint.external_id_last_processed
            records_processed = checkpoint.records_processed
            bytes_processed = checkpoint.bytes_processed
            logger.info("Resuming fetch from %s (%d done)", last_external_id, records_processed)

        query = select(DiscoveredRecord).where(
            DiscoveredRecord.trusted_source_id == source.id,
            DiscoveredRecord.status == DiscoveredRecordStatus.NEW,
        ).order_by(DiscoveredRecord.external_id)

        if last_external_id:
            query = query.where(DiscoveredRecord.external_id > last_external_id)

        result = await session.execute(query)
        records = result.scalars().all()

        total = len(records) + records_processed
        logger.info("Fetching %d records for %s", len(records), source.slug)

        async with httpx.AsyncClient(timeout=60.0) as client:
            for record in records:
                try:
                    await self._fetch_record(session, client, source, record)
                    records_processed += 1
                    bytes_downloaded = 0

                    await session.execute(
                        update(DiscoveredRecord)
                        .where(DiscoveredRecord.id == record.id)
                        .values(status=DiscoveredRecordStatus.FETCHED)
                    )

                except Exception as exc:
                    logger.error("Failed to fetch %s: %s", record.external_id, exc)
                    await session.execute(
                        update(DiscoveredRecord)
                        .where(DiscoveredRecord.id == record.id)
                        .values(status=DiscoveredRecordStatus.FAILED)
                    )

                await self.maybe_checkpoint(
                    session, job,
                    checkpoint_type="fetch",
                    external_id_last_processed=record.external_id,
                    records_processed=records_processed,
                    records_total_estimate=total,
                    bytes_processed=bytes_processed,
                    stage_percent=(records_processed / total * 100) if total else None,
                )

                delay = settings.default_fetch_delay_seconds
                if source.rate_limit_rpm:
                    delay = max(delay, 60.0 / source.rate_limit_rpm)
                await asyncio.sleep(delay)

        await self.maybe_checkpoint(
            session, job,
            checkpoint_type="fetch",
            records_processed=records_processed,
            records_total_estimate=total,
            bytes_processed=bytes_processed,
            stage_percent=100.0,
            force=True,
        )

        await update_source_progress(
            session, source.id,
            fetched_count=records_processed,
            total_bytes_stored=bytes_processed,
        )

    async def _fetch_record(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient,
        source: TrustedSource,
        record: DiscoveredRecord,
    ) -> RawObject:
        is_api = source.ingestion_method == IngestionMethod.API
        fetch_url = None

        if is_api:
            fetch_url = api_fetch_url(source.slug, record.external_id)

        if not fetch_url:
            fetch_url = record.record_url

        if not fetch_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {fetch_url}")

        response = await client.get(
            fetch_url,
            follow_redirects=True,
            headers={"Accept": "application/json"} if is_api else {},
        )
        response.raise_for_status()
        data = response.content
        content_type = response.headers.get("content-type", "")

        if is_api and "json" in content_type.lower():
            api_json = response.json()
            if isinstance(api_json, list) and len(api_json) == 1:
                api_json = api_json[0]
            metadata = parse_api_metadata(source.slug, api_json)
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
            if image_urls:
                await self._store_api_images(session, source, raw_obj, image_urls)
        elif "text/html" in content_type.lower():
            await self._extract_and_store_images(
                session, client, source, raw_obj, data.decode("utf-8", errors="replace"),
                record.record_url,
            )

        return raw_obj

    async def _store_api_images(
        self,
        session: AsyncSession,
        source: TrustedSource,
        raw_obj: RawObject,
        image_urls: list[str],
    ) -> int:
        """Store image references from API metadata."""
        stored = 0
        for i, url in enumerate(image_urls[:MAX_IMAGES_PER_PAGE]):
            try:
                img = ObjectImage(
                    raw_object_id=raw_obj.id,
                    trusted_source_id=source.id,
                    image_url=url,
                    image_order=i,
                )
                session.add(img)
                stored += 1
            except Exception as exc:
                logger.debug("Failed to record API image %s: %s", url, exc)

        if stored:
            await session.flush()
            logger.info("Stored %d API image refs for %s", stored, raw_obj.external_id)
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
