from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChapterImageSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chapter_image_sets"

    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    object_image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
