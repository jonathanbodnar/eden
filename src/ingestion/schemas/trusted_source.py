from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.ingestion.models.enums import (
    IngestionMethod,
    ParserType,
    SourceCategory,
    TrustTier,
)


class TrustedSourceCreate(BaseModel):
    name: str = Field(..., max_length=512)
    slug: str = Field(..., max_length=256)
    domain: str = Field(..., max_length=512)
    base_url: str = Field(..., max_length=2048)
    source_category: SourceCategory
    trust_tier: TrustTier = TrustTier.SECONDARY
    ingestion_method: IngestionMethod
    parser_type: ParserType
    content_types_supported: list[str] | None = None
    robots_or_access_notes: str | None = None
    license_notes: str | None = None
    default_language: str | None = None
    active: bool = True
    priority: int = 100
    rate_limit_rpm: int | None = None
    crawl_frequency_hours: int | None = None
    notes: str | None = None
    is_secondary_source: bool = False


class TrustedSourceUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    base_url: str | None = None
    source_category: SourceCategory | None = None
    trust_tier: TrustTier | None = None
    ingestion_method: IngestionMethod | None = None
    parser_type: ParserType | None = None
    content_types_supported: list[str] | None = None
    robots_or_access_notes: str | None = None
    license_notes: str | None = None
    default_language: str | None = None
    active: bool | None = None
    priority: int | None = None
    rate_limit_rpm: int | None = None
    crawl_frequency_hours: int | None = None
    notes: str | None = None
    is_secondary_source: bool | None = None


class TrustedSourceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    domain: str
    base_url: str
    source_category: SourceCategory
    trust_tier: TrustTier
    ingestion_method: IngestionMethod
    parser_type: ParserType
    content_types_supported: list[str] | None
    robots_or_access_notes: str | None
    license_notes: str | None
    default_language: str | None
    active: bool
    priority: int
    rate_limit_rpm: int | None
    crawl_frequency_hours: int | None
    notes: str | None
    is_secondary_source: bool
    created_at: datetime
    updated_at: datetime


class TrustedSourceListResponse(BaseModel):
    items: list[TrustedSourceResponse]
    total: int
