"""Collection browser: rich view of all ingested objects with images, text, context."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.ingestion.database import get_session
from src.ingestion.models.contextual_statement import ContextualStatement
from src.ingestion.models.object_image import ObjectImage
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.segment import Segment
from src.ingestion.models.source_date import SourceDate
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.storage.r2_client import r2_client

router = APIRouter()


class ImageSummary(BaseModel):
    id: uuid.UUID
    image_url: str
    r2_key: str | None = None
    alt_text: str | None
    caption: str | None
    image_order: int

    model_config = {"from_attributes": True}


class VersionSummary(BaseModel):
    id: uuid.UUID
    version_type: str
    language: str | None
    text_extracted: str | None
    is_preferred: bool

    model_config = {"from_attributes": True}


class DateSummary(BaseModel):
    id: uuid.UUID
    date_type: str
    date_start: int | None
    date_end: int | None
    date_label: str | None
    dating_confidence: str

    model_config = {"from_attributes": True}


class SegmentSummary(BaseModel):
    id: uuid.UUID
    segment_type: str
    segment_order: int
    original_text: str | None
    normalized_text: str | None

    model_config = {"from_attributes": True}


class ContextSummary(BaseModel):
    id: uuid.UUID
    statement_text: str
    context_type: str
    confidence: str
    review_status: str

    model_config = {"from_attributes": True}


class CollectionItem(BaseModel):
    id: uuid.UUID
    canonical_title: str
    source_category: str
    culture: str | None
    language_family: str | None
    origin_place_name: str | None
    repository_institution: str | None
    provenance_status: str
    record_status: str
    metadata_jsonb: dict | None
    created_at: datetime
    source_url: str | None
    source_name: str
    source_slug: str
    images: list[ImageSummary]
    versions: list[VersionSummary]
    dates: list[DateSummary]
    segment_count: int
    context_count: int


class CollectionItemDetail(CollectionItem):
    segments: list[SegmentSummary]
    context_statements: list[ContextSummary]


class CollectionListResponse(BaseModel):
    items: list[CollectionItem]
    total: int


class CollectionStats(BaseModel):
    total_records: int
    total_images: int
    total_versions: int
    total_segments: int
    total_contexts: int
    by_source: list[dict]
    by_category: dict[str, int]
    by_culture: dict[str, int]


@router.get("/stats", response_model=CollectionStats)
async def collection_stats(session: AsyncSession = Depends(get_session)):
    total_records = (await session.execute(select(func.count(SourceRecord.id)))).scalar() or 0
    total_images = (await session.execute(select(func.count(ObjectImage.id)))).scalar() or 0
    total_versions = (await session.execute(select(func.count(SourceVersion.id)))).scalar() or 0
    total_segments = (await session.execute(select(func.count(Segment.id)))).scalar() or 0
    total_contexts = (await session.execute(select(func.count(ContextualStatement.id)))).scalar() or 0

    by_source_q = (
        select(
            TrustedSource.name,
            TrustedSource.slug,
            func.count(SourceRecord.id).label("count"),
        )
        .join(SourceRecord, SourceRecord.trusted_source_id == TrustedSource.id)
        .group_by(TrustedSource.name, TrustedSource.slug)
        .order_by(func.count(SourceRecord.id).desc())
    )
    by_source = [
        {"name": r[0], "slug": r[1], "count": r[2]}
        for r in (await session.execute(by_source_q)).all()
    ]

    by_category_q = (
        select(SourceRecord.source_category, func.count(SourceRecord.id))
        .group_by(SourceRecord.source_category)
    )
    by_category = {
        str(r[0].value): r[1]
        for r in (await session.execute(by_category_q)).all()
    }

    by_culture_q = (
        select(SourceRecord.culture, func.count(SourceRecord.id))
        .where(SourceRecord.culture.isnot(None))
        .group_by(SourceRecord.culture)
        .order_by(func.count(SourceRecord.id).desc())
        .limit(20)
    )
    by_culture = {
        r[0]: r[1]
        for r in (await session.execute(by_culture_q)).all()
    }

    return CollectionStats(
        total_records=total_records,
        total_images=total_images,
        total_versions=total_versions,
        total_segments=total_segments,
        total_contexts=total_contexts,
        by_source=by_source,
        by_category=by_category,
        by_culture=by_culture,
    )


@router.get("", response_model=CollectionListResponse)
async def list_collection(
    trusted_source_id: uuid.UUID | None = Query(None),
    source_category: str | None = Query(None),
    culture: str | None = Query(None),
    search: str | None = Query(None),
    record_status: str | None = Query(None),
    has_images: bool | None = Query(None),
    sort_by: str = Query("newest", regex="^(newest|oldest|title|images)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    filters = []
    if trusted_source_id:
        filters.append(SourceRecord.trusted_source_id == trusted_source_id)
    if source_category:
        filters.append(SourceRecord.source_category == source_category)
    if culture:
        filters.append(SourceRecord.culture.ilike(f"%{culture}%"))
    if search:
        filters.append(SourceRecord.canonical_title.ilike(f"%{search}%"))
    if record_status:
        filters.append(SourceRecord.record_status == record_status)
    if has_images is True:
        filters.append(
            SourceRecord.raw_object_id.in_(
                select(ObjectImage.raw_object_id).distinct()
            )
        )
    elif has_images is False:
        filters.append(
            ~SourceRecord.raw_object_id.in_(
                select(ObjectImage.raw_object_id).distinct()
            )
        )

    count_q = select(func.count(SourceRecord.id))
    for f in filters:
        count_q = count_q.where(f)
    total = (await session.execute(count_q)).scalar() or 0

    img_count_subq = (
        select(func.count(ObjectImage.id))
        .where(ObjectImage.raw_object_id == SourceRecord.raw_object_id)
        .correlate(SourceRecord)
        .scalar_subquery()
    )

    query = select(SourceRecord)
    for f in filters:
        query = query.where(f)

    if sort_by == "images":
        query = query.order_by(img_count_subq.desc(), SourceRecord.created_at.desc())
    elif sort_by == "oldest":
        query = query.order_by(SourceRecord.created_at.asc())
    elif sort_by == "title":
        query = query.order_by(SourceRecord.canonical_title.asc())
    else:
        query = query.order_by(SourceRecord.created_at.desc())

    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    records = result.scalars().all()

    items = []
    for rec in records:
        source = await session.get(TrustedSource, rec.trusted_source_id)
        raw = await session.get(RawObject, rec.raw_object_id)

        img_q = (
            select(ObjectImage)
            .where(ObjectImage.raw_object_id == rec.raw_object_id)
            .order_by(ObjectImage.image_order)
            .limit(6)
        )
        img_result = await session.execute(img_q)
        images = [ImageSummary.model_validate(i) for i in img_result.scalars().all()]

        ver_q = select(SourceVersion).where(SourceVersion.source_record_id == rec.id)
        ver_result = await session.execute(ver_q)
        versions = [VersionSummary.model_validate(v) for v in ver_result.scalars().all()]

        date_q = select(SourceDate).where(SourceDate.source_record_id == rec.id)
        date_result = await session.execute(date_q)
        dates = [DateSummary.model_validate(d) for d in date_result.scalars().all()]

        seg_count = (await session.execute(
            select(func.count(Segment.id))
            .join(SourceVersion, Segment.source_version_id == SourceVersion.id)
            .where(SourceVersion.source_record_id == rec.id)
        )).scalar() or 0

        ctx_count = (await session.execute(
            select(func.count(ContextualStatement.id))
            .where(ContextualStatement.source_record_id == rec.id)
        )).scalar() or 0

        items.append(CollectionItem(
            id=rec.id,
            canonical_title=rec.canonical_title,
            source_category=rec.source_category.value,
            culture=rec.culture,
            language_family=rec.language_family,
            origin_place_name=rec.origin_place_name,
            repository_institution=rec.repository_institution,
            provenance_status=rec.provenance_status.value,
            record_status=rec.record_status.value,
            metadata_jsonb=rec.metadata_jsonb,
            created_at=rec.created_at,
            source_url=raw.source_url if raw else None,
            source_name=source.name if source else "Unknown",
            source_slug=source.slug if source else "",
            images=images,
            versions=versions,
            dates=dates,
            segment_count=seg_count,
            context_count=ctx_count,
        ))

    return CollectionListResponse(items=items, total=total)


@router.get("/images/{image_id}/file")
async def serve_image(
    image_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Proxy an image from R2 storage."""
    img = await session.get(ObjectImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    if not img.r2_key:
        raise HTTPException(status_code=404, detail="No R2 copy available")

    try:
        data = r2_client.download(img.r2_key)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch image from storage")

    content_type = img.content_type or "image/jpeg"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{record_id}", response_model=CollectionItemDetail)
async def get_collection_item(
    record_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    rec = await session.get(SourceRecord, record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")

    source = await session.get(TrustedSource, rec.trusted_source_id)
    raw = await session.get(RawObject, rec.raw_object_id)

    img_q = (
        select(ObjectImage)
        .where(ObjectImage.raw_object_id == rec.raw_object_id)
        .order_by(ObjectImage.image_order)
    )
    images = [ImageSummary.model_validate(i) for i in (await session.execute(img_q)).scalars().all()]

    ver_q = select(SourceVersion).where(SourceVersion.source_record_id == rec.id)
    versions = [VersionSummary.model_validate(v) for v in (await session.execute(ver_q)).scalars().all()]

    date_q = select(SourceDate).where(SourceDate.source_record_id == rec.id)
    dates = [DateSummary.model_validate(d) for d in (await session.execute(date_q)).scalars().all()]

    seg_q = (
        select(Segment)
        .join(SourceVersion, Segment.source_version_id == SourceVersion.id)
        .where(SourceVersion.source_record_id == rec.id)
        .order_by(Segment.segment_order)
    )
    segments = [SegmentSummary.model_validate(s) for s in (await session.execute(seg_q)).scalars().all()]

    ctx_q = (
        select(ContextualStatement)
        .where(ContextualStatement.source_record_id == rec.id)
        .order_by(ContextualStatement.created_at)
    )
    context_statements = [ContextSummary.model_validate(c) for c in (await session.execute(ctx_q)).scalars().all()]

    return CollectionItemDetail(
        id=rec.id,
        canonical_title=rec.canonical_title,
        source_category=rec.source_category.value,
        culture=rec.culture,
        language_family=rec.language_family,
        origin_place_name=rec.origin_place_name,
        repository_institution=rec.repository_institution,
        provenance_status=rec.provenance_status.value,
        record_status=rec.record_status.value,
        metadata_jsonb=rec.metadata_jsonb,
        created_at=rec.created_at,
        source_url=raw.source_url if raw else None,
        source_name=source.name if source else "Unknown",
        source_slug=source.slug if source else "",
        images=images,
        versions=versions,
        dates=dates,
        segment_count=len(segments),
        context_count=len(context_statements),
        segments=segments,
        context_statements=context_statements,
    )
