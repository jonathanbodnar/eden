"""Worker that builds world packets for chapters."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobType
from src.canon.services.world_packet_builder import WorldPacketBuilderService
from src.canon.workers.base import BaseWorker


class WorldPacketWorker(BaseWorker):
    job_types = [WorldJobType.BUILD_WORLD_PACKETS]

    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        svc = WorldPacketBuilderService()
        result = await svc.run_full_build(session)
        return result
