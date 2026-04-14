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

    deps_q = select(CanonDependency).where(
        CanonDependency.parent_type == CanonicalType.CHAPTER,
        CanonDependency.parent_id.in_(chapter_ids),
    )
    deps = (await session.execute(deps_q)).scalars().all()

    actor_ids = list({d.child_id for d in deps if d.child_type == CanonicalType.ACTOR})
    event_ids = list({d.child_id for d in deps if d.child_type == CanonicalType.EVENT})
    place_ids = list({d.child_id for d in deps if d.child_type == CanonicalType.PLACE})

    img_count_q = select(func.count(ChapterImageSet.id)).where(
        ChapterImageSet.chapter_id.in_(chapter_ids)
    )
    total_images = (await session.execute(img_count_q)).scalar() or 0

    src_q = (
        select(ChapterSourceSet.source_record_id)
        .where(ChapterSourceSet.chapter_id.in_(chapter_ids))
        .distinct()
    )
    source_record_ids = [
        r[0] for r in (await session.execute(src_q)).all()
    ]

    culture_counts: dict[str, dict] = defaultdict(
        lambda: {"source_count": 0, "actor_count": 0, "event_count": 0, "place_count": 0, "image_count": 0}
    )

    if source_record_ids:
        culture_q = (
            select(SASourceRecord.culture, func.count(SASourceRecord.id))
            .where(SASourceRecord.id.in_(source_record_ids))
            .group_by(SASourceRecord.culture)
        )
        for culture_name, cnt in (await session.execute(culture_q)).all():
            key = culture_name or "Unknown"
            culture_counts[key]["source_count"] = cnt

    all_entity_ids = actor_ids + event_ids + place_ids
    if all_entity_ids:
        link_q = (
            select(CanonSupportLink)
            .where(CanonSupportLink.canonical_id.in_(all_entity_ids))
        )
        links = (await session.execute(link_q)).scalars().all()

        sr_ids_from_links = list({
            lk.archive_object_id for lk in links
            if lk.archive_object_type.value == "source_record"
        })
        if sr_ids_from_links:
            sr_culture_q = select(SASourceRecord.id, SASourceRecord.culture).where(
                SASourceRecord.id.in_(sr_ids_from_links)
            )
            sr_culture_map = {
                row[0]: row[1] or "Unknown"
                for row in (await session.execute(sr_culture_q)).all()
            }
        else:
            sr_culture_map = {}

        entity_culture: dict[uuid.UUID, str] = {}
        for lk in links:
            if lk.archive_object_type.value == "source_record" and lk.archive_object_id in sr_culture_map:
                entity_culture[lk.canonical_id] = sr_culture_map[lk.archive_object_id]

        for aid in actor_ids:
            c = entity_culture.get(aid, "Unknown")
            culture_counts[c]["actor_count"] += 1
        for eid in event_ids:
            c = entity_culture.get(eid, "Unknown")
            culture_counts[c]["event_count"] += 1
        for pid in place_ids:
            c = entity_culture.get(pid, "Unknown")
            culture_counts[c]["place_count"] += 1

    cultures = []
    for name, counts in sorted(culture_counts.items(), key=lambda x: x[1]["source_count"], reverse=True):
        total = counts["source_count"] + counts["actor_count"] + counts["event_count"] + counts["place_count"]
        cultures.append(CultureSummary(
            name=name,
            explorable=total >= EXPLORABLE_THRESHOLD,
            **counts,
        ))

    featured_raw = await get_epoch_images(
        session, chapter_ids, limit=20,
        time_start=epoch.time_start, time_end=epoch.time_end,
    )
    featured_images = [EntityImage(**img) for img in featured_raw]

    return EpochOverviewResponse(
        epoch=epoch_resp,
        cultures=cultures,
        total_sources=len(source_record_ids),
        total_actors=len(actor_ids),
        total_events=len(event_ids),
        total_places=len(place_ids),
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
    """Drill into a specific culture within an epoch."""
    epoch = await session.get(CanonicalEpoch, epoch_id)
    if not epoch:
        raise HTTPException(status_code=404, detail="Epoch not found")

    chapters_q = select(CanonicalChapter.id).where(
        CanonicalChapter.epoch_id == epoch_id,
        CanonicalChapter.is_current.is_(True),
    )
    chapter_ids = [
        r[0] for r in (await session.execute(chapters_q)).all()
    ]
    if not chapter_ids:
        return {"culture": culture_name, "actors": [], "events": [], "places": [], "sources": [], "images": []}

    culture_filter = SASourceRecord.culture == culture_name if culture_name != "Unknown" else SASourceRecord.culture.is_(None)

    deps_q = select(CanonDependency).where(
        CanonDependency.parent_type == CanonicalType.CHAPTER,
        CanonDependency.parent_id.in_(chapter_ids),
    )
    deps = (await session.execute(deps_q)).scalars().all()

    all_actor_ids = list({d.child_id for d in deps if d.child_type == CanonicalType.ACTOR})
    all_event_ids = list({d.child_id for d in deps if d.child_type == CanonicalType.EVENT})
    all_place_ids = list({d.child_id for d in deps if d.child_type == CanonicalType.PLACE})
    all_entity_ids = all_actor_ids + all_event_ids + all_place_ids

    culture_entity_ids: set = set()
    if all_entity_ids:
        link_q = select(CanonSupportLink.canonical_id).where(
            CanonSupportLink.canonical_id.in_(all_entity_ids),
            CanonSupportLink.archive_object_id.in_(
                select(SASourceRecord.id).where(culture_filter)
            ),
        )
        culture_entity_ids = {r[0] for r in (await session.execute(link_q)).all()}

    actors = []
    actor_ids = [a for a in all_actor_ids if a in culture_entity_ids]
    if actor_ids:
        aq = select(CanonicalActor).where(CanonicalActor.id.in_(actor_ids), CanonicalActor.is_current.is_(True))
        actors = [ActorResponse.model_validate(a) for a in (await session.execute(aq)).scalars().all()]

    events = []
    event_ids = [e for e in all_event_ids if e in culture_entity_ids]
    if event_ids:
        eq = select(CanonicalEvent).where(CanonicalEvent.id.in_(event_ids), CanonicalEvent.is_current.is_(True))
        events = [EventResponse.model_validate(e) for e in (await session.execute(eq)).scalars().all()]

    places = []
    place_ids = [p for p in all_place_ids if p in culture_entity_ids]
    if place_ids:
        pq = select(CanonicalPlace).where(CanonicalPlace.id.in_(place_ids), CanonicalPlace.is_current.is_(True))
        places = [PlaceResponse.model_validate(p) for p in (await session.execute(pq)).scalars().all()]

    chapter_src_q = (
        select(ChapterSourceSet)
        .where(
            ChapterSourceSet.chapter_id.in_(chapter_ids),
            ChapterSourceSet.source_record_id.in_(
                select(SASourceRecord.id).where(culture_filter)
            ),
        )
        .order_by(ChapterSourceSet.relevance_weight.desc())
        .limit(50)
    )
    sources_raw = (await session.execute(chapter_src_q)).scalars().all()
    sources = [
        {"id": str(s.id), "title": s.title, "excerpt": s.excerpt, "source_type": s.source_type, "relevance_weight": s.relevance_weight}
        for s in sources_raw
    ]

    img_q = (
        select(ChapterImageSet)
        .where(ChapterImageSet.chapter_id.in_(chapter_ids))
        .order_by(ChapterImageSet.display_order)
        .limit(20)
    )
    images_raw = (await session.execute(img_q)).scalars().all()
    images = [
        {"id": str(i.id), "image_url": i.image_url, "caption": i.caption, "image_type": i.image_type}
        for i in images_raw
    ]

    # If no chapter-linked images, discover directly by culture
    if not images and culture_name != "Unknown":
        direct_imgs = await discover_images_for_culture(session, culture_name, limit=20)
        images = [
            {"id": img["id"], "image_url": img["image_url"], "caption": img["caption"], "image_type": "artifact"}
            for img in direct_imgs
        ]

    all_entity_ids_for_images = actor_ids + event_ids + place_ids
    entity_image_map = await get_entity_images(session, all_entity_ids_for_images, limit=6)

    def enrich(entities, ids):
        result = []
        for e in entities:
            d = e.model_dump(mode="json")
            eid = uuid.UUID(d["id"])
            d["images"] = entity_image_map.get(eid, [])
            result.append(d)
        return result

    return {
        "culture": culture_name,
        "actors": enrich(actors, actor_ids),
        "events": enrich(events, event_ids),
        "places": enrich(places, place_ids),
        "sources": sources,
        "images": images,
    }
