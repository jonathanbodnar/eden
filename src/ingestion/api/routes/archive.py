"""Archive inspection endpoints for provenance chain viewing."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.discovered_record import DiscoveredRecord
from src.ingestion.models.embedding import Embedding
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.segment import Segment
from src.ingestion.models.source_date import SourceDate
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.schemas.archive import (
    DiscoveredRecordResponse,
    ProvenanceChainResponse,
    RawObjectResponse,
    SegmentResponse,
    SourceDateResponse,
    SourceRecordResponse,
    SourceVersionResponse,
)

router = APIRouter()


@router.get("/raw-objects/{object_id}", response_model=RawObjectResponse)
async def get_raw_object(
    object_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    obj = await session.get(RawObject, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Raw object not found")
    return RawObjectResponse.model_validate(obj)


@router.get("/raw-objects", response_model=list[RawObjectResponse])
async def list_raw_objects(
    trusted_source_id: uuid.UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    query = select(RawObject)
    if trusted_source_id:
        query = query.where(RawObject.trusted_source_id == trusted_source_id)
    query = query.order_by(RawObject.fetched_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [RawObjectResponse.model_validate(o) for o in result.scalars().all()]


@router.get("/source-records/{record_id}", response_model=SourceRecordResponse)
async def get_source_record(
    record_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    record = await session.get(SourceRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Source record not found")
    return SourceRecordResponse.model_validate(record)


@router.get("/source-records", response_model=list[SourceRecordResponse])
async def list_source_records(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    query = select(SourceRecord).order_by(SourceRecord.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [SourceRecordResponse.model_validate(r) for r in result.scalars().all()]


@router.get("/source-records/{record_id}/dates", response_model=list[SourceDateResponse])
async def list_source_dates(
    record_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SourceDate).where(SourceDate.source_record_id == record_id)
    )
    return [SourceDateResponse.model_validate(d) for d in result.scalars().all()]


@router.get("/source-records/{record_id}/versions", response_model=list[SourceVersionResponse])
async def list_source_versions(
    record_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SourceVersion).where(SourceVersion.source_record_id == record_id)
    )
    return [SourceVersionResponse.model_validate(v) for v in result.scalars().all()]


@router.get("/versions/{version_id}/segments", response_model=list[SegmentResponse])
async def list_segments(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Segment)
        .where(Segment.source_version_id == version_id)
        .order_by(Segment.segment_order)
    )
    return [SegmentResponse.model_validate(s) for s in result.scalars().all()]


@router.get("/provenance/{record_id}", response_model=ProvenanceChainResponse)
async def get_provenance_chain(
    record_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Full provenance chain for a source record: source -> raw -> record -> dates -> versions -> segments -> embeddings."""
    source_record = await session.get(SourceRecord, record_id)
    if not source_record:
        raise HTTPException(status_code=404, detail="Source record not found")

    raw_object = await session.get(RawObject, source_record.raw_object_id)
    trusted_source = await session.get(TrustedSource, raw_object.trusted_source_id)

    discovered_record = None
    if raw_object.discovered_record_id:
        discovered_record = await session.get(DiscoveredRecord, raw_object.discovered_record_id)

    dates_result = await session.execute(
        select(SourceDate).where(SourceDate.source_record_id == record_id)
    )
    dates = dates_result.scalars().all()

    versions_result = await session.execute(
        select(SourceVersion).where(SourceVersion.source_record_id == record_id)
    )
    versions = versions_result.scalars().all()

    all_segments = []
    total_embeddings = 0
    for version in versions:
        segs_result = await session.execute(
            select(Segment)
            .where(Segment.source_version_id == version.id)
            .order_by(Segment.segment_order)
        )
        segs = segs_result.scalars().all()
        all_segments.extend(segs)

        for seg in segs:
            emb_count = (
                await session.execute(
                    select(func.count(Embedding.id)).where(Embedding.segment_id == seg.id)
                )
            ).scalar() or 0
            total_embeddings += emb_count

    return ProvenanceChainResponse(
        trusted_source={"id": str(trusted_source.id), "name": trusted_source.name, "slug": trusted_source.slug},
        discovered_record={
            "id": str(discovered_record.id),
            "external_id": discovered_record.external_id,
            "record_url": discovered_record.record_url,
        } if discovered_record else None,
        raw_object={
            "id": str(raw_object.id),
            "r2_key": raw_object.r2_key,
            "checksum": raw_object.checksum,
            "byte_size": raw_object.byte_size,
            "fetched_at": raw_object.fetched_at.isoformat(),
        },
        source_record={
            "id": str(source_record.id),
            "canonical_title": source_record.canonical_title,
            "source_category": source_record.source_category.value,
            "record_status": source_record.record_status.value,
        },
        source_dates=[
            {
                "id": str(d.id),
                "date_type": d.date_type.value,
                "date_start": d.date_start,
                "date_end": d.date_end,
                "date_label": d.date_label,
            }
            for d in dates
        ],
        source_versions=[
            {
                "id": str(v.id),
                "version_type": v.version_type.value,
                "language": v.language,
                "is_preferred": v.is_preferred,
            }
            for v in versions
        ],
        segments=[
            {
                "id": str(s.id),
                "segment_type": s.segment_type.value,
                "segment_order": s.segment_order,
                "citation_ref": s.citation_ref,
            }
            for s in all_segments
        ],
        embedding_count=total_embeddings,
    )
