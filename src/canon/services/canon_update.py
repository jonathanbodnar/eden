"""Canon-update-worker logic: processes update targets, rebuilds affected canon objects
with versioning, and rebuilds dependent chapters/packets."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.change_event import CanonUpdateTarget
from src.canon.models.enums import CanonicalType, UpdateTargetStatus
from src.canon.services.scoring_service import ScoringService

logger = logging.getLogger(__name__)


class CanonUpdateService:
    def __init__(self):
        self.scoring = ScoringService()

    async def process_update_target(
        self, session: AsyncSession, target: CanonUpdateTarget
    ) -> bool:
        """Process a single update target: re-score and version the entity."""
        target.status = UpdateTargetStatus.PROCESSING
        await session.flush()

        try:
            if target.target_type in (CanonicalType.ACTOR, CanonicalType.EVENT, CanonicalType.PLACE):
                await self._rescore_entity(session, target.target_type, target.target_id)
            elif target.target_type == CanonicalType.CHAPTER:
                await self._rebuild_chapter_summary(session, target.target_id)

            target.status = UpdateTargetStatus.COMPLETED
            await session.flush()
            return True
        except Exception:
            logger.exception("Failed to process update target %s", target.id)
            target.status = UpdateTargetStatus.FAILED
            await session.flush()
            return False

    async def _rescore_entity(
        self,
        session: AsyncSession,
        entity_type: CanonicalType,
        entity_id: uuid.UUID,
    ) -> None:
        """Re-score a canonical entity after a change."""
        model_map = {
            CanonicalType.ACTOR: CanonicalActor,
            CanonicalType.EVENT: CanonicalEvent,
            CanonicalType.PLACE: CanonicalPlace,
        }
        model_cls = model_map.get(entity_type)
        if not model_cls:
            return

        entity = await session.get(model_cls, entity_id)
        if not entity or not entity.is_current:
            return

        merge_conf = getattr(entity, "merge_confidence", None)
        await self.scoring.score_entity(
            session, entity_type, entity_id,
            entity.time_start, entity.time_end, merge_conf,
        )

        entity.version += 1
        logger.info("Re-scored and versioned %s %s to v%d", entity_type.value, entity_id, entity.version)

    async def _rebuild_chapter_summary(
        self, session: AsyncSession, chapter_id: uuid.UUID
    ) -> None:
        """Rebuild a chapter's summary based on its current dependencies."""
        chapter = await session.get(CanonicalChapter, chapter_id)
        if not chapter or not chapter.is_current:
            return

        deps_q = select(CanonDependency).where(
            CanonDependency.parent_type == CanonicalType.CHAPTER,
            CanonDependency.parent_id == chapter_id,
        )
        deps = (await session.execute(deps_q)).scalars().all()

        actor_names = []
        event_names = []
        for dep in deps:
            if dep.child_type == CanonicalType.ACTOR:
                actor = await session.get(CanonicalActor, dep.child_id)
                if actor and actor.is_current:
                    actor_names.append(actor.canonical_name)
            elif dep.child_type == CanonicalType.EVENT:
                event = await session.get(CanonicalEvent, dep.child_id)
                if event and event.is_current:
                    event_names.append(event.canonical_name)

        summary_parts = []
        if actor_names:
            summary_parts.append(f"Key figures: {', '.join(actor_names[:5])}")
        if event_names:
            summary_parts.append(f"Key events: {', '.join(event_names[:5])}")

        chapter.chapter_summary = ". ".join(summary_parts) if summary_parts else chapter.chapter_summary
        chapter.version += 1
        logger.info("Rebuilt chapter %s summary to v%d", chapter_id, chapter.version)

    async def process_all_pending(self, session: AsyncSession) -> dict:
        """Process all pending update targets in priority order."""
        q = (
            select(CanonUpdateTarget)
            .where(CanonUpdateTarget.status == UpdateTargetStatus.PENDING)
            .order_by(CanonUpdateTarget.priority.desc())
        )
        targets = (await session.execute(q)).scalars().all()

        processed = 0
        failed = 0
        for target in targets:
            success = await self.process_update_target(session, target)
            if success:
                processed += 1
            else:
                failed += 1

        return {"processed": processed, "failed": failed}
