"""Impact-resolver: maps change events to affected canonical objects.
Creates canon_update_targets for each affected entity."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.change_event import CanonUpdateTarget, ChangeEvent
from src.canon.models.enums import (
    ArchiveObjectType,
    CanonicalType,
    UpdateTargetStatus,
)

logger = logging.getLogger(__name__)


class ImpactResolver:

    async def resolve_change_event(
        self, session: AsyncSession, change_event: ChangeEvent
    ) -> list[CanonUpdateTarget]:
        """Given a change event, find all affected canonical objects."""
        targets = []

        affected_canonical = await self._find_affected_by_archive_object(
            session,
            change_event.source_object_type,
            change_event.source_object_id,
        )

        if change_event.affected_time_start is not None or change_event.affected_time_end is not None:
            time_affected = await self._find_affected_by_time_range(
                session,
                change_event.affected_time_start,
                change_event.affected_time_end,
            )
            for item in time_affected:
                if item not in affected_canonical:
                    affected_canonical.append(item)

        for canonical_type, canonical_id in affected_canonical:
            existing_q = select(CanonUpdateTarget).where(
                CanonUpdateTarget.change_event_id == change_event.id,
                CanonUpdateTarget.target_type == canonical_type,
                CanonUpdateTarget.target_id == canonical_id,
            )
            if (await session.execute(existing_q)).scalar_one_or_none():
                continue

            priority = self._compute_priority(change_event, canonical_type)
            target = CanonUpdateTarget(
                id=uuid.uuid4(),
                change_event_id=change_event.id,
                target_type=canonical_type,
                target_id=canonical_id,
                priority=priority,
                status=UpdateTargetStatus.PENDING,
            )
            session.add(target)
            targets.append(target)

        chapter_targets = await self._propagate_to_chapters(session, change_event.id, affected_canonical)
        targets.extend(chapter_targets)

        await session.flush()
        logger.info("Resolved %d update targets for change event %s", len(targets), change_event.id)
        return targets

    async def _find_affected_by_archive_object(
        self,
        session: AsyncSession,
        archive_type: ArchiveObjectType,
        archive_id: uuid.UUID,
    ) -> list[tuple[CanonicalType, uuid.UUID]]:
        """Find canonical entities linked to a specific archive object."""
        q = select(CanonSupportLink.canonical_type, CanonSupportLink.canonical_id).where(
            CanonSupportLink.archive_object_type == archive_type,
            CanonSupportLink.archive_object_id == archive_id,
        )
        result = await session.execute(q)
        return [(row[0], row[1]) for row in result.all()]

    async def _find_affected_by_time_range(
        self,
        session: AsyncSession,
        time_start: int | None,
        time_end: int | None,
    ) -> list[tuple[CanonicalType, uuid.UUID]]:
        """Find chapters that overlap with the change's time range."""
        affected = []
        q = select(CanonicalChapter).where(CanonicalChapter.is_current.is_(True))

        if time_start is not None:
            q = q.where(CanonicalChapter.time_end >= time_start)
        if time_end is not None:
            q = q.where(CanonicalChapter.time_start <= time_end)

        chapters = (await session.execute(q)).scalars().all()
        for ch in chapters:
            affected.append((CanonicalType.CHAPTER, ch.id))
        return affected

    async def _propagate_to_chapters(
        self,
        session: AsyncSession,
        change_event_id: uuid.UUID,
        affected: list[tuple[CanonicalType, uuid.UUID]],
    ) -> list[CanonUpdateTarget]:
        """If an actor/event/place is affected, also mark its parent chapters."""
        child_ids = [
            (ct, cid) for ct, cid in affected
            if ct in (CanonicalType.ACTOR, CanonicalType.EVENT, CanonicalType.PLACE)
        ]
        if not child_ids:
            return []

        targets = []
        for child_type, child_id in child_ids:
            deps_q = select(CanonDependency).where(
                CanonDependency.child_type == child_type,
                CanonDependency.child_id == child_id,
                CanonDependency.parent_type == CanonicalType.CHAPTER,
            )
            deps = (await session.execute(deps_q)).scalars().all()
            for dep in deps:
                existing_q = select(CanonUpdateTarget).where(
                    CanonUpdateTarget.change_event_id == change_event_id,
                    CanonUpdateTarget.target_type == CanonicalType.CHAPTER,
                    CanonUpdateTarget.target_id == dep.parent_id,
                )
                if (await session.execute(existing_q)).scalar_one_or_none():
                    continue

                target = CanonUpdateTarget(
                    id=uuid.uuid4(),
                    change_event_id=change_event_id,
                    target_type=CanonicalType.CHAPTER,
                    target_id=dep.parent_id,
                    priority=5,
                    status=UpdateTargetStatus.PENDING,
                )
                session.add(target)
                targets.append(target)

        return targets

    def _compute_priority(
        self, change_event: ChangeEvent, canonical_type: CanonicalType
    ) -> int:
        """Higher priority = process first. Based on impact score and type."""
        base = int(change_event.impact_score * 10)
        type_boost = {
            CanonicalType.ACTOR: 3,
            CanonicalType.EVENT: 3,
            CanonicalType.PLACE: 2,
            CanonicalType.CHAPTER: 1,
        }
        return base + type_boost.get(canonical_type, 0)

    async def resolve_all_pending(self, session: AsyncSession) -> dict:
        """Resolve all change events that don't yet have update targets."""
        q = select(ChangeEvent).where(
            ~ChangeEvent.id.in_(
                select(CanonUpdateTarget.change_event_id).distinct()
            )
        )
        events = (await session.execute(q)).scalars().all()

        total_targets = 0
        for event in events:
            targets = await self.resolve_change_event(session, event)
            total_targets += len(targets)

        return {"events_resolved": len(events), "targets_created": total_targets}
