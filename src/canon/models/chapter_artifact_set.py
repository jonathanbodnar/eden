from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChapterArtifactSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chapter_artifact_sets"

    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    raw_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    location: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    date_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
