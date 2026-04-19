from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.ingestion.models.enums import (
    CopyrightStatus,
    DatingConfidence,
    DateType,
    DiscoveredRecordStatus,
    ProvenanceStatus,
    RecordStatus,
    ReviewStatus,
    SegmentType,
    SourceCategory,
    VersionType,
)


class RawObjectResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    trusted_source_id: uuid.UUID
    discovered_record_id: uuid.UUID | None
    external_id: str
    source_url: str
    content_type: str | None
    checksum: str
    byte_size: int
    r2_key: str
    fetched_at: datetime
    http_status: int | None
    raw_metadata_jsonb: dict | None
    parser_hint: str | None


class DiscoveredRecordResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    trusted_source_id: uuid.UUID
    external_id: str
    record_url: str
    title_hint: str | None
    discovered_at: datetime
    last_seen_at: datetime
    discovery_metadata_jsonb: dict | None
    status: DiscoveredRecordStatus


class SourceRecordResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    raw_object_id: uuid.UUID
    canonical_title: str
    source_category: SourceCategory
    culture: str | None
    language_family: str | None
    origin_place_name: str | None
    repository_institution: str | None
    provenance_status: ProvenanceStatus
    authenticity_notes: str | None
    rights_notes: str | None
    record_status: RecordStatus
    metadata_jsonb: dict | None
    created_at: datetime
    updated_at: datetime


class SourceDateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_record_id: uuid.UUID
    date_type: DateType
    date_start: int | None
    date_end: int | None
    date_label: str | None
    dating_method: str | None
    dating_confidence: DatingConfidence
    source_note: str | None


class SourceVersionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_record_id: uuid.UUID
    version_type: VersionType
    language: str | None
    translator_editor: str | None
    publication_year: int | None
    publisher: str | None
    edition_title: str | None
    license_notes: str | None
    copyright_status: CopyrightStatus
    is_preferred: bool
    quality_score: float | None
    r2_key: str | None
    metadata_jsonb: dict | None
    created_at: datetime
    updated_at: datetime


class SegmentResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_version_id: uuid.UUID
    segment_type: SegmentType
    segment_order: int
    citation_ref: str | None
    original_text: str | None
    normalized_text: str | None
    metadata_jsonb: dict | None
    review_status: ReviewStatus


class ProvenanceChainResponse(BaseModel):
    trusted_source: dict
    discovered_record: dict | None
    raw_object: dict
    source_record: dict
    source_dates: list[dict]
    source_versions: list[dict]
    segments: list[dict]
    embedding_count: int
