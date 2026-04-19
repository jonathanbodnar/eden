from __future__ import annotations

import uuid

from sqlalchemy import Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrationPacket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narration_packets"

    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    intro_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_actor_ids_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    key_event_ids_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    key_place_ids_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
