from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.chapter_image_set import ChapterImageSet
from src.canon.models.chapter_source_set import ChapterSourceSet
from src.canon.models.enums import CanonicalType
from src.canon.models.system_a import SASourceRecord
from src.canon.api.routes.entity_images import (
    discover_images_for_culture,
    get_entity_images,
    get_epoch_images,
)
from src.canon.schemas.canonical import (
    ActorResponse,
    ChapterResponse,
    CultureSummary,
    EntityImage,
    EpochOverviewResponse,
    EpochResponse,
    EpochWithCountResponse,
    EventResponse,
    PlaceResponse,
)

router = APIRouter()

EXPLORABLE_THRESHOLD = 3


@router.get("/", response_model=list[EpochWithCountResponse])
async def list_epochs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(CanonicalEpoch)
        .where(CanonicalEpoch.is_current.is_(True))
        .order_by(CanonicalEpoch.epoch_order.asc())
        .limit(limit)
        .offset(offset)
    )
    epochs = (await session.execute(q)).scalars().all()

    results = []
    for epoch in epochs:
        count_q = select(func.count(CanonicalChapter.id)).where(
            CanonicalChapter.epoch_id == epoch.id,
            CanonicalChapter.is_current.is_(True),
        )
        chapter_count = (await session.execute(count_q)).scalar() or 0
        resp = EpochWithCountResponse(
            **EpochResponse.model_validate(epoch).model_dump(),
            chapter_count=chapter_count,
        )
        results.append(resp)

    return results


@router.get("/{epoch_id}", response_model=EpochWithCountResponse)
async def get_epoch(
    epoch_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    epoch = await session.get(CanonicalEpoch, epoch_id)
    if not epoch:
        raise HTTPException(status_code=404, detail="Epoch not found")

    count_q = select(func.count(CanonicalChapter.id)).where(
        CanonicalChapter.epoch_id == epoch.id,
        CanonicalChapter.is_current.is_(True),
    )
    chapter_count = (await session.execute(count_q)).scalar() or 0
    return EpochWithCountResponse(
        **EpochResponse.model_validate(epoch).model_dump(),
        chapter_count=chapter_count,
    )


@router.get("/{epoch_id}/overview", response_model=EpochOverviewResponse)
async def get_epoch_overview(
    epoch_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    epoch = await session.get(CanonicalEpoch, epoch_id)
    if not epoch:
        raise HTTPException(status_code=404, detail="Epoch not found")

    chapters_q = (
        select(CanonicalChapter)
        .where(
            CanonicalChapter.epoch_id == epoch_id,
            CanonicalChapter.is_current.is_(True),
        )
        .order_by(CanonicalChapter.chapter_order)
    )
    chapters = (await session.execute(chapters_q)).scalars().all()
    chapter_ids = [c.id for c in chapters]
    chapter_responses = [ChapterResponse.model_validate(c) for c in chapters]

    count_q = select(func.count(CanonicalChapter.id)).where(
        CanonicalChapter.epoch_id == epoch.id,
        CanonicalChapter.is_current.is_(True),
    )
    chapter_count = (await session.execute(count_q)).scalar() or 0
    epoch_resp = EpochWithCountResponse(
        **EpochResponse.model_validate(epoch).model_dump(),
        chapter_count=chapter_count,
    )

    if not chapter_ids:
        return EpochOverviewResponse(epoch=epoch_resp, chapters=chapter_responses)

    chapter_id_subq = (
        select(CanonicalChapter.id)
        .where(CanonicalChapter.epoch_id == epoch_id, CanonicalChapter.is_current.is_(True))
    ).scalar_subquery()

    img_count_q = select(func.count(ChapterImageSet.id)).where(
        ChapterImageSet.chapter_id.in_(select(CanonicalChapter.id).where(
            CanonicalChapter.epoch_id == epoch_id, CanonicalChapter.is_current.is_(True)
        ))
    )
    total_images = (await session.execute(img_count_q)).scalar() or 0

    culture_q = (
        select(SASourceRecord.culture, func.count(func.distinct(SASourceRecord.id)))
        .join(ChapterSourceSet, ChapterSourceSet.source_record_id == SASourceRecord.id)
        .where(ChapterSourceSet.chapter_id.in_(
            select(CanonicalChapter.id).where(
                CanonicalChapter.epoch_id == epoch_id, CanonicalChapter.is_current.is_(True)
            )
        ))
        .group_by(SASourceRecord.culture)
    )
    culture_counts: dict[str, dict] = defaultdict(
        lambda: {"source_count": 0, "actor_count": 0, "event_count": 0, "place_count": 0, "image_count": 0}
    )
    for culture_name, cnt in (await session.execute(culture_q)).all():
        key = culture_name or "Unknown"
        culture_counts[key]["source_count"] = cnt

    total_sources_q = select(func.count(func.distinct(ChapterSourceSet.source_record_id))).where(
        ChapterSourceSet.chapter_id.in_(
            select(CanonicalChapter.id).where(
                CanonicalChapter.epoch_id == epoch_id, CanonicalChapter.is_current.is_(True)
            )
        )
    )
    total_sources = (await session.execute(total_sources_q)).scalar() or 0

    from src.canon.models.chapter_focus_object import ChapterFocusObject
    focus_counts_q = (
        select(ChapterFocusObject.object_type, func.count(func.distinct(ChapterFocusObject.object_id)))
        .where(ChapterFocusObject.chapter_id.in_(
            select(CanonicalChapter.id).where(
                CanonicalChapter.epoch_id == epoch_id, CanonicalChapter.is_current.is_(True)
            )
        ))
        .group_by(ChapterFocusObject.object_type)
    )
    focus_counts = {row[0]: row[1] for row in (await session.execute(focus_counts_q)).all()}
    total_actors = focus_counts.get("actor", 0)
    total_events = focus_counts.get("event", 0)
    total_places = focus_counts.get("place", 0)

    cultures = []
    for name, counts in sorted(culture_counts.items(), key=lambda x: x[1]["source_count"], reverse=True):
        total = counts["source_count"] + counts["actor_count"] + counts["event_count"] + counts["place_count"]
        cultures.append(CultureSummary(
            name=name,
            explorable=total >= EXPLORABLE_THRESHOLD,
            **counts,
        ))

    featured_raw = await get_epoch_images(
        session, chapter_ids[:50], limit=20,
        time_start=epoch.time_start, time_end=epoch.time_end,
    )
    featured_images = [EntityImage(**img) for img in featured_raw]

    return EpochOverviewResponse(
        epoch=epoch_resp,
        cultures=cultures,
        total_sources=total_sources,
        total_actors=total_actors,
        total_events=total_events,
        total_places=total_places,
        total_images=total_images,
        featured_images=featured_images,
        chapters=chapter_responses,
    )


@router.get("/{epoch_id}/culture/{culture_name}", response_model=dict)
async def get_epoch_culture_detail(
    epoch_id: uuid.UUID,
    culture_name: str,
    session: AsyncSession = Depends(get_session),
):
    """Drill into a specific culture within an epoch. Uses raw SQL for performance."""
    epoch = await session.get(CanonicalEpoch, epoch_id)
    if not epoch:
        raise HTTPException(status_code=404, detail="Epoch not found")

    culture_filter_sql = "sr.culture = :culture" if culture_name != "Unknown" else "sr.culture IS NULL"

    actor_rows = (await session.execute(text(f"""
        SELECT DISTINCT a.id, a.canonical_name, a.actor_type, a.summary, a.time_start, a.time_end, a.merge_confidence
        FROM canonical_actors a
        JOIN canon_support_links csl ON csl.canonical_id = a.id AND csl.canonical_type = 'actor'
        JOIN source_records sr ON sr.id = csl.archive_object_id AND {culture_filter_sql}
        WHERE a.is_current = true
        ORDER BY a.canonical_name LIMIT 50
    """), {"culture": culture_name})).fetchall()

    actors = [{"id": str(r.id), "canonical_name": r.canonical_name, "actor_type": r.actor_type,
               "summary": r.summary, "time_start": r.time_start, "time_end": r.time_end,
               "merge_confidence": float(r.merge_confidence) if r.merge_confidence else None} for r in actor_rows]

    event_rows = (await session.execute(text(f"""
        SELECT DISTINCT e.id, e.canonical_name, e.event_type, e.summary, e.time_start, e.time_end, e.merge_confidence
        FROM canonical_events e
        JOIN canon_support_links csl ON csl.canonical_id = e.id AND csl.canonical_type = 'event'
        JOIN source_records sr ON sr.id = csl.archive_object_id AND {culture_filter_sql}
        WHERE e.is_current = true
        ORDER BY e.canonical_name LIMIT 50
    """), {"culture": culture_name})).fetchall()

    events = [{"id": str(r.id), "canonical_name": r.canonical_name, "event_type": r.event_type,
               "summary": r.summary, "time_start": r.time_start, "time_end": r.time_end,
               "merge_confidence": float(r.merge_confidence) if r.merge_confidence else None} for r in event_rows]

    place_rows = (await session.execute(text(f"""
        SELECT DISTINCT p.id, p.canonical_name, p.place_type, p.summary, p.time_start, p.time_end, p.merge_confidence
        FROM canonical_places p
        JOIN canon_support_links csl ON csl.canonical_id = p.id AND csl.canonical_type = 'place'
        JOIN source_records sr ON sr.id = csl.archive_object_id AND {culture_filter_sql}
        WHERE p.is_current = true
        ORDER BY p.canonical_name LIMIT 50
    """), {"culture": culture_name})).fetchall()

    places = [{"id": str(r.id), "canonical_name": r.canonical_name, "place_type": r.place_type,
               "summary": r.summary, "time_start": r.time_start, "time_end": r.time_end,
               "merge_confidence": float(r.merge_confidence) if r.merge_confidence else None} for r in place_rows]

    src_rows = (await session.execute(text(f"""
        SELECT css.id, css.title, css.relevance_weight, css.source_type,
               LEFT(sv.text_extracted, 500) as excerpt
        FROM chapter_source_sets css
        JOIN canonical_chapters ch ON ch.id = css.chapter_id AND ch.epoch_id = :epoch_id AND ch.is_current = true
        JOIN source_records sr ON sr.id = css.source_record_id AND {culture_filter_sql}
        LEFT JOIN LATERAL (
            SELECT text_extracted FROM source_versions WHERE source_record_id = sr.id AND text_extracted IS NOT NULL LIMIT 1
        ) sv ON true
        ORDER BY css.relevance_weight DESC LIMIT 30
    """), {"epoch_id": str(epoch_id), "culture": culture_name})).fetchall()

    sources = [{"id": str(r.id), "title": r.title, "excerpt": r.excerpt,
                "source_type": r.source_type, "relevance_weight": float(r.relevance_weight) if r.relevance_weight else None}
               for r in src_rows]

    img_rows = (await session.execute(text(f"""
        SELECT cis.id, cis.image_url, cis.caption, cis.image_type
        FROM chapter_image_sets cis
        JOIN canonical_chapters ch ON ch.id = cis.chapter_id AND ch.epoch_id = :epoch_id AND ch.is_current = true
        JOIN source_records sr ON sr.id = (
            SELECT css2.source_record_id FROM chapter_source_sets css2
            WHERE css2.chapter_id = cis.chapter_id LIMIT 1
        ) AND {culture_filter_sql}
        WHERE cis.image_url IS NOT NULL
        ORDER BY cis.display_order LIMIT 20
    """), {"epoch_id": str(epoch_id), "culture": culture_name})).fetchall()

    images = [{"id": str(r.id), "image_url": r.image_url, "caption": r.caption, "image_type": r.image_type}
              for r in img_rows]

    if not images and culture_name != "Unknown":
        direct_imgs = await discover_images_for_culture(session, culture_name, limit=20)
        images = [{"id": img["id"], "image_url": img["image_url"], "caption": img["caption"], "image_type": "artifact"}
                  for img in direct_imgs]

    for a in actors:
        a["images"] = []
    for e in events:
        e["images"] = []
    for p in places:
        p["images"] = []

    return {
        "culture": culture_name,
        "actors": actors,
        "events": events,
        "places": places,
        "sources": sources,
        "images": images,
    }
