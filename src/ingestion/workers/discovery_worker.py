"""Discovery worker: identifies source records from trusted sources."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models.discovered_record import DiscoveredRecord
from src.ingestion.models.enums import DiscoveredRecordStatus, JobType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class DiscoveryWorker(BaseWorker):
    job_types = [JobType.DISCOVER]

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source or not source.active:
            logger.warning("Source %s is not active, skipping discovery", job.trusted_source_id)
            return

        start_cursor = None
        records_processed = 0
        if checkpoint:
            start_cursor = checkpoint.cursor_value
            records_processed = checkpoint.records_processed
            logger.info("Resuming discovery from cursor %s (%d already processed)", start_cursor, records_processed)

        discovered_count = await self._discover_from_source(
            session, source, job, start_cursor, records_processed
        )

        await update_source_progress(
            session, source.id, discovered_count=discovered_count
        )
        await session.commit()
        logger.info("Discovery complete for %s: %d records", source.slug, discovered_count)

    async def _discover_from_source(
        self,
        session: AsyncSession,
        source: TrustedSource,
        job: QueuedJob,
        start_cursor: str | None,
        records_already_processed: int,
    ) -> int:
        """Source-specific discovery logic.

        This is a template implementation. Real discovery would use
        the source's ingestion_method to fetch listings from APIs,
        sitemaps, feeds, etc.
        """
        records_processed = records_already_processed

        payload = job.payload_jsonb or {}
        external_records = payload.get("records", [])

        for record in external_records:
            ext_id = record.get("external_id", "")
            if start_cursor and ext_id <= start_cursor:
                continue

            existing = await session.execute(
                select(DiscoveredRecord).where(
                    DiscoveredRecord.trusted_source_id == source.id,
                    DiscoveredRecord.external_id == ext_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            discovered = DiscoveredRecord(
                trusted_source_id=source.id,
                external_id=ext_id,
                record_url=record.get("url", ""),
                title_hint=record.get("title"),
                discovery_metadata_jsonb=record.get("metadata"),
                status=DiscoveredRecordStatus.NEW,
            )
            session.add(discovered)
            records_processed += 1

            await self.maybe_checkpoint(
                session,
                job,
                checkpoint_type="discovery",
                cursor_value=ext_id,
                records_processed=records_processed,
                records_total_estimate=len(external_records),
                stage_percent=(records_processed / len(external_records) * 100) if external_records else None,
            )

        await self.maybe_checkpoint(
            session, job,
            checkpoint_type="discovery",
            records_processed=records_processed,
            records_total_estimate=len(external_records),
            stage_percent=100.0,
            force=True,
        )

        return records_processed
