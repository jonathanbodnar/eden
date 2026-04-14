from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.canon.models.base import Base, UUIDPrimaryKeyMixin
from src.canon.models.enums import ChatRole


class ChatSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_sessions"

    chapter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        order_by="ChatMessage.created_at",
        foreign_keys="[ChatMessage.session_id]",
    )


class ChatMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(
        ENUM(ChatRole, name="chat_role", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer_packet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="messages")
