"""Trusted source management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.enums import RunType
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import create_source_run
from src.ingestion.schemas.jobs import RunSourceRequest, SourceRunResponse
from src.ingestion.schemas.trusted_source import (
    TrustedSourceCreate,
    TrustedSourceListResponse,
    TrustedSourceResponse,
    TrustedSourceUpdate,
)

router = APIRouter()


@router.get("", response_model=TrustedSourceListResponse)
async def list_sources(
    active_only: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    query = select(TrustedSource)
    count_query = select(func.count(TrustedSource.id))

    if active_only:
        query = query.where(TrustedSource.active.is_(True))
        count_query = count_query.where(TrustedSource.active.is_(True))

    query = query.order_by(TrustedSource.priority, TrustedSource.name).offset(offset).limit(limit)

    total = (await session.execute(count_query)).scalar() or 0
    items = (await session.execute(query)).scalars().all()

    return TrustedSourceListResponse(
        items=[TrustedSourceResponse.model_validate(s) for s in items],
        total=total,
    )


@router.post("", response_model=TrustedSourceResponse, status_code=201)
async def create_source(
    body: TrustedSourceCreate,
    session: AsyncSession = Depends(get_session),
):
    existing = await session.execute(
        select(TrustedSource).where(TrustedSource.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Source with slug '{body.slug}' already exists")

    source = TrustedSource(**body.model_dump())
    session.add(source)
    await session.flush()

    await create_source_run(
        session,
        trusted_source_id=source.id,
        run_type=RunType.FULL_INGEST,
        requested_by="auto",
        notes="Automatically queued on source creation",
    )

    await session.refresh(source)
    return TrustedSourceResponse.model_validate(source)


@router.get("/{source_id}", response_model=TrustedSourceResponse)
async def get_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    source = await session.get(TrustedSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return TrustedSourceResponse.model_validate(source)


@router.patch("/{source_id}", response_model=TrustedSourceResponse)
async def update_source(
    source_id: uuid.UUID,
    body: TrustedSourceUpdate,
    session: AsyncSession = Depends(get_session),
):
    source = await session.get(TrustedSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(source, key, value)

    await session.commit()
    await session.refresh(source)
    return TrustedSourceResponse.model_validate(source)


@router.post("/{source_id}/pause", status_code=204)
async def pause_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    source = await session.get(TrustedSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.active = False
    await session.commit()


@router.post("/{source_id}/resume", status_code=204)
async def resume_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    source = await session.get(TrustedSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.active = True
    await session.commit()


@router.post("/{source_id}/run", response_model=SourceRunResponse)
async def run_source(
    source_id: uuid.UUID,
    body: RunSourceRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    source = await session.get(TrustedSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if not source.active:
        raise HTTPException(status_code=400, detail="Source is not active")

    run_type = body.run_type if body else RunType.FULL_INGEST
    requested_by = body.requested_by if body else None
    notes = body.notes if body else None
    parallelism = min(body.parallelism, 20) if body and body.parallelism else 1

    skip_stages = body.skip_stages if body else None

    run = await create_source_run(
        session,
        trusted_source_id=source_id,
        run_type=run_type,
        requested_by=requested_by,
        notes=notes,
        parallelism=parallelism,
        skip_stages=skip_stages,
    )
    return SourceRunResponse.model_validate(run)


@router.post("/{source_id}/reprocess", response_model=SourceRunResponse)
async def reprocess_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    source = await session.get(TrustedSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    run = await create_source_run(
        session,
        trusted_source_id=source_id,
        run_type=RunType.REPROCESS,
        requested_by="admin",
    )
    return SourceRunResponse.model_validate(run)
