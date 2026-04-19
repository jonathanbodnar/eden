from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceProgressResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    trusted_source_id: uuid.UUID
    last_run_id: uuid.UUID | None
    discovered_count: int
    fetched_count: int
    normalized_count: int
    segmented_count: int
    embedded_count: int
    failed_count: int
    skipped_count: int
    total_bytes_stored: int
    last_successful_checkpoint: datetime | None
    last_updated_at: datetime


class SourceProgressWithName(SourceProgressResponse):
    source_name: str
    source_slug: str
    active: bool


class OverviewResponse(BaseModel):
    total_trusted_sources: int
    active_trusted_sources: int
    total_raw_objects: int
    total_source_records: int
    total_versions: int
    total_segments: int
    total_embeddings: int
    total_bytes_stored: int
    jobs_running: int
    jobs_queued: int
    jobs_failed: int


class SourceStageProgress(BaseModel):
    source_id: uuid.UUID
    source_name: str
    source_slug: str
    status: str
    current_run_type: str | None
    discovered_count: int
    fetched_count: int
    normalized_count: int
    segmented_count: int
    embedded_count: int
    failed_count: int
    total_bytes_stored: int
    last_checkpoint: datetime | None
    stages: list[StageDetail]


class StageDetail(BaseModel):
    stage: str
    processed: int
    total: int | None
    percent: float | None
    status: str


SourceStageProgress.model_rebuild()
