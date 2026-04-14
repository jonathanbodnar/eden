"""Worker that runs canon synthesis jobs."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobType
from src.canon.services.canon_synth import CanonSynthService
from src.canon.workers.base import BaseWorker


class CanonSynthWorker(BaseWorker):
    job_types = [WorldJobType.SYNTH_CANON]

    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        svc = CanonSynthService()
        result = await svc.run_full_synthesis(session)
        return result
