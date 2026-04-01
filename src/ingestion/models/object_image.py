from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin


class ObjectImage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "object_images"

    raw_object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_objects.id"), nullable=False, index=True
    )
    trusted_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trusted_sources.id"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    r2_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    raw_object = relationship("RawObject", back_populates="images")
    trusted_source = relationship("TrustedSource")
