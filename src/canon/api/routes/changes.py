from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.change_event import CanonUpdateTarget, ChangeEvent
from src.canon.schemas.canonical import ChangeEventResponse

router = APIRouter()


@router.get("/", response_model=list[ChangeEventResponse])
async def list_changes(
    change_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ChangeEvent)
        .order_by(ChangeEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if change_type:
        q = q.where(ChangeEvent.change_type == change_type)
    result = await session.execute(q)
    return [ChangeEventResponse.model_validate(e) for e in result.scalars().all()]


@router.get("/stats")
async def change_stats(session: AsyncSession = Depends(get_session)):
    total_events = (await session.execute(select(func.count(ChangeEvent.id)))).scalar() or 0
    total_targets = (await session.execute(select(func.count(CanonUpdateTarget.id)))).scalar() or 0
    pending_targets = (await session.execute(
        select(func.count(CanonUpdateTarget.id)).where(CanonUpdateTarget.status == "pending")
    )).scalar() or 0

    return {
        "total_change_events": total_events,
        "total_update_targets": total_targets,
        "pending_update_targets": pending_targets,
    }
