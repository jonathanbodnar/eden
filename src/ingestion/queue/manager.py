"""Postgres-backed job queue with row-level locking for worker claim."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.config import settings
from src.ingestion.models.enums import JobStatus, JobType, RunStatus, RunType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.source_progress import SourceProgress
from src.ingestion.models.source_run import SourceRun

logger = logging.getLogger(__name__)

PIPELINE_STAGES = [
    JobType.DISCOVER,
    JobType.FETCH,
    JobType.NORMALIZE,
    JobType.SEGMENT,
    JobType.EMBED,
]


async def enqueue_job(
    session: AsyncSession,
    *,
    trusted_source_id: uuid.UUID,
    job_type: JobType,
    source_run_id: uuid.UUID | None = None,
    priority: int = 100,
    payload: dict | None = None,
    scheduled_for: datetime | None = None,
) -> QueuedJob:
    job = QueuedJob(
        trusted_source_id=trusted_source_id,
        source_run_id=source_run_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        priority=priority,
        payload_jsonb=payload,
        scheduled_for=scheduled_for,
        max_attempts=settings.worker_max_attempts,
    )
    session.add(job)
    await session.flush()
    logger.info("Enqueued job %s [%s] for source %s", job.id, job_type.value, trusted_source_id)
    return job


async def create_source_run(
    session: AsyncSession,
    *,
    trusted_source_id: uuid.UUID,
    run_type: RunType,
    requested_by: str | None = None,
    notes: str | None = None,
) -> SourceRun:
    """Create a source run and enqueue all pipeline stage jobs."""
    run = SourceRun(
        trusted_source_id=trusted_source_id,
        run_type=run_type,
        status=RunStatus.QUEUED,
        requested_by=requested_by,
        notes=notes,
    )
    session.add(run)
    await session.flush()

    stages = PIPELINE_STAGES
    if run_type == RunType.DISCOVERY:
        stages = [JobType.DISCOVER]
    elif run_type == RunType.REPROCESS:
        stages = [JobType.NORMALIZE, JobType.SEGMENT, JobType.EMBED]

    for i, stage in enumerate(stages):
        await enqueue_job(
            session,
            trusted_source_id=trusted_source_id,
            job_type=stage,
            source_run_id=run.id,
            priority=100 + i,
        )

    progress = await session.execute(
        select(SourceProgress).where(SourceProgress.trusted_source_id == trusted_source_id)
    )
    if not progress.scalar_one_or_none():
        session.add(SourceProgress(trusted_source_id=trusted_source_id, last_run_id=run.id))
    else:
        await session.execute(
            update(SourceProgress)
            .where(SourceProgress.trusted_source_id == trusted_source_id)
            .values(last_run_id=run.id)
        )

    await session.commit()
    logger.info("Created source run %s [%s] with %d jobs", run.id, run_type.value, len(stages))
    return run


async def claim_job(
    session: AsyncSession,
    worker_id: str,
    job_types: list[JobType] | None = None,
) -> QueuedJob | None:
    """Claim the next available queued job using SELECT FOR UPDATE SKIP LOCKED."""
    now = datetime.now(timezone.utc)

    filters = [
        QueuedJob.status == JobStatus.QUEUED,
    ]
    if job_types:
        filters.append(QueuedJob.job_type.in_(job_types))

    filters.append(
        (QueuedJob.scheduled_for.is_(None)) | (QueuedJob.scheduled_for <= now)
    )

    stmt = (
        select(QueuedJob)
        .where(and_(*filters))
        .order_by(QueuedJob.priority.asc(), QueuedJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    result = await session.execute(stmt)
    job = result.scalar_one_or_none()

    if job is None:
        return None

    job.status = JobStatus.RUNNING
    job.worker_id = worker_id
    job.started_at = now
    job.last_heartbeat_at = now
    job.attempt_count += 1
    await session.commit()

    logger.info("Worker %s claimed job %s [%s]", worker_id, job.id, job.job_type.value)
    return job


async def complete_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    success: bool = True,
    error_log: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    status = JobStatus.SUCCEEDED if success else JobStatus.FAILED
    await session.execute(
        update(QueuedJob)
        .where(QueuedJob.id == job_id)
        .values(status=status, completed_at=now, error_log=error_log)
    )
    await session.commit()
    logger.info("Job %s completed with status %s", job_id, status.value)


async def heartbeat(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(QueuedJob)
        .where(QueuedJob.id == job_id)
        .values(last_heartbeat_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def save_checkpoint(
    session: AsyncSession,
    *,
    queued_job_id: uuid.UUID,
    checkpoint_type: str,
    cursor_value: str | None = None,
    external_id_last_processed: str | None = None,
    records_processed: int = 0,
    records_total_estimate: int | None = None,
    bytes_processed: int = 0,
    stage_percent: float | None = None,
    extra: dict | None = None,
) -> JobCheckpoint:
    existing = await session.execute(
        select(JobCheckpoint).where(JobCheckpoint.queued_job_id == queued_job_id).limit(1)
    )
    cp = existing.scalar_one_or_none()

    if cp:
        cp.checkpoint_type = checkpoint_type
        cp.cursor_value = cursor_value
        cp.external_id_last_processed = external_id_last_processed
        cp.records_processed = records_processed
        cp.records_total_estimate = records_total_estimate
        cp.bytes_processed = bytes_processed
        cp.stage_percent = stage_percent
        cp.checkpoint_jsonb = extra
        cp.updated_at = datetime.now(timezone.utc)
    else:
        cp = JobCheckpoint(
            queued_job_id=queued_job_id,
            checkpoint_type=checkpoint_type,
            cursor_value=cursor_value,
            external_id_last_processed=external_id_last_processed,
            records_processed=records_processed,
            records_total_estimate=records_total_estimate,
            bytes_processed=bytes_processed,
            stage_percent=stage_percent,
            checkpoint_jsonb=extra,
        )
        session.add(cp)

    await session.flush()
    return cp


async def get_latest_checkpoint(
    session: AsyncSession, queued_job_id: uuid.UUID
) -> JobCheckpoint | None:
    result = await session.execute(
        select(JobCheckpoint)
        .where(JobCheckpoint.queued_job_id == queued_job_id)
        .order_by(JobCheckpoint.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def pause_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(QueuedJob)
        .where(QueuedJob.id == job_id)
        .values(status=JobStatus.PAUSED)
    )
    await session.commit()


async def resume_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(QueuedJob)
        .where(QueuedJob.id == job_id, QueuedJob.status == JobStatus.PAUSED)
        .values(status=JobStatus.QUEUED)
    )
    await session.commit()


async def cancel_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(QueuedJob)
        .where(QueuedJob.id == job_id, QueuedJob.status.in_([JobStatus.QUEUED, JobStatus.PAUSED]))
        .values(status=JobStatus.CANCELED)
    )
    await session.commit()


async def retry_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    result = await session.execute(select(QueuedJob).where(QueuedJob.id == job_id))
    job = result.scalar_one_or_none()
    if job and job.status == JobStatus.FAILED and job.attempt_count < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.error_log = None
        await session.commit()


async def recover_stalled_jobs(session: AsyncSession) -> int:
    """Find jobs with stale heartbeats and re-queue them."""
    threshold = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_stale_threshold_seconds
    )
    result = await session.execute(
        update(QueuedJob)
        .where(
            QueuedJob.status == JobStatus.RUNNING,
            QueuedJob.last_heartbeat_at < threshold,
            QueuedJob.attempt_count < QueuedJob.max_attempts,
        )
        .values(status=JobStatus.QUEUED, worker_id=None)
        .returning(QueuedJob.id)
    )
    recovered = result.fetchall()
    await session.commit()
    count = len(recovered)
    if count:
        logger.warning("Recovered %d stalled jobs", count)
    return count


async def update_source_progress(
    session: AsyncSession,
    trusted_source_id: uuid.UUID,
    **kwargs,
) -> None:
    """Increment or set fields on source_progress."""
    existing = await session.execute(
        select(SourceProgress).where(SourceProgress.trusted_source_id == trusted_source_id)
    )
    progress = existing.scalar_one_or_none()
    if not progress:
        progress = SourceProgress(trusted_source_id=trusted_source_id, **kwargs)
        session.add(progress)
    else:
        for key, value in kwargs.items():
            if hasattr(progress, key):
                setattr(progress, key, value)
    progress.last_updated_at = datetime.now(timezone.utc)
    await session.flush()
