"""Normalization worker: converts raw objects into canonical source records."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models.enums import (
    CopyrightStatus,
    DatingConfidence,
    DateType,
    JobType,
    ProvenanceStatus,
    RecordStatus,
    SourceCategory,
    VersionType,
)
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.source_date import SourceDate
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class NormalizationWorker(BaseWorker):
    job_types = [JobType.NORMALIZE]

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source:
            return

        last_raw_id = None
        records_processed = 0
        if checkpoint:
            last_raw_id = checkpoint.external_id_last_processed
            records_processed = checkpoint.records_processed

        query = (
            select(RawObject)
            .where(RawObject.trusted_source_id == source.id)
            .order_by(RawObject.fetched_at)
        )

        result = await session.execute(query)
        raw_objects = result.scalars().all()

        skip = True if last_raw_id else False
        total = len(raw_objects)

        for raw_obj in raw_objects:
            if skip:
                if str(raw_obj.id) == last_raw_id:
                    skip = False
                continue

            existing = await session.execute(
                select(SourceRecord).where(SourceRecord.raw_object_id == raw_obj.id)
            )
            if existing.scalar_one_or_none():
                records_processed += 1
                continue

            try:
                await self._normalize_raw_object(session, source, raw_obj)
                records_processed += 1
            except Exception as exc:
                logger.error("Failed to normalize raw object %s: %s", raw_obj.id, exc)

            if records_processed % 50 == 0:
                await update_source_progress(
                    session, source.id, normalized_count=records_processed,
                )
                await session.commit()
                logger.info("Normalize %s: %d/%d done (committed)", source.slug, records_processed, total)

            await self.maybe_checkpoint(
                session, job,
                checkpoint_type="normalize",
                external_id_last_processed=str(raw_obj.id),
                records_processed=records_processed,
                records_total_estimate=total,
                stage_percent=(records_processed / total * 100) if total else None,
            )

        await self.maybe_checkpoint(
            session, job,
            checkpoint_type="normalize",
            records_processed=records_processed,
            records_total_estimate=total,
            stage_percent=100.0,
            force=True,
        )

        await update_source_progress(
            session, source.id, normalized_count=records_processed
        )

    async def _normalize_raw_object(
        self,
        session: AsyncSession,
        source: TrustedSource,
        raw_obj: RawObject,
    ) -> SourceRecord:
        """Parse raw object metadata into canonical record.

        Uses the source's parser_type to determine parsing strategy.
        JSON API sources get rich structured normalization; HTML sources
        fall back to basic metadata extraction.
        """
        meta = raw_obj.raw_metadata_jsonb or {}

        source_record = SourceRecord(
            trusted_source_id=source.id,
            raw_object_id=raw_obj.id,
            canonical_title=meta.get("title", f"Record {raw_obj.external_id}"),
            source_category=source.source_category,
            culture=meta.get("culture"),
            language_family=meta.get("language_family", source.default_language),
            origin_place_name=meta.get("origin_place"),
            repository_institution=meta.get("repository"),
            provenance_status=ProvenanceStatus.UNKNOWN,
            record_status=RecordStatus.NORMALIZED,
            metadata_jsonb=meta,
        )

        if meta.get("medium"):
            source_record.metadata_jsonb["medium"] = meta["medium"]
        if meta.get("period"):
            source_record.metadata_jsonb["period"] = meta["period"]

        session.add(source_record)
        await session.flush()

        if "dates" in meta:
            for date_info in meta["dates"]:
                try:
                    date_record = SourceDate(
                        source_record_id=source_record.id,
                        date_type=DateType(date_info.get("type", "composition")),
                        date_start=date_info.get("start"),
                        date_end=date_info.get("end"),
                        date_label=date_info.get("label"),
                        dating_method=date_info.get("method"),
                        dating_confidence=DatingConfidence(
                            date_info.get("confidence", "uncertain")
                        ),
                        source_note=date_info.get("note"),
                    )
                    session.add(date_record)
                except Exception as exc:
                    logger.warning("Failed to add date for %s: %s", raw_obj.external_id, exc)

        text_content = meta.get("text", "")
        copyright_status = CopyrightStatus.UNKNOWN
        if meta.get("is_public_domain"):
            copyright_status = CopyrightStatus.PUBLIC_DOMAIN

        version = SourceVersion(
            source_record_id=source_record.id,
            version_type=VersionType.ORIGINAL,
            language=meta.get("language_family", source.default_language),
            copyright_status=copyright_status,
            is_preferred=True,
            r2_key=raw_obj.r2_key,
            text_extracted=text_content if text_content else None,
            metadata_jsonb={"parser": source.parser_type.value},
        )
        session.add(version)

        if meta.get("text") and meta.get("text_format") == "ATF":
            transliteration = SourceVersion(
                source_record_id=source_record.id,
                version_type=VersionType.TRANSLITERATION,
                language="Sumerian",
                copyright_status=CopyrightStatus.PUBLIC_DOMAIN,
                is_preferred=False,
                text_extracted=meta["text"],
                metadata_jsonb={"format": "ATF", "parser": "cdli_atf"},
            )
            session.add(transliteration)

        await session.flush()
        return source_record
