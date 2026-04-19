from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.answer_packet import AnswerPacket, AnswerPacketContext, AnswerPacketSource
from src.canon.models.chat_session import ChatMessage, ChatSession
from src.canon.schemas.canonical import (
    AnswerPacketResponse,
    ChatMessageResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionDetailResponse,
    ChatSessionResponse,
)
from src.canon.services.chat_answer_builder import ChatAnswerBuilder

router = APIRouter()


@router.post("/query", response_model=ChatQueryResponse)
async def chat_query(
    request: ChatQueryRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = ChatAnswerBuilder()
    result = await svc.answer_query(
        session,
        query=request.query,
        chapter_id=request.chapter_id,
        epoch_id=request.epoch_id,
        session_id=request.session_id,
    )
    await session.commit()
    return ChatQueryResponse(**result)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    chapter_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(limit).offset(offset)
    if chapter_id:
        q = q.where(ChatSession.chapter_id == chapter_id)

    sessions = (await session.execute(q)).scalars().all()
    results = []
    for s in sessions:
        count_q = select(func.count(ChatMessage.id)).where(ChatMessage.session_id == s.id)
        msg_count = (await session.execute(count_q)).scalar() or 0
        resp = ChatSessionResponse.model_validate(s)
        resp.message_count = msg_count
        results.append(resp)
    return results


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    chat_session = await session.get(ChatSession, session_id)
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs_q = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    messages = (await session.execute(msgs_q)).scalars().all()

    count = len(messages)
    return ChatSessionDetailResponse(
        **ChatSessionResponse.model_validate(chat_session).model_dump(),
        message_count=count,
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
    )


@router.get("/answer-packets/{packet_id}", response_model=AnswerPacketResponse)
async def get_answer_packet(
    packet_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(AnswerPacket, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Answer packet not found")

    srcs_q = select(AnswerPacketSource).where(AnswerPacketSource.answer_packet_id == packet_id)
    srcs = (await session.execute(srcs_q)).scalars().all()

    ctxs_q = select(AnswerPacketContext).where(AnswerPacketContext.answer_packet_id == packet_id)
    ctxs = (await session.execute(ctxs_q)).scalars().all()

    return AnswerPacketResponse(
        id=packet.id,
        query=packet.query,
        chapter_id=packet.chapter_id,
        answer_mode=packet.answer_mode,
        answer_summary=packet.answer_summary,
        confidence=packet.confidence,
        created_at=packet.created_at,
        sources=[
            {
                "id": str(s.id),
                "source_record_id": str(s.source_record_id),
                "excerpt": s.excerpt,
                "support_type": s.support_type,
                "weight": s.weight,
            }
            for s in srcs
        ],
        contexts=[
            {
                "id": str(c.id),
                "contextual_statement_id": str(c.contextual_statement_id),
                "summary": c.summary,
                "weight": c.weight,
            }
            for c in ctxs
        ],
    )
