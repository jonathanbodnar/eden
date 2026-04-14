from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.world_packet import WorldPacket
from src.canon.schemas.canonical import WorldPacketResponse

router = APIRouter()


@router.get("/{chapter_id}", response_model=WorldPacketResponse)
async def get_world_packet(
    chapter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(WorldPacket)
        .where(WorldPacket.chapter_id == chapter_id)
        .order_by(WorldPacket.packet_version.desc())
        .limit(1)
    )
    packet = (await session.execute(q)).scalar_one_or_none()
    if not packet:
        raise HTTPException(status_code=404, detail="World packet not found for this chapter")
    return WorldPacketResponse.model_validate(packet)


@router.get("/", response_model=list[WorldPacketResponse])
async def list_world_packets(
    session: AsyncSession = Depends(get_session),
):
    q = select(WorldPacket).order_by(WorldPacket.created_at.desc())
    result = await session.execute(q)
    return [WorldPacketResponse.model_validate(p) for p in result.scalars().all()]
