"""Progress and status endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.embedding import Embedding
from src.ingestion.models.enums import JobStatus
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.segment import Segment
from src.ingestion.models.source_progress import SourceProgress
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.schemas.progress import (
    OverviewResponse,
    SourceProgressResponse,
    SourceProgressWithName,
)

router = APIRouter()


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    session: AsyncSession = Depends(get_session),
):
    total_sources = (await session.execute(select(func.count(TrustedSource.id)))).scalar() or 0
    active_sources = (
        await session.execute(
            select(func.count(TrustedSource.id)).where(TrustedSource.active.is_(True))
        )
    ).scalar() or 0
    total_raw = (await session.execute(select(func.count(RawObject.id)))).scalar() or 0
    total_records = (await session.execute(select(func.count(SourceRecord.id)))).scalar() or 0
    total_versions = (await session.execute(select(func.count(SourceVersion.id)))).scalar() or 0
    total_segments = (await session.execute(select(func.count(Segment.id)))).scalar() or 0
    total_embeddings = (await session.execute(select(func.count(Embedding.id)))).scalar() or 0

    total_bytes = (
        await session.execute(select(func.coalesce(func.sum(SourceProgress.total_bytes_stored), 0)))
    ).scalar() or 0

    jobs_running = (
        await session.execute(
            select(func.count(QueuedJob.id)).where(QueuedJob.status == JobStatus.RUNNING)
        )
    ).scalar() or 0
    jobs_queued = (
        await session.execute(
            select(func.count(QueuedJob.id)).where(QueuedJob.status == JobStatus.QUEUED)
        )
    ).scalar() or 0
    jobs_failed = (
        await session.execute(
            select(func.count(QueuedJob.id)).where(QueuedJob.status == JobStatus.FAILED)
        )
    ).scalar() or 0

    return OverviewResponse(
        total_trusted_sources=total_sources,
        active_trusted_sources=active_sources,
        total_raw_objects=total_raw,
        total_source_records=total_records,
        total_versions=total_versions,
        total_segments=total_segments,
        total_embeddings=total_embeddings,
        total_bytes_stored=total_bytes,
        jobs_running=jobs_running,
        jobs_queued=jobs_queued,
        jobs_failed=jobs_failed,
    )


@router.get("/sources", response_model=list[SourceProgressWithName])
async def get_all_source_progress(
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SourceProgress, TrustedSource.name, TrustedSource.slug, TrustedSource.active)
        .join(TrustedSource, SourceProgress.trusted_source_id == TrustedSource.id)
        .order_by(TrustedSource.priority, TrustedSource.name)
    )
    rows = result.all()

    return [
        SourceProgressWithName(
            **SourceProgressResponse.model_validate(progress).model_dump(),
            source_name=name,
            source_slug=slug,
            active=active,
        )
        for progress, name, slug, active in rows
    ]


@router.get("/sources/{source_id}", response_model=SourceProgressResponse)
async def get_source_progress(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SourceProgress).where(SourceProgress.trusted_source_id == source_id)
    )
    progress = result.scalar_one_or_none()
    if not progress:
        raise HTTPException(status_code=404, detail="Progress data not found for this source")
    return SourceProgressResponse.model_validate(progress)
