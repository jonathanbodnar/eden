from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.config import settings
from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin


class Embedding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "embeddings"

    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id"), nullable=False, index=True
    )
    embedding = mapped_column(Vector(settings.embedding_dimensions), nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(256), nullable=False, default=settings.embedding_model
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    segment = relationship("Segment", back_populates="embeddings")
