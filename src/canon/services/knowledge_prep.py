"""Knowledge-prep-service: reads System A segments + contextual_statements,
uses Anthropic to extract actor/event/place hints, stores in extracted_hints.

Key design decisions:
- Uses AsyncAnthropic to avoid blocking the event loop
- Cursor-based pagination (no OFFSET) for scalability
- Idempotent: skips segments/statements that already have extracted hints
- Per-run limits to prevent runaway extraction jobs
- Focuses on segments with actual text content
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.enums import HintType
from src.canon.models.extracted_hint import ExtractedHint
from src.canon.models.system_a import (
    SAContextualStatement,
    SASegment,
    SASourceDate,
    SASourceRecord,
    SASourceVersion,
)

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """You are a historical/mythological knowledge extraction engine.
Given a text segment from an ancient source, extract structured hints about:
- ACTORS: deities, rulers, mythic figures, historical persons, collectives
- EVENTS: creation, flood, war, migration, founding, ritual, astronomical events
- PLACES: cities, temples, rivers, mountains, regions, sacred sites

For each hint, provide:
- hint_type: "actor", "event", or "place"
- name: canonical name (normalize spelling)
- description: brief description based on the text
- time_start: approximate year (negative for BCE), null if unknown
- time_end: approximate year, null if unknown
- confidence: 0.0-1.0 how confident you are this is correctly identified

Return ONLY valid JSON array of hint objects. If no hints found, return empty array []."""

EXTRACTION_TOOL = {
    "name": "record_hints",
    "description": "Record extracted actor/event/place hints from the source text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hint_type": {"type": "string", "enum": ["actor", "event", "place"]},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "time_start": {"type": ["integer", "null"]},
                        "time_end": {"type": ["integer", "null"]},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["hint_type", "name", "description", "confidence"],
                },
            }
        },
        "required": ["hints"],
    },
}


class KnowledgePrepService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            # Use AsyncAnthropic to avoid blocking the event loop
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def gather_source_context(
        self, session: AsyncSession, source_record_id: uuid.UUID
    ) -> dict:
        """Gather all relevant context for a source record from System A."""
        record = await session.get(SASourceRecord, source_record_id)
        if not record:
            return {}

        dates_q = select(SASourceDate).where(SASourceDate.source_record_id == source_record_id)
        dates = (await session.execute(dates_q)).scalars().all()

        versions_q = select(SASourceVersion).where(SASourceVersion.source_record_id == source_record_id)
        versions = (await session.execute(versions_q)).scalars().all()

        return {
            "record": record,
            "dates": dates,
            "versions": versions,
        }

    async def _segment_already_extracted(
        self, session: AsyncSession, segment_id: uuid.UUID
    ) -> bool:
        """Check if a segment has already had hints extracted."""
        q = select(exists().where(ExtractedHint.source_segment_id == segment_id))
        result = await session.execute(q)
        return result.scalar()

    async def _statement_already_extracted(
        self, session: AsyncSession, statement_id: uuid.UUID
    ) -> bool:
        """Check if a statement has already had hints extracted."""
        q = select(exists().where(ExtractedHint.source_statement_id == statement_id))
        result = await session.execute(q)
        return result.scalar()

    async def get_segments_for_extraction(
        self,
        session: AsyncSession,
        after_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[SASegment]:
        """Cursor-based pagination to avoid slow OFFSET queries.
        Only returns segments that have actual text content."""
        q = (
            select(SASegment)
            .where(
                SASegment.normalized_text.isnot(None),
                SASegment.normalized_text != "",
            )
            .order_by(SASegment.id)
            .limit(limit)
        )
        if after_id is not None:
            q = q.where(SASegment.id > after_id)
        result = await session.execute(q)
        return list(result.scalars().all())

    async def get_statements_for_extraction(
        self,
        session: AsyncSession,
        after_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[SAContextualStatement]:
        """Cursor-based pagination for statements."""
        q = (
            select(SAContextualStatement)
            .where(SAContextualStatement.statement_text.isnot(None))
            .order_by(SAContextualStatement.id)
            .limit(limit)
        )
        if after_id is not None:
            q = q.where(SAContextualStatement.id > after_id)
        result = await session.execute(q)
        return list(result.scalars().all())

    def _build_extraction_prompt(
        self,
        segment: SASegment | None = None,
        statement: SAContextualStatement | None = None,
        source_context: dict | None = None,
    ) -> str:
        parts = []
        if source_context and source_context.get("record"):
            rec = source_context["record"]
            parts.append(f"Source: {rec.canonical_title}")
            if rec.culture:
                parts.append(f"Culture: {rec.culture}")
            if source_context.get("dates"):
                for d in source_context["dates"]:
                    parts.append(f"Date: {d.date_label or ''} ({d.date_start} to {d.date_end})")

        if segment:
            text = segment.normalized_text or segment.original_text or ""
            # Limit text length to avoid huge prompts
            if len(text) > 3000:
                text = text[:3000] + "..."
            parts.append(f"\nSegment text:\n{text}")
        elif statement:
            parts.append(f"\nContextual statement:\n{statement.statement_text}")
            parts.append(f"Context type: {statement.context_type}")

        return "\n".join(parts)

    async def extract_hints_from_text(self, prompt_text: str) -> list[dict]:
        """Call Anthropic (async) to extract hints from text."""
        if not settings.anthropic_api_key:
            logger.debug("No Anthropic API key configured, skipping extraction")
            return []

        try:
            response = await self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=EXTRACTION_SYSTEM_PROMPT,
                tools=[EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "record_hints"},
                messages=[{"role": "user", "content": prompt_text}],
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "record_hints":
                    return block.input.get("hints", [])

            return []
        except Exception:
            logger.exception("Anthropic extraction failed")
            return []

    async def process_segment(
        self,
        session: AsyncSession,
        segment: SASegment,
        source_context: dict | None = None,
    ) -> list[ExtractedHint]:
        """Extract hints from a single segment and persist them."""
        prompt = self._build_extraction_prompt(segment=segment, source_context=source_context)
        raw_hints = await self.extract_hints_from_text(prompt)

        hints = []
        for h in raw_hints:
            try:
                hint = ExtractedHint(
                    id=uuid.uuid4(),
                    hint_type=HintType(h["hint_type"]),
                    name=h["name"],
                    description=h.get("description"),
                    time_start=h.get("time_start"),
                    time_end=h.get("time_end"),
                    source_segment_id=segment.id,
                    source_record_id=None,
                    confidence=h.get("confidence", 0.5),
                    extraction_model=settings.anthropic_model,
                )
                session.add(hint)
                hints.append(hint)
            except Exception:
                logger.exception("Failed to create hint from: %s", h)

        return hints

    async def process_statement(
        self,
        session: AsyncSession,
        statement: SAContextualStatement,
        source_context: dict | None = None,
    ) -> list[ExtractedHint]:
        """Extract hints from a contextual statement and persist them."""
        prompt = self._build_extraction_prompt(statement=statement, source_context=source_context)
        raw_hints = await self.extract_hints_from_text(prompt)

        hints = []
        for h in raw_hints:
            try:
                hint = ExtractedHint(
                    id=uuid.uuid4(),
                    hint_type=HintType(h["hint_type"]),
                    name=h["name"],
                    description=h.get("description"),
                    time_start=h.get("time_start"),
                    time_end=h.get("time_end"),
                    source_statement_id=statement.id,
                    source_record_id=statement.source_record_id,
                    confidence=h.get("confidence", 0.5),
                    extraction_model=settings.anthropic_model,
                )
                session.add(hint)
                hints.append(hint)
            except Exception:
                logger.exception("Failed to create hint from: %s", h)

        return hints

    async def run_extraction_batch(
        self,
        session: AsyncSession,
        batch_size: int = 50,
        max_items: int = 500,
        after_segment_id: uuid.UUID | None = None,
        after_statement_id: uuid.UUID | None = None,
    ) -> dict:
        """Run extraction on a bounded batch. Returns cursor positions for resuming.

        This is the primary extraction method - safe to call repeatedly.
        Each call processes at most max_items segments and max_items statements.
        """
        total_hints = 0
        segments_processed = 0
        statements_processed = 0
        last_segment_id: uuid.UUID | None = after_segment_id
        last_statement_id: uuid.UUID | None = after_statement_id

        # Process segments (cursor-based, skip already-processed)
        remaining = max_items
        after_id = after_segment_id
        while remaining > 0:
            chunk = min(batch_size, remaining)
            segments = await self.get_segments_for_extraction(
                session, after_id=after_id, limit=chunk
            )
            if not segments:
                last_segment_id = None  # Signal: reached end
                break

            for seg in segments:
                already_done = await self._segment_already_extracted(session, seg.id)
                if not already_done:
                    hints = await self.process_segment(session, seg)
                    total_hints += len(hints)
                segments_processed += 1
                last_segment_id = seg.id

            after_id = segments[-1].id
            remaining -= len(segments)
            await session.flush()

        # Process contextual statements
        remaining = max_items
        after_id = after_statement_id
        while remaining > 0:
            chunk = min(batch_size, remaining)
            statements = await self.get_statements_for_extraction(
                session, after_id=after_id, limit=chunk
            )
            if not statements:
                last_statement_id = None  # Signal: reached end
                break

            for stmt in statements:
                already_done = await self._statement_already_extracted(session, stmt.id)
                if not already_done:
                    hints = await self.process_statement(session, stmt)
                    total_hints += len(hints)
                statements_processed += 1
                last_statement_id = stmt.id

            after_id = statements[-1].id
            remaining -= len(statements)
            await session.flush()

        return {
            "segments_processed": segments_processed,
            "statements_processed": statements_processed,
            "total_hints": total_hints,
            "next_segment_id": str(last_segment_id) if last_segment_id else None,
            "next_statement_id": str(last_statement_id) if last_statement_id else None,
            "has_more": last_segment_id is not None or last_statement_id is not None,
        }

    async def run_full_extraction(
        self, session: AsyncSession, batch_size: int | None = None
    ) -> dict:
        """Run one bounded extraction pass (safe to call from API or worker).

        Processes up to 500 segments and 500 statements per call.
        Call repeatedly (using returned cursor IDs) to process everything.
        """
        bs = batch_size or settings.extraction_batch_size
        return await self.run_extraction_batch(
            session,
            batch_size=bs,
            max_items=500,
        )
