"""Change-detect-service: monitors System A for new/updated segments and statements.
Creates change_events when changes are detected."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.change_event import ChangeEvent
from src.canon.models.enums import ArchiveObjectType, ChangeType
from src.canon.models.system_a import SAContextualStatement, SASegment, SASourceDate

logger = logging.getLogger(__name__)


class ChangeDetectService:

    async def _get_last_scan_time(self, session: AsyncSession) -> datetime | None:
        """Get the most recent change event timestamp as our last scan marker."""
        q = select(func.max(ChangeEvent.created_at))
        result = await session.execute(q)
        return result.scalar()

    async def detect_new_segments(
        self, session: AsyncSession, since: datetime | None = None
    ) -> list[ChangeEvent]:
        """Detect segments created after the last scan."""
        q = select(SASegment)
        if since:
            q = q.where(SASegment.created_at >= since)

        segments = (await session.execute(q)).scalars().all()

        existing_q = select(ChangeEvent.source_object_id).where(
            ChangeEvent.source_object_type == ArchiveObjectType.SEGMENT,
        )
        existing_ids = set(
            row[0] for row in (await session.execute(existing_q)).all()
        )

        events = []
        for seg in segments:
            if seg.id in existing_ids:
                continue

            time_start, time_end = await self._get_time_range_for_segment(session, seg)

            event = ChangeEvent(
                id=uuid.uuid4(),
                change_type=ChangeType.NEW_SEGMENT,
                source_object_type=ArchiveObjectType.SEGMENT,
                source_object_id=seg.id,
                affected_time_start=time_start,
                affected_time_end=time_end,
                impact_score=0.5,
            )
            session.add(event)
            events.append(event)

        await session.flush()
        return events

    async def detect_new_statements(
        self, session: AsyncSession, since: datetime | None = None
    ) -> list[ChangeEvent]:
        """Detect contextual statements not yet tracked."""
        q = select(SAContextualStatement)
        statements = (await session.execute(q)).scalars().all()

        existing_q = select(ChangeEvent.source_object_id).where(
            ChangeEvent.source_object_type == ArchiveObjectType.CONTEXTUAL_STATEMENT,
        )
        existing_ids = set(
            row[0] for row in (await session.execute(existing_q)).all()
        )

        events = []
        for stmt in statements:
            if stmt.id in existing_ids:
                continue

            event = ChangeEvent(
                id=uuid.uuid4(),
                change_type=ChangeType.NEW_STATEMENT,
                source_object_type=ArchiveObjectType.CONTEXTUAL_STATEMENT,
                source_object_id=stmt.id,
                impact_score=0.3,
            )
            session.add(event)
            events.append(event)

        await session.flush()
        return events

    async def _get_time_range_for_segment(
        self, session: AsyncSession, segment: SASegment
    ) -> tuple[int | None, int | None]:
        """Try to get time range from the source record's dates."""
        try:
            from src.canon.models.system_a import SASourceVersion
            version = await session.get(SASourceVersion, segment.source_version_id)
            if not version:
                return None, None

            dates_q = select(SASourceDate).where(
                SASourceDate.source_record_id == version.source_record_id
            ).limit(1)
            date = (await session.execute(dates_q)).scalar_one_or_none()
            if date:
                return date.date_start, date.date_end
        except Exception:
            pass
        return None, None

    async def run_full_detection(self, session: AsyncSession) -> dict:
        """Run full change detection scan."""
        since = await self._get_last_scan_time(session)
        new_segs = await self.detect_new_segments(session, since)
        new_stmts = await self.detect_new_statements(session, since)
        return {
            "new_segment_events": len(new_segs),
            "new_statement_events": len(new_stmts),
        }
