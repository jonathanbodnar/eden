"""Context extraction worker: hybrid rules + LLM pipeline for secondary sources."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.config import settings
from src.ingestion.models.contextual_statement import ContextualStatement
from src.ingestion.models.enums import (
    ContextType,
    ExtractionMethod,
    JobType,
    ReviewStatus,
    StatementConfidence,
)
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.segment import Segment
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.services.rules_classifier import RulesVerdict, classify_with_rules
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)

RULES_ENGINE_VERSION = "1.0.0"


class ContextExtractionWorker(BaseWorker):
    job_types = [JobType.EXTRACT_CONTEXT]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._anthropic = None

    @property
    def anthropic(self):
        if self._anthropic is None:
            from src.ingestion.services.anthropic_classifier import AnthropicClassifier
            self._anthropic = AnthropicClassifier()
        return self._anthropic

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source:
            logger.warning("Source %s not found, skipping job", job.trusted_source_id)
            return

        if not source.is_secondary_source:
            logger.info("Source %s is not a secondary source, skipping", source.slug)
            return

        last_segment_id = None
        records_processed = 0
        statements_created = 0
        if checkpoint:
            last_segment_id = checkpoint.external_id_last_processed
            records_processed = checkpoint.records_processed
            if checkpoint.checkpoint_jsonb:
                statements_created = checkpoint.checkpoint_jsonb.get("statements_created", 0)

        segments = await self._get_segments_for_source(session, source.id)

        skip = True if last_segment_id else False
        ambiguous_batch: list[tuple[str, str, Segment]] = []
        batch_size = settings.context_extraction_batch_size

        for segment in segments:
            if skip:
                if str(segment.id) == last_segment_id:
                    skip = False
                continue

            existing = await session.execute(
                select(ContextualStatement)
                .where(ContextualStatement.segment_id == segment.id)
                .limit(1)
            )
            if existing.scalar_one_or_none():
                records_processed += 1
                continue

            text = segment.original_text or segment.normalized_text or ""
            if not text.strip():
                records_processed += 1
                continue

            rules_result = classify_with_rules(text)

            if rules_result.verdict == RulesVerdict.CONTEXTUAL:
                stmt = ContextualStatement(
                    source_record_id=await self._get_source_record_id(session, segment),
                    source_version_id=segment.source_version_id,
                    segment_id=segment.id,
                    statement_text=text,
                    context_type=rules_result.context_type or ContextType.UNCERTAIN,
                    confidence=rules_result.confidence,
                    extraction_method=ExtractionMethod.RULES_BASED,
                    classifier_version=RULES_ENGINE_VERSION,
                    supporting_quote=text[:500],
                    review_status=ReviewStatus.PENDING,
                )
                session.add(stmt)
                statements_created += 1

            elif rules_result.verdict == RulesVerdict.AMBIGUOUS:
                if settings.context_extraction_rules_only:
                    records_processed += 1
                    continue
                ambiguous_batch.append((str(segment.id), text, segment))

                if len(ambiguous_batch) >= batch_size:
                    created = await self._process_llm_batch(session, ambiguous_batch)
                    statements_created += created
                    ambiguous_batch = []

            records_processed += 1

            await self.maybe_checkpoint(
                session, job,
                checkpoint_type="context_extraction",
                external_id_last_processed=str(segment.id),
                records_processed=records_processed,
                extra={"statements_created": statements_created},
            )

        if ambiguous_batch:
            created = await self._process_llm_batch(session, ambiguous_batch)
            statements_created += created

        await self.maybe_checkpoint(
            session, job,
            checkpoint_type="context_extraction",
            records_processed=records_processed,
            stage_percent=100.0,
            extra={"statements_created": statements_created},
            force=True,
        )

        logger.info(
            "Context extraction complete for %s: %d segments processed, %d statements created",
            source.slug, records_processed, statements_created,
        )

    async def _get_segments_for_source(
        self, session: AsyncSession, trusted_source_id
    ) -> list[Segment]:
        """Get all segments belonging to a secondary source via the version->record chain."""
        result = await session.execute(
            select(Segment)
            .join(SourceVersion, Segment.source_version_id == SourceVersion.id)
            .join(SourceRecord, SourceVersion.source_record_id == SourceRecord.id)
            .where(SourceRecord.trusted_source_id == trusted_source_id)
            .order_by(Segment.created_at)
        )
        return list(result.scalars().all())

    async def _get_source_record_id(self, session: AsyncSession, segment: Segment):
        """Get source_record_id for a segment via its source_version."""
        version = await session.get(SourceVersion, segment.source_version_id)
        if version:
            return version.source_record_id
        return None

    async def _process_llm_batch(
        self,
        session: AsyncSession,
        batch: list[tuple[str, str, Segment]],
    ) -> int:
        """Send ambiguous segments through the Anthropic LLM classifier."""
        created = 0
        segments_for_llm = [(seg_id, text) for seg_id, text, _ in batch]
        segment_map = {seg_id: seg for seg_id, _, seg in batch}

        try:
            results = self.anthropic.classify_batch(segments_for_llm)
        except Exception as exc:
            logger.error("Anthropic batch classification failed: %s", exc)
            return 0

        for seg_id, result in results:
            if not result.is_contextual:
                continue

            segment = segment_map.get(seg_id)
            if not segment:
                continue

            source_record_id = await self._get_source_record_id(session, segment)

            extraction_method = ExtractionMethod.HYBRID if result.is_contextual else ExtractionMethod.LLM_CLASSIFIED

            stmt = ContextualStatement(
                source_record_id=source_record_id,
                source_version_id=segment.source_version_id,
                segment_id=segment.id,
                statement_text=result.statement_text or segment.original_text or "",
                context_type=result.context_type or ContextType.UNCERTAIN,
                confidence=result.confidence,
                extraction_method=extraction_method,
                classifier_model=settings.anthropic_model,
                supporting_quote=result.supporting_quote[:500] if result.supporting_quote else None,
                review_status=ReviewStatus.PENDING,
            )
            session.add(stmt)
            created += 1

        await session.flush()
        return created
