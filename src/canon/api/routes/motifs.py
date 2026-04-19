from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.motif import Motif, MotifAssignment
from src.canon.schemas.canonical import MotifAssignmentResponse, MotifResponse

router = APIRouter()


@router.get("/", response_model=list[MotifResponse])
async def list_motifs(session: AsyncSession = Depends(get_session)):
    q = select(Motif).order_by(Motif.label)
    result = await session.execute(q)
    return [MotifResponse.model_validate(m) for m in result.scalars().all()]


@router.get("/{motif_id}/assignments", response_model=list[MotifAssignmentResponse])
async def list_motif_assignments(
    motif_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(MotifAssignment)
        .where(MotifAssignment.motif_id == motif_id)
        .order_by(MotifAssignment.confidence.desc())
        .limit(limit)
    )
    result = await session.execute(q)
    assignments = result.scalars().all()

    motif = await session.get(Motif, motif_id)
    motif_label = motif.label if motif else None

    responses = []
    for a in assignments:
        resp = MotifAssignmentResponse(
            id=a.id,
            motif_id=a.motif_id,
            motif_label=motif_label,
            target_type=a.target_type.value,
            target_id=a.target_id,
            confidence=a.confidence,
        )
        responses.append(resp)
    return responses
