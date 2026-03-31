from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import IngestionMethod, ParserType, SourceCategory, TrustTier


class TrustedSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trusted_sources"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    slug: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(512), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_category: Mapped[SourceCategory] = mapped_column(
        ENUM(SourceCategory, name="source_category", create_type=False),
        nullable=False,
    )
    trust_tier: Mapped[TrustTier] = mapped_column(
        ENUM(TrustTier, name="trust_tier", create_type=False),
        nullable=False,
        default=TrustTier.SECONDARY,
    )
    ingestion_method: Mapped[IngestionMethod] = mapped_column(
        ENUM(IngestionMethod, name="ingestion_method", create_type=False),
        nullable=False,
    )
    parser_type: Mapped[ParserType] = mapped_column(
        ENUM(ParserType, name="parser_type", create_type=False),
        nullable=False,
    )
    content_types_supported: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(128)), nullable=True
    )
    robots_or_access_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawl_frequency_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    discovered_records = relationship("DiscoveredRecord", back_populates="trusted_source")
    raw_objects = relationship("RawObject", back_populates="trusted_source")
    ingestion_jobs = relationship("IngestionJob", back_populates="trusted_source")
    source_runs = relationship("SourceRun", back_populates="trusted_source")
    queued_jobs = relationship("QueuedJob", back_populates="trusted_source")
    source_progress = relationship("SourceProgress", back_populates="trusted_source", uselist=False)
