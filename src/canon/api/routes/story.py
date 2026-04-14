"""Story Mode API routes — serves the unified narrative for the frontend."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.image_generation_job import ImageGenerationJob
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.system_a import SASourceRecord, SASourceVersion, SAObjectImage, SASegment

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/epochs")
async def get_story_epochs(session: AsyncSession = Depends(get_session)):
    """Get all epochs with story chapter counts for book navigation."""
    q = select(CanonicalEpoch).where(
        CanonicalEpoch.is_current.is_(True)
    ).order_by(CanonicalEpoch.epoch_order)
    epochs = (await session.execute(q)).scalars().all()

    result = []
    for e in epochs:
        ch_count = (await session.execute(
            select(func.count(StoryChapter.id)).where(StoryChapter.epoch_id == e.id)
        )).scalar() or 0

        result.append({
            "id": str(e.id),
            "title": e.title,
            "epoch_order": e.epoch_order,
            "time_start": e.time_start,
            "time_end": e.time_end,
            "summary": e.summary,
            "chapter_count": ch_count,
        })
    return result


@router.get("/chapters")
async def get_story_chapters(session: AsyncSession = Depends(get_session)):
    """Get all story chapters in order."""
    q = (
        select(StoryChapter, CanonicalChapter, CanonicalEpoch)
        .join(CanonicalChapter, CanonicalChapter.id == StoryChapter.chapter_id)
        .join(CanonicalEpoch, CanonicalEpoch.id == StoryChapter.epoch_id)
        .order_by(CanonicalEpoch.epoch_order, CanonicalChapter.chapter_order)
    )
    rows = (await session.execute(q)).all()

    result = []
    for sc, ch, ep in rows:
        images = await _get_chapter_images(session, sc.id)
        result.append({
            "id": str(sc.id),
            "chapter_id": str(sc.chapter_id),
            "epoch_id": str(sc.epoch_id),
            "epoch_title": ep.title,
            "chapter_title": ch.title,
            "narrative_text": sc.narrative_text,
            "claims": sc.claims_json or [],
            "images": images,
            "word_count": sc.word_count,
            "time_start": ch.time_start,
            "time_end": ch.time_end,
            "synthesis_version": sc.synthesis_version,
        })
    return result


@router.get("/chapters/{story_chapter_id}")
async def get_story_chapter(story_chapter_id: str, session: AsyncSession = Depends(get_session)):
    """Get a single story chapter with full narrative and evidence."""
    import uuid
    sc = await session.get(StoryChapter, uuid.UUID(story_chapter_id))
    if not sc:
        from fastapi import HTTPException
        raise HTTPException(404, "Story chapter not found")

    ch = await session.get(CanonicalChapter, sc.chapter_id)
    ep = await session.get(CanonicalEpoch, sc.epoch_id)
    images = await _get_chapter_images(session, sc.id)

    return {
        "id": str(sc.id),
        "chapter_id": str(sc.chapter_id),
        "epoch_id": str(sc.epoch_id),
        "epoch_title": ep.title if ep else "",
        "chapter_title": ch.title if ch else "",
        "narrative_text": sc.narrative_text,
        "claims": sc.claims_json or [],
        "images": images,
        "word_count": sc.word_count,
        "time_start": ch.time_start if ch else None,
        "time_end": ch.time_end if ch else None,
        "synthesis_version": sc.synthesis_version,
    }


@router.get("/chapters/{story_chapter_id}/evidence")
async def get_story_chapter_evidence(
    story_chapter_id: str, session: AsyncSession = Depends(get_session)
):
    """Get source evidence supporting a story chapter."""
    import uuid
    sc = await session.get(StoryChapter, uuid.UUID(story_chapter_id))
    if not sc:
        return []

    claims = sc.claims_json or []
    source_ids = set()
    for claim in claims:
        for sid in claim.get("source_ids", []):
            source_ids.add(sid)

    if not source_ids:
        return []

    evidence = []
    for sid in list(source_ids)[:30]:
        try:
            sr = await session.get(SASourceRecord, uuid.UUID(sid))
            if not sr:
                continue

            sv_q = select(SASourceVersion.text_extracted).where(
                SASourceVersion.source_record_id == sr.id
            ).limit(1)
            sv_row = (await session.execute(sv_q)).first()
            excerpt = sv_row[0][:600] if sv_row and sv_row[0] else ""

            evidence.append({
                "source_id": str(sr.id),
                "title": sr.canonical_title,
                "culture": sr.culture,
                "category": sr.source_category,
                "excerpt": excerpt,
                "origin_place": sr.origin_place_name,
            })
        except Exception:
            continue

    return evidence


@router.get("/stats")
async def get_story_stats(session: AsyncSession = Depends(get_session)):
    """Get comprehensive stats for the About page."""
    source_records = (await session.execute(
        select(func.count(SASourceRecord.id))
    )).scalar() or 0

    images = (await session.execute(
        select(func.count(SAObjectImage.id))
    )).scalar() or 0

    cultures = (await session.execute(
        select(func.count(distinct(SASourceRecord.culture))).where(
            SASourceRecord.culture.isnot(None), SASourceRecord.culture != ""
        )
    )).scalar() or 0

    languages = (await session.execute(
        select(func.count(distinct(SASourceVersion.language))).where(
            SASourceVersion.language.isnot(None), SASourceVersion.language != ""
        )
    )).scalar() or 0

    segments = (await session.execute(
        select(func.count(SASegment.id))
    )).scalar() or 0

    story_chapters = (await session.execute(
        select(func.count(StoryChapter.id))
    )).scalar() or 0

    total_words = (await session.execute(
        select(func.sum(StoryChapter.word_count))
    )).scalar() or 0

    epochs = (await session.execute(
        select(func.count(CanonicalEpoch.id)).where(CanonicalEpoch.is_current.is_(True))
    )).scalar() or 0

    actors = (await session.execute(
        select(func.count(CanonicalActor.id)).where(CanonicalActor.is_current.is_(True))
    )).scalar() or 0

    events = (await session.execute(
        select(func.count(CanonicalEvent.id)).where(CanonicalEvent.is_current.is_(True))
    )).scalar() or 0

    places = (await session.execute(
        select(func.count(CanonicalPlace.id)).where(CanonicalPlace.is_current.is_(True))
    )).scalar() or 0

    return {
        "total_source_records": source_records,
        "total_images": images,
        "total_cultures": cultures,
        "total_languages": languages,
        "total_segments": segments,
        "total_story_chapters": story_chapters,
        "total_words": total_words,
        "total_epochs": epochs,
        "total_canonical_actors": actors,
        "total_canonical_events": events,
        "total_canonical_places": places,
    }


async def _get_chapter_images(session: AsyncSession, story_chapter_id) -> list[dict]:
    """Get completed generated images for a story chapter."""
    q = select(ImageGenerationJob).where(
        ImageGenerationJob.story_chapter_id == story_chapter_id,
        ImageGenerationJob.status == "completed",
    ).order_by(ImageGenerationJob.created_at)
    jobs = (await session.execute(q)).scalars().all()
    return [
        {
            "url": j.result_url or "",
            "caption": j.prompt_text[:150] if j.prompt_text else "",
            "prompt": j.prompt_text,
        }
        for j in jobs
    ]
