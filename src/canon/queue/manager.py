"""Postgres-backed job queue for System B workers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.enums import WorldJobStatus, WorldJobType
from src.canon.models.world_job import WorldJobCheckpoint, WorldQueuedJob

logger = logging.getLogger(__name__)


class JobQueueManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(
        self,
        job_type: WorldJobType,
        payload: dict | None = None,
        priority: int = 100,
        max_attempts: int = 3,
    ) -> WorldQueuedJob:
        job = WorldQueuedJob(
            id=uuid.uuid4(),
            job_type=job_type,
            status=WorldJobStatus.QUEUED,
            priority=priority,
            payload_json=payload,
            max_attempts=max_attempts,
        )
        self.session.add(job)
        await self.session.flush()
        logger.info("Enqueued job %s type=%s", job.id, job_type.value)
        return job

    async def claim_next(
        self, job_types: list[WorldJobType], worker_id: str
    ) -> WorldQueuedJob | None:
        q = (
            select(WorldQueuedJob)
            .where(
                WorldQueuedJob.status == WorldJobStatus.QUEUED,
                WorldQueuedJob.job_type.in_(job_types),
            )
            .order_by(WorldQueuedJob.priority.desc(), WorldQueuedJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(q)
        job = result.scalar_one_or_none()

        if job:
            job.status = WorldJobStatus.RUNNING
            job.worker_id = worker_id
            job.started_at = datetime.now(timezone.utc)
            job.attempts += 1
            await self.session.flush()
            logger.info("Worker %s claimed job %s", worker_id, job.id)

        return job

    async def complete(self, job_id: uuid.UUID, result: dict | None = None) -> None:
        job = await self.session.get(WorldQueuedJob, job_id)
        if job:
            job.status = WorldJobStatus.SUCCEEDED
            job.completed_at = datetime.now(timezone.utc)
            job.result_json = result
            await self.session.flush()

    async def fail(self, job_id: uuid.UUID, error: str) -> None:
        job = await self.session.get(WorldQueuedJob, job_id)
        if job:
            if job.attempts < job.max_attempts:
                job.status = WorldJobStatus.QUEUED
                job.worker_id = None
            else:
                job.status = WorldJobStatus.FAILED
                job.completed_at = datetime.now(timezone.utc)
            job.error = error
            await self.session.flush()

    async def save_checkpoint(
        self, job_id: uuid.UUID, data: dict, items_processed: int
    ) -> WorldJobCheckpoint:
        cp = WorldJobCheckpoint(
            id=uuid.uuid4(),
            job_id=job_id,
            checkpoint_data=data,
            items_processed=items_processed,
        )
        self.session.add(cp)
        await self.session.flush()
        return cp

    async def get_latest_checkpoint(
        self, job_id: uuid.UUID
    ) -> WorldJobCheckpoint | None:
        q = (
            select(WorldJobCheckpoint)
            .where(WorldJobCheckpoint.job_id == job_id)
            .order_by(WorldJobCheckpoint.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(q)
        return result.scalar_one_or_none()
