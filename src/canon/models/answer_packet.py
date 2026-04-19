from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.canon.models.base import Base, UUIDPrimaryKeyMixin
from src.canon.models.enums import AnswerMode


class AnswerPacket(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "answer_packets"

    query: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    answer_mode: Mapped[str] = mapped_column(
        ENUM(AnswerMode, name="answer_mode", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    answer_summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sources: Mapped[list[AnswerPacketSource]] = relationship(
        back_populates="answer_packet", foreign_keys="[AnswerPacketSource.answer_packet_id]",
    )
    contexts: Mapped[list[AnswerPacketContext]] = relationship(
        back_populates="answer_packet", foreign_keys="[AnswerPacketContext.answer_packet_id]",
    )


class AnswerPacketSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "answer_packet_sources"

    answer_packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_packets.id"), nullable=False, index=True,
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    answer_packet: Mapped[AnswerPacket] = relationship(back_populates="sources")


class AnswerPacketContext(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "answer_packet_context"

    answer_packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_packets.id"), nullable=False, index=True,
    )
    contextual_statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    answer_packet: Mapped[AnswerPacket] = relationship(back_populates="contexts")
