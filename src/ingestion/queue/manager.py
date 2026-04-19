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


def _stages_for_run_type(run_type: RunType) -> list[JobType]:
    if run_type == RunType.DISCOVERY:
        return [JobType.DISCOVER]
    if run_type == RunType.REPROCESS:
        return [JobType.NORMALIZE, JobType.SEGMENT, JobType.EMBED]
    return list(PIPELINE_STAGES)


PARALLELIZABLE_STAGES = {JobType.FETCH, JobType.NORMALIZE, JobType.SEGMENT, JobType.EMBED}


async def create_source_run(
    session: AsyncSession,
    *,
    trusted_source_id: uuid.UUID,
    run_type: RunType,
    requested_by: str | None = None,
    notes: str | None = None,
    parallelism: int = 1,
    skip_stages: list[str] | None = None,
) -> SourceRun:
    """Create a source run and enqueue ALL pipeline stages concurrently.

    All stages are queued at once so workers can run in parallel.
    Downstream workers poll for records as upstream produces them.
    When parallelism > 1, multiple shard jobs are created for
    fetch/normalize/segment/embed stages so multiple workers can
    process the same source simultaneously.
    """
    run = SourceRun(
        trusted_source_id=trusted_source_id,
        run_type=run_type,
        status=RunStatus.QUEUED,
        requested_by=requested_by,
        notes=notes,
    )
    session.add(run)
    await session.flush()

    _skip = {s.lower() for s in (skip_stages or [])}
    stages = [s for s in _stages_for_run_type(run_type) if s.value not in _skip]
    for i, stage in enumerate(stages):
        shards = parallelism if stage in PARALLELIZABLE_STAGES else 1
        for _shard in range(shards):
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
    logger.info("Created source run %s [%s], queued all %d stages", run.id, run_type.value, len(stages))
    return run


async def enqueue_next_stage(
    session: AsyncSession,
    completed_job: QueuedJob,
) -> QueuedJob | None:
    """After a job succeeds, enqueue the next pipeline stage for this run."""
    if not completed_job.source_run_id:
        return None

    run = await session.get(SourceRun, completed_job.source_run_id)
    if not run:
        return None

    stages = _stages_for_run_type(run.run_type)
    current_stage = completed_job.job_type

    try:
        idx = stages.index(current_stage)
    except ValueError:
        return None

    if idx + 1 >= len(stages):
        run.status = RunStatus.SUCCEEDED
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info("Source run %s completed — all stages done", run.id)
        return None

    next_stage = stages[idx + 1]
    job = await enqueue_job(
        session,
        trusted_source_id=completed_job.trusted_source_id,
        job_type=next_stage,
        source_run_id=run.id,
        priority=100 + idx + 1,
    )
    await session.commit()
    logger.info("Source run %s: stage %s done, queued next stage %s", run.id, current_stage.value, next_stage.value)
    return job


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


async def is_upstream_done(
    session: AsyncSession,
    source_run_id: uuid.UUID,
    current_stage: JobType,
) -> bool:
    """Check if ALL upstream pipeline stage jobs have completed for this run.

    With parallel sharding there can be multiple jobs for the same stage.
    All of them must be finished before downstream considers upstream done.
    """
    stages = list(PIPELINE_STAGES)
    try:
        idx = stages.index(current_stage)
    except ValueError:
        return True
    if idx == 0:
        return True

    upstream = stages[idx - 1]
    result = await session.execute(
        select(QueuedJob.status).where(
            QueuedJob.source_run_id == source_run_id,
            QueuedJob.job_type == upstream,
        )
    )
    statuses = result.scalars().all()
    if not statuses:
        return True
    return all(
        s in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED)
        for s in statuses
    )


async def update_source_progress(
    session: AsyncSession,
    trusted_source_id: uuid.UUID,
    **kwargs,
) -> None:
    """Update source_progress with real counts from the database."""
    from src.ingestion.models.discovered_record import DiscoveredRecord
    from src.ingestion.models.enums import DiscoveredRecordStatus, RecordStatus
    from src.ingestion.models.raw_object import RawObject
    from src.ingestion.models.source_record import SourceRecord
    from src.ingestion.models.source_version import SourceVersion
    from src.ingestion.models.segment import Segment

    counts: dict[str, int] = {}

    if "discovered_count" in kwargs:
        result = await session.execute(
            select(func.count()).select_from(DiscoveredRecord)
            .where(DiscoveredRecord.trusted_source_id == trusted_source_id)
        )
        counts["discovered_count"] = result.scalar() or 0

    if "fetched_count" in kwargs:
        result = await session.execute(
            select(func.count()).select_from(RawObject)
            .where(RawObject.trusted_source_id == trusted_source_id)
        )
        counts["fetched_count"] = result.scalar() or 0

    if "normalized_count" in kwargs:
        result = await session.execute(
            select(func.count()).select_from(SourceRecord)
            .where(SourceRecord.trusted_source_id == trusted_source_id)
        )
        counts["normalized_count"] = result.scalar() or 0

    if "segmented_count" in kwargs:
        result = await session.execute(
            select(func.count(Segment.id))
            .join(SourceVersion, Segment.source_version_id == SourceVersion.id)
            .join(SourceRecord, SourceVersion.source_record_id == SourceRecord.id)
            .where(SourceRecord.trusted_source_id == trusted_source_id)
        )
        counts["segmented_count"] = result.scalar() or 0

    if "embedded_count" in kwargs:
        counts["embedded_count"] = kwargs["embedded_count"]

    if not counts:
        counts = kwargs

    existing = await session.execute(
        select(SourceProgress).where(SourceProgress.trusted_source_id == trusted_source_id)
    )
    progress = existing.scalar_one_or_none()
    if not progress:
        progress = SourceProgress(trusted_source_id=trusted_source_id, **counts)
        session.add(progress)
    else:
        for key, value in counts.items():
            if hasattr(progress, key):
                setattr(progress, key, value)
    progress.last_updated_at = datetime.now(timezone.utc)
    await session.flush()
