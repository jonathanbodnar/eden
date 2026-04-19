from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.ingestion.models.enums import (
    ContextType,
    ExtractionMethod,
    ReviewStatus,
    StatementConfidence,
)


class ContextualStatementCreate(BaseModel):
    source_record_id: uuid.UUID
    source_version_id: uuid.UUID | None = None
    segment_id: uuid.UUID | None = None
    raw_object_id: uuid.UUID | None = None
    statement_text: str = Field(..., min_length=1)
    context_type: ContextType
    confidence: StatementConfidence = StatementConfidence.MEDIUM
    extraction_method: ExtractionMethod = ExtractionMethod.MANUAL
    classifier_model: str | None = None
    classifier_version: str | None = None
    source_reference: str | None = None
    supporting_quote: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    notes_jsonb: dict | None = None


class ContextualStatementUpdate(BaseModel):
    review_status: ReviewStatus | None = None
    notes_jsonb: dict | None = None
    context_type: ContextType | None = None
    confidence: StatementConfidence | None = None
    statement_text: str | None = None


class ContextualStatementResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_record_id: uuid.UUID
    source_version_id: uuid.UUID | None
    segment_id: uuid.UUID | None
    raw_object_id: uuid.UUID | None
    statement_text: str
    context_type: ContextType
    confidence: StatementConfidence
    extraction_method: ExtractionMethod
    classifier_model: str | None
    classifier_version: str | None
    source_reference: str | None
    supporting_quote: str | None
    review_status: ReviewStatus
    notes_jsonb: dict | None
    created_at: datetime
    updated_at: datetime


class ContextualStatementListResponse(BaseModel):
    items: list[ContextualStatementResponse]
    total: int


class ReviewBatchRequest(BaseModel):
    ids: list[uuid.UUID] = Field(..., min_length=1)
    review_status: ReviewStatus


class ContextStats(BaseModel):
    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_confidence: dict[str, int] = Field(default_factory=dict)
    by_review_status: dict[str, int] = Field(default_factory=dict)
    by_extraction_method: dict[str, int] = Field(default_factory=dict)
