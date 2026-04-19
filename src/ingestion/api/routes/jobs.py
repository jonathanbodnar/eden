"""Job queue management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.enums import JobStatus, JobType
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.queue.manager import (
    cancel_job,
    enqueue_job,
    pause_job,
    recover_stalled_jobs,
    resume_job,
    retry_job,
)
from src.ingestion.schemas.jobs import (
    EnqueueJobRequest,
    JobCheckpointResponse,
    QueuedJobListResponse,
    QueuedJobResponse,
)

router = APIRouter()


@router.get("", response_model=QueuedJobListResponse)
async def list_jobs(
    status: JobStatus | None = Query(None),
    job_type: JobType | None = Query(None),
    trusted_source_id: uuid.UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    query = select(QueuedJob)
    count_query = select(func.count(QueuedJob.id))

    if status:
        query = query.where(QueuedJob.status == status)
        count_query = count_query.where(QueuedJob.status == status)
    if job_type:
        query = query.where(QueuedJob.job_type == job_type)
        count_query = count_query.where(QueuedJob.job_type == job_type)
    if trusted_source_id:
        query = query.where(QueuedJob.trusted_source_id == trusted_source_id)
        count_query = count_query.where(QueuedJob.trusted_source_id == trusted_source_id)

    query = query.order_by(QueuedJob.created_at.desc()).offset(offset).limit(limit)

    total = (await session.execute(count_query)).scalar() or 0
    items = (await session.execute(query)).scalars().all()

    return QueuedJobListResponse(
        items=[QueuedJobResponse.model_validate(j) for j in items],
        total=total,
    )


@router.get("/{job_id}", response_model=QueuedJobResponse)
async def get_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(QueuedJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return QueuedJobResponse.model_validate(job)


@router.get("/{job_id}/checkpoints", response_model=list[JobCheckpointResponse])
async def get_job_checkpoints(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(JobCheckpoint)
        .where(JobCheckpoint.queued_job_id == job_id)
        .order_by(JobCheckpoint.updated_at.desc())
    )
    checkpoints = result.scalars().all()
    return [JobCheckpointResponse.model_validate(cp) for cp in checkpoints]


@router.post("/enqueue", response_model=QueuedJobResponse, status_code=201)
async def enqueue(
    body: EnqueueJobRequest,
    session: AsyncSession = Depends(get_session),
):
    job = await enqueue_job(
        session,
        trusted_source_id=body.trusted_source_id,
        job_type=body.job_type,
        priority=body.priority,
        payload=body.payload,
    )
    await session.commit()
    return QueuedJobResponse.model_validate(job)


@router.post("/{job_id}/pause", status_code=204)
async def pause_job_endpoint(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await pause_job(session, job_id)


@router.post("/{job_id}/resume", status_code=204)
async def resume_job_endpoint(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await resume_job(session, job_id)


@router.post("/{job_id}/retry", status_code=204)
async def retry_job_endpoint(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await retry_job(session, job_id)


@router.post("/{job_id}/cancel", status_code=204)
async def cancel_job_endpoint(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await cancel_job(session, job_id)


@router.post("/recover-stalled", response_model=dict)
async def recover_stalled(
    session: AsyncSession = Depends(get_session),
):
    count = await recover_stalled_jobs(session)
    return {"recovered": count}
