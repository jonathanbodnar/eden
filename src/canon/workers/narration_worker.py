"""Worker that builds narration packets for chapters."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobType
from src.canon.services.narration_builder import NarrationBuilderService
from src.canon.workers.base import BaseWorker


class NarrationWorker(BaseWorker):
    job_types = [WorldJobType.BUILD_NARRATION]

    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        svc = NarrationBuilderService()
        result = await svc.run_full_build(session)
        return result
