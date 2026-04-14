"""Worker that runs knowledge-prep-service extraction jobs."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobType
from src.canon.services.knowledge_prep import KnowledgePrepService
from src.canon.workers.base import BaseWorker


class KnowledgePrepWorker(BaseWorker):
    job_types = [WorldJobType.EXTRACT_HINTS]

    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        svc = KnowledgePrepService()
        batch_size = (payload or {}).get("batch_size")
        result = await svc.run_full_extraction(session, batch_size=batch_size)
        return result
