from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class IntakeAnalyzeRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=100)


class FieldConfidence(BaseModel):
    name: float = 0.0
    slug: float = 0.0
    domain: float = 1.0
    base_url: float = 1.0
    source_category: float = 0.0
    trust_tier: float = 0.0
    ingestion_method: float = 0.0
    parser_type: float = 0.0
    default_language: float = 0.0
    rate_limit_rpm: float = 0.0
    crawl_frequency_hours: float = 0.0
    license_notes: float = 0.0
    notes: float = 0.0


class SuggestedSource(BaseModel):
    name: str = ""
    slug: str = ""
    domain: str = ""
    base_url: str = ""
    source_category: str = "text_corpus"
    trust_tier: str = "secondary"
    ingestion_method: str = "html_scrape"
    parser_type: str = "museum_html_parser"
    priority: int = 100
    default_language: str = ""
    rate_limit_rpm: int = 30
    crawl_frequency_hours: int = 24
    license_notes: str = ""
    notes: str = ""
    is_secondary_source: bool = False


class DomainGroup(BaseModel):
    domain: str
    urls: list[str]
    suggested_source: SuggestedSource
    confidence: FieldConfidence
    evidence: list[str] = Field(default_factory=list)


class IntakeAnalyzeResponse(BaseModel):
    id: uuid.UUID
    groups: list[DomainGroup]
    status: str


class IntakeRunResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    submitted_urls_jsonb: dict
    grouped_domains_jsonb: dict | None
    status: str
    analysis_result_jsonb: dict | None
    error_log: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
