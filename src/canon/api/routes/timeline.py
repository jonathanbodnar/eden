from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, union_all, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.schemas.canonical import TimelineEntry, TimelineResponse

router = APIRouter()


@router.get("/", response_model=TimelineResponse)
async def get_timeline(
    time_start: int | None = None,
    time_end: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    entries: list[TimelineEntry] = []

    actors_q = select(CanonicalActor).where(CanonicalActor.is_current.is_(True))
    if time_start is not None:
        actors_q = actors_q.where(CanonicalActor.time_end >= time_start)
    if time_end is not None:
        actors_q = actors_q.where(CanonicalActor.time_start <= time_end)

    for a in (await session.execute(actors_q)).scalars().all():
        entries.append(TimelineEntry(
            id=a.id,
            canonical_type="actor",
            name=a.canonical_name,
            time_start=a.time_start,
            time_end=a.time_end,
            summary=a.summary,
        ))

    events_q = select(CanonicalEvent).where(CanonicalEvent.is_current.is_(True))
    if time_start is not None:
        events_q = events_q.where(CanonicalEvent.time_end >= time_start)
    if time_end is not None:
        events_q = events_q.where(CanonicalEvent.time_start <= time_end)

    for e in (await session.execute(events_q)).scalars().all():
        entries.append(TimelineEntry(
            id=e.id,
            canonical_type="event",
            name=e.canonical_name,
            time_start=e.time_start,
            time_end=e.time_end,
            summary=e.summary,
        ))

    places_q = select(CanonicalPlace).where(CanonicalPlace.is_current.is_(True))
    if time_start is not None:
        places_q = places_q.where(CanonicalPlace.time_end >= time_start)
    if time_end is not None:
        places_q = places_q.where(CanonicalPlace.time_start <= time_end)

    for p in (await session.execute(places_q)).scalars().all():
        entries.append(TimelineEntry(
            id=p.id,
            canonical_type="place",
            name=p.canonical_name,
            time_start=p.time_start,
            time_end=p.time_end,
            summary=p.summary,
        ))

    entries.sort(key=lambda e: e.time_start if e.time_start is not None else 999999)
    total = len(entries)
    entries = entries[:limit]

    return TimelineResponse(entries=entries, total=total)
