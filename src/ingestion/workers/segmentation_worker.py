"""Segmentation worker: breaks source versions into retrieval-friendly segments."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models.enums import JobType, ReviewStatus, SegmentType, VersionType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.segment import Segment
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)

VERSION_TYPE_SEGMENT_MAP = {
    VersionType.ORIGINAL: SegmentType.SECTION,
    VersionType.TRANSLITERATION: SegmentType.LINE_RANGE,
    VersionType.TRANSLATION: SegmentType.PARAGRAPH,
    VersionType.OCR: SegmentType.PARAGRAPH,
    VersionType.MUSEUM_DESCRIPTION: SegmentType.DESCRIPTION_BLOCK,
    VersionType.EDITION: SegmentType.SECTION,
}

MAX_SEGMENT_CHARS = 2000
MIN_SEGMENT_CHARS = 100


class SegmentationWorker(BaseWorker):
    job_types = [JobType.SEGMENT]

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        from src.ingestion.queue.manager import is_upstream_done
        import asyncio

        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source:
            return

        records_processed = 0
        segments_created = 0
        empty_polls = 0

        while True:
            result = await session.execute(
                select(SourceVersion)
                .join(SourceRecord, SourceVersion.source_record_id == SourceRecord.id)
                .where(SourceRecord.trusted_source_id == source.id)
                .where(~SourceVersion.id.in_(
                    select(Segment.source_version_id).distinct()
                ))
                .where(SourceVersion.text_extracted.isnot(None))
                .where(SourceVersion.text_extracted != "")
                .order_by(SourceVersion.created_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
            batch = result.scalars().all()

            if not batch:
                upstream_done = await is_upstream_done(session, job.source_run_id, job.job_type)
                if upstream_done:
                    empty_polls += 1
                    if empty_polls >= 2:
                        logger.info("Segment %s: upstream done, no more records", source.slug)
                        break
                await asyncio.sleep(5.0)
                continue

            empty_polls = 0
            for version in batch:
                try:
                    count = await self._segment_version(session, version)
                    segments_created += count
                    records_processed += 1
                except Exception as exc:
                    logger.error("Failed to segment version %s: %s", version.id, exc)

            await update_source_progress(session, source.id, segmented_count=records_processed)
            await session.commit()
            logger.info("Segment %s: %d versions, %d segments (committed)", source.slug, records_processed, segments_created)

        await update_source_progress(session, source.id, segmented_count=records_processed)

    @staticmethod
    def _raw_object_alias():
        from src.ingestion.models.raw_object import RawObject
        return RawObject.__table__

    async def _segment_version(
        self,
        session: AsyncSession,
        version: SourceVersion,
    ) -> int:
        text = version.text_extracted or ""
        if not text.strip():
            return 0

        segment_type = VERSION_TYPE_SEGMENT_MAP.get(version.version_type, SegmentType.PARAGRAPH)
        chunks = self._split_text(text)
        count = 0

        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue

            normalized = self._normalize_text(chunk)

            segment = Segment(
                source_version_id=version.id,
                segment_type=segment_type,
                segment_order=i + 1,
                citation_ref=f"{version.id}:seg:{i + 1}",
                original_text=chunk,
                normalized_text=normalized,
                review_status=ReviewStatus.PENDING,
            )
            session.add(segment)
            count += 1

        await session.flush()
        return count

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """Split text into segments respecting paragraph boundaries."""
        paragraphs = re.split(r"\n\s*\n", text)

        segments = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current) + len(para) > MAX_SEGMENT_CHARS and current:
                segments.append(current.strip())
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para

        if current.strip():
            segments.append(current.strip())

        final_segments = []
        for seg in segments:
            if len(seg) > MAX_SEGMENT_CHARS:
                sentences = re.split(r"(?<=[.!?])\s+", seg)
                chunk = ""
                for sent in sentences:
                    if len(chunk) + len(sent) > MAX_SEGMENT_CHARS and chunk:
                        final_segments.append(chunk.strip())
                        chunk = sent
                    else:
                        chunk = f"{chunk} {sent}" if chunk else sent
                if chunk.strip():
                    final_segments.append(chunk.strip())
            else:
                final_segments.append(seg)

        return final_segments

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        normalized = normalized.lower()
        return normalized
