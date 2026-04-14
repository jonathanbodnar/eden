from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorldPacket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "world_packets"

    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    canon_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    packet_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    world_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment_profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    material_culture_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    symbol_system_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    motifs_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    key_actors_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    key_places_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    key_events_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    hard_constraints_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    soft_constraints_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reference_image_ids_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_panel_ids_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    consistency_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
