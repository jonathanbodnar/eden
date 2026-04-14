from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.enums import CanonicalType
from src.canon.models.chapter_artifact_set import ChapterArtifactSet
from src.canon.models.chapter_context_set import ChapterContextSet
from src.canon.models.chapter_focus_object import ChapterFocusObject
from src.canon.models.chapter_image_set import ChapterImageSet
from src.canon.models.chapter_source_set import ChapterSourceSet
from src.canon.models.system_a import (
    SAObjectImage, SARawObject, SASourceDate, SASourceRecord,
    SASourceVersion, SATrustedSource,
)
from src.canon.schemas.canonical import (
    ActorResponse,
    ChapterArtifactSetResponse,
    ChapterContextSetResponse,
    ChapterDetailResponse,
    ChapterFocusObjectResponse,
    ChapterImageSetResponse,
    ChapterResponse,
    ChapterSourceSetResponse,
    EventResponse,
    PlaceResponse,
)

router = APIRouter()


@router.get("/", response_model=list[ChapterResponse])
async def list_chapters(
    epoch_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(CanonicalChapter)
        .where(CanonicalChapter.is_current.is_(True))
        .order_by(CanonicalChapter.chapter_order)
        .limit(limit)
        .offset(offset)
    )
    if epoch_id:
        q = q.where(CanonicalChapter.epoch_id == epoch_id)
    result = await session.execute(q)
    return [ChapterResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    chapter = await session.get(CanonicalChapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    deps_q = select(CanonDependency).where(
        CanonDependency.parent_type == CanonicalType.CHAPTER,
        CanonDependency.parent_id == chapter_id,
    )
    deps = (await session.execute(deps_q)).scalars().all()

    actor_ids = [d.child_id for d in deps if d.child_type == CanonicalType.ACTOR]
    event_ids = [d.child_id for d in deps if d.child_type == CanonicalType.EVENT]
    place_ids = [d.child_id for d in deps if d.child_type == CanonicalType.PLACE]

    actors = []
    if actor_ids:
        aq = select(CanonicalActor).where(CanonicalActor.id.in_(actor_ids))
        actors = [ActorResponse.model_validate(a) for a in (await session.execute(aq)).scalars().all()]

    events = []
    if event_ids:
        eq = select(CanonicalEvent).where(CanonicalEvent.id.in_(event_ids))
        events = [EventResponse.model_validate(e) for e in (await session.execute(eq)).scalars().all()]

    places = []
    if place_ids:
        pq = select(CanonicalPlace).where(CanonicalPlace.id.in_(place_ids))
        places = [PlaceResponse.model_validate(p) for p in (await session.execute(pq)).scalars().all()]

    return ChapterDetailResponse(
        **ChapterResponse.model_validate(chapter).model_dump(),
        actors=actors,
        events=events,
        places=places,
    )


@router.get("/{chapter_id}/sources", response_model=list[ChapterSourceSetResponse])
async def get_chapter_sources(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ChapterSourceSet)
        .where(ChapterSourceSet.chapter_id == chapter_id)
        .order_by(ChapterSourceSet.relevance_weight.desc())
    )
    return [ChapterSourceSetResponse.model_validate(r) for r in (await session.execute(q)).scalars().all()]


@router.get("/{chapter_id}/context", response_model=list[ChapterContextSetResponse])
async def get_chapter_context(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ChapterContextSet)
        .where(ChapterContextSet.chapter_id == chapter_id)
        .order_by(ChapterContextSet.relevance_weight.desc())
    )
    return [ChapterContextSetResponse.model_validate(r) for r in (await session.execute(q)).scalars().all()]


@router.get("/{chapter_id}/artifacts", response_model=list[ChapterArtifactSetResponse])
async def get_chapter_artifacts(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = select(ChapterArtifactSet).where(ChapterArtifactSet.chapter_id == chapter_id)
    return [ChapterArtifactSetResponse.model_validate(r) for r in (await session.execute(q)).scalars().all()]


@router.get("/{chapter_id}/images", response_model=list[ChapterImageSetResponse])
async def get_chapter_images(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ChapterImageSet)
        .where(ChapterImageSet.chapter_id == chapter_id)
        .order_by(ChapterImageSet.display_order)
    )
    return [ChapterImageSetResponse.model_validate(r) for r in (await session.execute(q)).scalars().all()]


@router.get("/{chapter_id}/focus-objects", response_model=list[ChapterFocusObjectResponse])
async def get_chapter_focus_objects(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ChapterFocusObject)
        .where(ChapterFocusObject.chapter_id == chapter_id)
        .order_by(ChapterFocusObject.display_order)
    )
    return [ChapterFocusObjectResponse.model_validate(r) for r in (await session.execute(q)).scalars().all()]


@router.get("/images/{image_id}/record")
async def get_image_record_detail(
    image_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get full source record details for a chapter image (for the modal)."""
    img_row = (await session.execute(
        select(ChapterImageSet).where(ChapterImageSet.id == image_id)
    )).scalar_one_or_none()
    if not img_row:
        raise HTTPException(404, "Image not found")

    result: dict = {
        "id": str(img_row.id),
        "image_url": img_row.image_url,
        "caption": img_row.caption,
        "image_type": img_row.image_type,
    }

    if not img_row.object_image_id:
        return result

    obj_img = (await session.execute(
        select(SAObjectImage).where(SAObjectImage.id == img_row.object_image_id)
    )).scalar_one_or_none()
    if not obj_img:
        return result

    result["original_image_url"] = obj_img.image_url
    result["alt_text"] = obj_img.alt_text
    result["original_caption"] = obj_img.caption

    raw_obj = (await session.execute(
        select(SARawObject).where(SARawObject.id == obj_img.raw_object_id)
    )).scalar_one_or_none()

    if raw_obj:
        result["external_id"] = raw_obj.external_id
        result["source_url"] = raw_obj.source_url
        result["content_type"] = raw_obj.content_type

        sr = (await session.execute(
            select(SASourceRecord).where(SASourceRecord.raw_object_id == raw_obj.id)
        )).scalar_one_or_none()

        if sr:
            result["record_title"] = sr.canonical_title
            result["source_category"] = sr.source_category
            result["culture"] = sr.culture
            result["language_family"] = sr.language_family
            result["origin_place_name"] = sr.origin_place_name
            result["provenance_status"] = sr.provenance_status
            result["metadata"] = sr.metadata_jsonb

            ts = (await session.execute(
                select(SATrustedSource).where(SATrustedSource.id == sr.trusted_source_id)
            )).scalar_one_or_none()
            if ts:
                result["trusted_source_name"] = ts.name
                result["trust_tier"] = ts.trust_tier

            dates = (await session.execute(
                select(SASourceDate).where(SASourceDate.source_record_id == sr.id)
            )).scalars().all()
            if dates:
                result["dates"] = [
                    {
                        "date_type": d.date_type,
                        "date_start": d.date_start,
                        "date_end": d.date_end,
                        "date_label": d.date_label,
                        "dating_confidence": d.dating_confidence,
                    }
                    for d in dates
                ]

            version = (await session.execute(
                select(SASourceVersion).where(SASourceVersion.source_record_id == sr.id).limit(1)
            )).scalar_one_or_none()
            if version:
                text = version.text_extracted or ""
                result["text_excerpt"] = text[:2000] if len(text) > 2000 else text

    return result
