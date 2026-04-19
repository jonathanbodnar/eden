from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.enums import CanonicalType
from src.canon.api.routes.entity_images import get_entity_images
from src.canon.api.routes.actors import _get_linked_chapters, _get_source_excerpts
from src.canon.schemas.canonical import PlaceResponse, SupportLinkResponse

router = APIRouter()


@router.get("/", response_model=list[PlaceResponse])
async def list_places(
    place_type: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(CanonicalPlace)
        .where(CanonicalPlace.is_current.is_(True))
        .order_by(CanonicalPlace.canonical_name)
        .limit(limit)
        .offset(offset)
    )
    if place_type:
        q = q.where(CanonicalPlace.place_type == place_type)
    if search:
        q = q.where(CanonicalPlace.canonical_name.ilike(f"%{search}%"))
    result = await session.execute(q)
    return [PlaceResponse.model_validate(p) for p in result.scalars().all()]


@router.get("/{place_id}", response_model=dict)
async def get_place(place_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    place = await session.get(CanonicalPlace, place_id)
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")
    resp = PlaceResponse.model_validate(place).model_dump(mode="json")
    resp["images"] = (await get_entity_images(session, [place_id], limit=200)).get(place_id, [])
    resp["chapters"] = await _get_linked_chapters(session, place_id, "place")
    resp["source_excerpts"] = await _get_source_excerpts(session, place_id, CanonicalType.PLACE)
    return resp


@router.get("/{place_id}/support-links", response_model=list[SupportLinkResponse])
async def get_place_support_links(
    place_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    q = select(CanonSupportLink).where(
        CanonSupportLink.canonical_type == CanonicalType.PLACE,
        CanonSupportLink.canonical_id == place_id,
    )
    result = await session.execute(q)
    return [SupportLinkResponse.model_validate(sl) for sl in result.scalars().all()]
