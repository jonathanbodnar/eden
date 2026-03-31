"""Fetch worker: retrieves raw source material and stores it in R2."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.config import settings
from src.ingestion.models.discovered_record import DiscoveredRecord
from src.ingestion.models.enums import DiscoveredRecordStatus, JobType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.storage.r2_client import R2Client, r2_client
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)


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
        await session.commit()

    async def _fetch_record(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient,
        source: TrustedSource,
        record: DiscoveredRecord,
    ) -> RawObject:
        if not record.record_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {record.record_url}")

        from urllib.parse import urlparse
        parsed = urlparse(record.record_url)
        if source.domain and parsed.netloc and source.domain not in parsed.netloc:
            raise ValueError(
                f"URL domain {parsed.netloc} not in approved domain {source.domain}"
            )

        response = await client.get(record.record_url)
        response.raise_for_status()
        data = response.content
        content_type = response.headers.get("content-type", "")

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
                "source_url": record.record_url,
                "external_id": record.external_id,
                "http_status": response.status_code,
                "headers": dict(response.headers),
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
            raw_metadata_jsonb={"headers": dict(response.headers)},
            parser_hint=source.parser_type.value,
        )
        session.add(raw_obj)
        await session.flush()
        return raw_obj
