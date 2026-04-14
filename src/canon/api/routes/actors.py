from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.chapter_focus_object import ChapterFocusObject
from src.canon.models.enums import CanonicalType
from src.canon.models.system_a import SASourceRecord, SASourceVersion, SASourceDate
from src.canon.api.routes.entity_images import get_entity_images
from src.canon.schemas.canonical import ActorResponse, SupportLinkResponse

router = APIRouter()


@router.get("/", response_model=list[ActorResponse])
async def list_actors(
    actor_type: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(CanonicalActor)
        .where(CanonicalActor.is_current.is_(True))
        .order_by(CanonicalActor.canonical_name)
        .limit(limit)
        .offset(offset)
    )
    if actor_type:
        q = q.where(CanonicalActor.actor_type == actor_type)
    if search:
        q = q.where(CanonicalActor.canonical_name.ilike(f"%{search}%"))
    result = await session.execute(q)
    return [ActorResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/{actor_id}", response_model=dict)
async def get_actor(actor_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    actor = await session.get(CanonicalActor, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")
    resp = ActorResponse.model_validate(actor).model_dump(mode="json")
    resp["images"] = (await get_entity_images(session, [actor_id], limit=200)).get(actor_id, [])
    resp["chapters"] = await _get_linked_chapters(session, actor_id, "actor")
    resp["source_excerpts"] = await _get_source_excerpts(session, actor_id, CanonicalType.ACTOR)
    return resp


@router.get("/{actor_id}/support-links", response_model=list[SupportLinkResponse])
async def get_actor_support_links(
    actor_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    q = select(CanonSupportLink).where(
        CanonSupportLink.canonical_type == CanonicalType.ACTOR,
        CanonSupportLink.canonical_id == actor_id,
    )
    result = await session.execute(q)
    return [SupportLinkResponse.model_validate(sl) for sl in result.scalars().all()]


async def _get_linked_chapters(session: AsyncSession, entity_id: uuid.UUID, obj_type: str):
    q = (
        select(ChapterFocusObject)
        .where(ChapterFocusObject.object_id == entity_id, ChapterFocusObject.object_type == obj_type)
        .order_by(ChapterFocusObject.display_order)
        .limit(20)
    )
    focus_rows = (await session.execute(q)).scalars().all()
    chapters = []
    for fo in focus_rows:
        ch = await session.get(CanonicalChapter, fo.chapter_id)
        if ch and ch.is_current:
            chapters.append({
                "id": str(ch.id),
                "title": ch.title,
                "time_start": ch.time_start,
                "time_end": ch.time_end,
                "focus_reason": fo.focus_reason,
            })
    return chapters


async def _get_source_excerpts(session: AsyncSession, entity_id: uuid.UUID, canon_type: CanonicalType):
    links_q = (
        select(CanonSupportLink)
        .where(CanonSupportLink.canonical_type == canon_type, CanonSupportLink.canonical_id == entity_id)
        .order_by(CanonSupportLink.weight.desc())
        .limit(10)
    )
    links = (await session.execute(links_q)).scalars().all()
    excerpts = []
    seen_records: set[uuid.UUID] = set()
    for link in links:
        if str(link.archive_object_type) not in ("source_record", "ArchiveObjectType.SOURCE_RECORD"):
            continue
        sr = await session.get(SASourceRecord, link.archive_object_id)
        if not sr or sr.id in seen_records:
            continue
        seen_records.add(sr.id)
        text = ""
        ver_q = (
            select(SASourceVersion)
            .where(SASourceVersion.source_record_id == sr.id, SASourceVersion.text_extracted.isnot(None))
            .limit(1)
        )
        ver = (await session.execute(ver_q)).scalar_one_or_none()
        if ver and ver.text_extracted:
            text = ver.text_extracted[:600]
        dates_q = select(SASourceDate).where(SASourceDate.source_record_id == sr.id)
        dates = (await session.execute(dates_q)).scalars().all()
        excerpts.append({
            "source_record_id": str(sr.id),
            "title": sr.canonical_title,
            "culture": sr.culture,
            "category": sr.source_category,
            "excerpt": text,
            "support_type": str(link.support_type),
            "weight": link.weight,
            "dates": [{"date_type": d.date_type, "date_start": d.date_start, "date_end": d.date_end, "date_label": d.date_label} for d in dates],
        })
    return excerpts
