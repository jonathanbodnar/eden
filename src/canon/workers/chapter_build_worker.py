"""Worker that runs chapter-building jobs."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobType
from src.canon.services.chapter_builder import ChapterBuilderService
from src.canon.workers.base import BaseWorker


class ChapterBuildWorker(BaseWorker):
    job_types = [WorldJobType.BUILD_CHAPTERS]

    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        svc = ChapterBuilderService()
        result = await svc.run_full_build(session)
        return result
