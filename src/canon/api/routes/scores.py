from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canon_score import CanonScore
from src.canon.schemas.canonical import ScoreResponse

router = APIRouter()


def _tier(score: float) -> str:
    if score > 0.7:
        return "core_canon"
    if score >= 0.4:
        return "canon_with_caution"
    return "branch"


@router.get("/", response_model=list[ScoreResponse])
async def list_scores(
    canonical_type: str | None = None,
    min_score: float | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    q = select(CanonScore).order_by(CanonScore.final_score.desc()).limit(limit)
    if canonical_type:
        q = q.where(CanonScore.canonical_type == canonical_type)
    if min_score is not None:
        q = q.where(CanonScore.final_score >= min_score)

    result = await session.execute(q)
    responses = []
    for s in result.scalars().all():
        resp = ScoreResponse.model_validate(s)
        resp.tier = _tier(s.final_score)
        responses.append(resp)
    return responses


@router.get("/{canonical_id}", response_model=ScoreResponse)
async def get_score(
    canonical_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = select(CanonScore).where(CanonScore.canonical_id == canonical_id)
    score = (await session.execute(q)).scalar_one_or_none()
    if not score:
        return ScoreResponse(
            id=uuid.uuid4(),
            canonical_type="unknown",
            canonical_id=canonical_id,
            age_score=0, corroboration_score=0,
            independence_score=0, ambiguity_score=0,
            final_score=0, tier="unscored",
        )
    resp = ScoreResponse.model_validate(score)
    resp.tier = _tier(score.final_score)
    return resp
