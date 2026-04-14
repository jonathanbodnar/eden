from __future__ import annotations

import uuid

from sqlalchemy import Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChapterContextSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chapter_context_sets"

    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    contextual_statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
