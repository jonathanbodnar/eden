"""Source-record synthesis: extracts canonical entities from source record metadata.

This is faster and cheaper than segment-level extraction because:
- One AI call per batch of source records (not one per segment)
- Works from title + culture + dates (already structured data)
- 528K records → ~10K batches of 50 → manageable
- Focus on records that have meaningful titles and dating info
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.enums import HintType
from src.canon.models.extracted_hint import ExtractedHint
from src.canon.models.system_a import SASourceDate, SASourceRecord

logger = logging.getLogger(__name__)

BATCH_EXTRACTION_SYSTEM_PROMPT = """You are a historical/mythological knowledge extraction engine.
You will receive a list of ancient source records (texts, artifacts, sites) with metadata.
For each source, identify any:
- ACTORS: deities, rulers, mythic figures, historical persons, collectives mentioned in or associated with the source
- EVENTS: creation myths, floods, wars, migrations, foundlings, rituals associated with the source
- PLACES: cities, temples, rivers, mountains, sacred sites mentioned in or associated with the source

Focus on what is EXPLICITLY named or strongly implied by the title and metadata.
Normalize names to their most common English spelling.

Return a JSON array of hint objects. Each object must have:
- source_record_id: the ID from the input
- hints: array of {hint_type, name, description, time_start, time_end, confidence}

If a source has no clear entities, return an empty hints array for it."""

BATCH_EXTRACTION_TOOL = {
    "name": "record_batch_hints",
    "description": "Record extracted hints for a batch of source records.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_record_id": {"type": "string"},
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
                        },
                    },
                    "required": ["source_record_id", "hints"],
                },
            }
        },
        "required": ["results"],
    },
}

# Source categories most likely to contain mythological/historical entities
PRIORITY_CATEGORIES = {
    "primary_text",
    "mythology",
    "religious_text",
    "epic",
    "hymn",
    "historical_record",
    "inscription",
    "tablet",
    "manuscript",
    "article",
}


class SourceRecordSynthService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def get_prioritized_records(
        self,
        session: AsyncSession,
        after_id: uuid.UUID | None = None,
        limit: int = 30,
    ) -> list[tuple[SASourceRecord, list[SASourceDate]]]:
        """Get source records prioritized by content value, with their dates.
        Uses cursor-based pagination."""
        q = (
            select(SASourceRecord)
            .where(
                SASourceRecord.canonical_title.isnot(None),
                SASourceRecord.canonical_title != "",
            )
            .order_by(SASourceRecord.id)
            .limit(limit)
        )
        if after_id is not None:
            q = q.where(SASourceRecord.id > after_id)

        records = (await session.execute(q)).scalars().all()
        results = []
        for rec in records:
            dates_q = select(SASourceDate).where(
                SASourceDate.source_record_id == rec.id
            ).limit(3)
            dates = (await session.execute(dates_q)).scalars().all()
            results.append((rec, list(dates)))

        return results

    def _build_batch_prompt(
        self,
        records_with_dates: list[tuple[SASourceRecord, list[SASourceDate]]],
    ) -> str:
        lines = ["Analyze these ancient sources and extract entities:\n"]
        for rec, dates in records_with_dates:
            line = f"ID: {rec.id}\n  Title: {rec.canonical_title}"
            if rec.culture:
                line += f"\n  Culture: {rec.culture}"
            if rec.origin_place_name:
                line += f"\n  Place: {rec.origin_place_name}"
            if dates:
                date_parts = []
                for d in dates:
                    if d.date_start or d.date_end:
                        label = d.date_label or d.date_type or ""
                        date_parts.append(
                            f"{label} {d.date_start or '?'} to {d.date_end or '?'} BCE/CE"
                        )
                if date_parts:
                    line += f"\n  Dates: {'; '.join(date_parts)}"
            lines.append(line)

        return "\n\n".join(lines)

    async def extract_from_batch(
        self,
        records_with_dates: list[tuple[SASourceRecord, list[SASourceDate]]],
    ) -> dict[str, list[dict]]:
        """Call Claude to extract entities from a batch of source records.
        Returns map of source_record_id → list of raw hint dicts."""
        if not settings.anthropic_api_key:
            logger.debug("No Anthropic API key configured, skipping source extraction")
            return {}
        if not records_with_dates:
            return {}

        prompt = self._build_batch_prompt(records_with_dates)
        try:
            response = await self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=8192,
                system=BATCH_EXTRACTION_SYSTEM_PROMPT,
                tools=[BATCH_EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "record_batch_hints"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "record_batch_hints":
                    results = block.input.get("results", [])
                    return {r["source_record_id"]: r["hints"] for r in results}
            return {}
        except Exception:
            logger.exception("Batch extraction failed")
            return {}

    async def run_extraction_batch(
        self,
        session: AsyncSession,
        batch_size: int = 30,
        max_records: int = 300,
        after_id: uuid.UUID | None = None,
    ) -> dict:
        """Run one bounded pass of source-record-level extraction."""
        if not settings.anthropic_api_key:
            return {"records_processed": 0, "hints_created": 0, "has_more": False}

        total_hints = 0
        records_processed = 0
        last_id: uuid.UUID | None = after_id

        remaining = max_records
        while remaining > 0:
            chunk = min(batch_size, remaining)
            records_with_dates = await self.get_prioritized_records(
                session, after_id=last_id, limit=chunk
            )
            if not records_with_dates:
                last_id = None
                break

            hints_by_record = await self.extract_from_batch(records_with_dates)

            for rec, dates in records_with_dates:
                raw_hints = hints_by_record.get(str(rec.id), [])
                for h in raw_hints:
                    try:
                        hint = ExtractedHint(
                            id=uuid.uuid4(),
                            hint_type=HintType(h["hint_type"]),
                            name=h["name"],
                            description=h.get("description"),
                            time_start=h.get("time_start"),
                            time_end=h.get("time_end"),
                            source_record_id=rec.id,
                            confidence=h.get("confidence", 0.5),
                            extraction_model=settings.anthropic_model,
                        )
                        session.add(hint)
                        total_hints += 1
                    except Exception:
                        logger.exception("Failed to create hint: %s", h)

                records_processed += 1
                last_id = rec.id

            await session.flush()
            remaining -= len(records_with_dates)

        return {
            "records_processed": records_processed,
            "hints_created": total_hints,
            "next_record_id": str(last_id) if last_id else None,
            "has_more": last_id is not None,
        }
