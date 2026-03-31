"""Base worker with checkpoint, heartbeat, and resume support."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.config import settings
from src.ingestion.database import async_session_factory
from src.ingestion.models.enums import JobStatus, JobType
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.queue.manager import (
    claim_job,
    complete_job,
    get_latest_checkpoint,
    heartbeat,
    save_checkpoint,
)

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Abstract base for all pipeline workers.

    Subclasses implement `process()` and declare `job_types`.
    The run loop handles claim, heartbeat, checkpoint, and error recovery.
    """

    job_types: list[JobType]

    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or f"{self.__class__.__name__}-{uuid.uuid4().hex[:8]}"
        self._running = True
        self._last_checkpoint_time = 0.0
        self._items_since_checkpoint = 0

    async def run_loop(self, poll_interval: float = 2.0) -> None:
        logger.info("Worker %s starting run loop for %s", self.worker_id, self.job_types)
        while self._running:
            async with async_session_factory() as session:
                job = await claim_job(session, self.worker_id, self.job_types)
                if job is None:
                    await asyncio.sleep(poll_interval)
                    continue

                logger.info("Processing job %s [%s]", job.id, job.job_type.value)
                await self._process_job(session, job)

    async def _process_job(self, session: AsyncSession, job: QueuedJob) -> None:
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.id))
        try:
            checkpoint = await get_latest_checkpoint(session, job.id)
            self._last_checkpoint_time = time.monotonic()
            self._items_since_checkpoint = 0

            await self.process(session, job, checkpoint)

            await complete_job(session, job.id, success=True)
            logger.info("Job %s succeeded", job.id)

        except Exception as exc:
            logger.exception("Job %s failed: %s", job.id, exc)
            await complete_job(session, job.id, success=False, error_log=str(exc))

        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self, job_id: uuid.UUID) -> None:
        interval = settings.worker_heartbeat_interval_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                async with async_session_factory() as session:
                    await heartbeat(session, job_id)
            except Exception:
                logger.warning("Heartbeat failed for job %s", job_id, exc_info=True)

    async def maybe_checkpoint(
        self,
        session: AsyncSession,
        job: QueuedJob,
        *,
        checkpoint_type: str,
        cursor_value: str | None = None,
        external_id_last_processed: str | None = None,
        records_processed: int = 0,
        records_total_estimate: int | None = None,
        bytes_processed: int = 0,
        stage_percent: float | None = None,
        extra: dict | None = None,
        force: bool = False,
    ) -> None:
        """Save checkpoint if interval thresholds are met or force=True."""
        self._items_since_checkpoint += 1
        elapsed = time.monotonic() - self._last_checkpoint_time
        item_threshold = settings.worker_checkpoint_interval_items
        time_threshold = settings.worker_checkpoint_interval_seconds

        if not force and self._items_since_checkpoint < item_threshold and elapsed < time_threshold:
            return

        await save_checkpoint(
            session,
            queued_job_id=job.id,
            checkpoint_type=checkpoint_type,
            cursor_value=cursor_value,
            external_id_last_processed=external_id_last_processed,
            records_processed=records_processed,
            records_total_estimate=records_total_estimate,
            bytes_processed=bytes_processed,
            stage_percent=stage_percent,
            extra=extra,
        )
        self._last_checkpoint_time = time.monotonic()
        self._items_since_checkpoint = 0

    def stop(self) -> None:
        self._running = False
        logger.info("Worker %s stopping", self.worker_id)

    @abstractmethod
    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: object | None,
    ) -> None:
        """Implement the stage-specific processing logic."""
        ...
