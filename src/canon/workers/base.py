"""Base worker class for System B background processing."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import async_session_factory
from src.canon.models.enums import WorldJobType
from src.canon.queue.manager import JobQueueManager

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    job_types: list[WorldJobType] = []
    poll_interval: float = 5.0

    def __init__(self):
        self.worker_id = f"{self.__class__.__name__}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._running = False

    @abstractmethod
    async def process(self, session: AsyncSession, job_id: uuid.UUID, payload: dict | None) -> dict:
        """Process a job. Return result dict on success, raise on failure."""
        ...

    async def run_loop(self):
        self._running = True
        logger.info("Worker %s starting, listening for %s", self.worker_id, [jt.value for jt in self.job_types])

        while self._running:
            try:
                async with async_session_factory() as session:
                    qm = JobQueueManager(session)
                    job = await qm.claim_next(self.job_types, self.worker_id)

                    if not job:
                        await asyncio.sleep(self.poll_interval)
                        continue

                    logger.info("Processing job %s type=%s", job.id, job.job_type)
                    try:
                        result = await self.process(session, job.id, job.payload_json)
                        await qm.complete(job.id, result)
                        await session.commit()
                        logger.info("Job %s completed successfully", job.id)
                    except Exception as e:
                        await session.rollback()
                        async with async_session_factory() as err_session:
                            err_qm = JobQueueManager(err_session)
                            await err_qm.fail(job.id, str(e))
                            await err_session.commit()
                        logger.exception("Job %s failed: %s", job.id, e)

            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(self.poll_interval * 2)

    def stop(self):
        self._running = False
