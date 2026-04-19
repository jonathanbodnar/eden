from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.narration_packet import NarrationPacket
from src.canon.schemas.canonical import NarrationPacketResponse

router = APIRouter()


@router.get("/{chapter_id}", response_model=NarrationPacketResponse)
async def get_narration_packet(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(NarrationPacket)
        .where(NarrationPacket.chapter_id == chapter_id)
        .order_by(NarrationPacket.version.desc())
        .limit(1)
    )
    packet = (await session.execute(q)).scalar_one_or_none()
    if not packet:
        raise HTTPException(status_code=404, detail="Narration packet not found for this chapter")
    return NarrationPacketResponse.model_validate(packet)


@router.get("/", response_model=list[NarrationPacketResponse])
async def list_narration_packets(
    session: AsyncSession = Depends(get_session),
):
    q = select(NarrationPacket).order_by(NarrationPacket.created_at.desc())
    result = await session.execute(q)
    return [NarrationPacketResponse.model_validate(p) for p in result.scalars().all()]
