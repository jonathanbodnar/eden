from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin
from src.canon.models.enums import ThreadType


class CanonicalStoryThread(UUIDPrimaryKeyMixin, VersionedMixin, TimestampMixin, Base):
    __tablename__ = "canonical_story_threads"

    title: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    thread_type: Mapped[ThreadType] = mapped_column(
        ENUM(ThreadType, name="thread_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
