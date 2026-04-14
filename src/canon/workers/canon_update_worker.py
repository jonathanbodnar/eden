"""Worker that processes canon update targets from change detection."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobType
from src.canon.services.canon_update import CanonUpdateService
from src.canon.services.change_detect import ChangeDetectService
from src.canon.services.impact_resolver import ImpactResolver
from src.canon.workers.base import BaseWorker


class CanonUpdateWorker(BaseWorker):
    job_types = [WorldJobType.UPDATE_CANON]

    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        detect_svc = ChangeDetectService()
        detection = await detect_svc.run_full_detection(session)

        resolver = ImpactResolver()
        resolution = await resolver.resolve_all_pending(session)

        update_svc = CanonUpdateService()
        updates = await update_svc.process_all_pending(session)

        return {
            "detection": detection,
            "resolution": resolution,
            "updates": updates,
        }
