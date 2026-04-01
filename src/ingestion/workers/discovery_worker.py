"""Discovery worker: crawls trusted sources to find content pages."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models.discovered_record import DiscoveredRecord
from src.ingestion.models.enums import DiscoveredRecordStatus, IngestionMethod, JobType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.services.discovery import discover_source
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

        logger.info(
            "Starting discovery for %s (%s via %s)",
            source.slug, source.domain, source.ingestion_method.value,
        )

        if source.ingestion_method == IngestionMethod.API:
            await self._discover_via_stream(session, job, source)
        else:
            await self._discover_via_crawl(session, job, source)

    async def _discover_via_stream(
        self,
        session: AsyncSession,
        job: QueuedJob,
        source: TrustedSource,
    ) -> None:
        """Stream API discovery — inserts records to DB as batches arrive."""
        from src.ingestion.services.api_discovery import get_api_stream

        stream = get_api_stream(source.slug, max_pages=500_000)
        if stream is None:
            logger.warning("No API adapter for %s, falling back to crawl", source.slug)
            await self._discover_via_crawl(session, job, source)
            return

        new_count = 0
        skipped_count = 0
        pages_visited = 0
        errors = 0

        async for batch in stream:
            pages_visited += batch.pages_visited
            errors += batch.errors

            for page in batch.pages:
                existing = await session.execute(
                    select(DiscoveredRecord.id).where(
                        DiscoveredRecord.trusted_source_id == source.id,
                        DiscoveredRecord.external_id == page.external_id,
                    )
                )
                if existing.scalar_one_or_none():
                    skipped_count += 1
                    continue

                session.add(DiscoveredRecord(
                    trusted_source_id=source.id,
                    external_id=page.external_id,
                    record_url=page.url,
                    title_hint=page.title or None,
                    discovery_metadata_jsonb={
                        "depth": page.depth,
                        "content_hint": page.content_hint or None,
                    },
                    status=DiscoveredRecordStatus.NEW,
                ))
                new_count += 1

            await session.flush()

            if new_count % 1000 < 100:
                await update_source_progress(
                    session, source.id, discovered_count=new_count,
                )
                await session.commit()
                logger.info(
                    "Discovery streaming %s: %d new, %d skipped (committed)",
                    source.slug, new_count, skipped_count,
                )

            if batch.done:
                break

        await session.flush()
        await update_source_progress(session, source.id, discovered_count=new_count)

        logger.info(
            "Discovery complete for %s: %d new, %d skipped, %d API pages, %d errors",
            source.slug, new_count, skipped_count, pages_visited, errors,
        )

    async def _discover_via_crawl(
        self,
        session: AsyncSession,
        job: QueuedJob,
        source: TrustedSource,
    ) -> None:
        """Original HTML crawl discovery — buffers all results then inserts."""
        crawl_result = await discover_source(
            ingestion_method=source.ingestion_method,
            base_url=source.base_url,
            domain=source.domain,
            slug=source.slug,
        )

        new_count = 0
        skipped_count = 0

        for page in crawl_result.pages:
            existing = await session.execute(
                select(DiscoveredRecord.id).where(
                    DiscoveredRecord.trusted_source_id == source.id,
                    DiscoveredRecord.external_id == page.external_id,
                )
            )
            if existing.scalar_one_or_none():
                skipped_count += 1
                continue

            session.add(DiscoveredRecord(
                trusted_source_id=source.id,
                external_id=page.external_id,
                record_url=page.url,
                title_hint=page.title or None,
                discovery_metadata_jsonb={
                    "depth": page.depth,
                    "content_hint": page.content_hint or None,
                },
                status=DiscoveredRecordStatus.NEW,
            ))
            new_count += 1

            if new_count % 50 == 0:
                await session.flush()
                await self.maybe_checkpoint(
                    session, job,
                    checkpoint_type="discovery",
                    records_processed=new_count + skipped_count,
                    records_total_estimate=len(crawl_result.pages),
                    stage_percent=((new_count + skipped_count) / len(crawl_result.pages) * 100) if crawl_result.pages else None,
                )

        await session.flush()
        await update_source_progress(session, source.id, discovered_count=new_count)

        logger.info(
            "Discovery complete for %s: %d new, %d skipped, %d pages crawled",
            source.slug, new_count, skipped_count, crawl_result.pages_visited,
        )
