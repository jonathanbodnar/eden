from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.ingestion.models.enums import (
    JobStatus,
    JobType,
    RunStatus,
    RunType,
)


class EnqueueJobRequest(BaseModel):
    trusted_source_id: uuid.UUID
    job_type: JobType
    priority: int = 100
    payload: dict | None = None


class RunSourceRequest(BaseModel):
    run_type: RunType = RunType.FULL_INGEST
    requested_by: str | None = None
    notes: str | None = None
    parallelism: int = 1
    skip_stages: list[str] | None = None


class QueuedJobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_run_id: uuid.UUID | None
    trusted_source_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    priority: int
    scheduled_for: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    worker_id: str | None
    attempt_count: int
    max_attempts: int
    payload_jsonb: dict | None
    error_log: str | None
    last_heartbeat_at: datetime | None
    created_at: datetime


class QueuedJobListResponse(BaseModel):
    items: list[QueuedJobResponse]
    total: int


class SourceRunResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    trusted_source_id: uuid.UUID
    run_type: RunType
    status: RunStatus
    started_at: datetime | None
    completed_at: datetime | None
    paused_at: datetime | None
    last_heartbeat_at: datetime | None
    requested_by: str | None
    notes: str | None
    created_at: datetime


class JobCheckpointResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    queued_job_id: uuid.UUID
    checkpoint_type: str
    cursor_value: str | None
    external_id_last_processed: str | None
    records_processed: int
    records_total_estimate: int | None
    bytes_processed: int
    stage_percent: float | None
    checkpoint_jsonb: dict | None
    updated_at: datetime


class IngestionJobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    trusted_source_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    payload_jsonb: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    records_found: int
    records_processed: int
    error_log: str | None
    created_at: datetime
