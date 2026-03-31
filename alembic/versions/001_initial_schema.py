"""Initial schema: all v1 tables

Revision ID: 001
Revises: None
Create Date: 2026-03-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    # --- Enum types ---
    source_category = postgresql.ENUM(
        "text_corpus", "museum_collection", "site_archive", "gazetteer", "public_domain_library",
        name="source_category", create_type=True,
    )
    source_category.create(op.get_bind(), checkfirst=True)

    trust_tier = postgresql.ENUM("primary", "secondary", "tertiary", name="trust_tier", create_type=True)
    trust_tier.create(op.get_bind(), checkfirst=True)

    ingestion_method = postgresql.ENUM(
        "api", "xml_feed", "html_scrape", "iiif", "pdf_download", "manual_import",
        name="ingestion_method", create_type=True,
    )
    ingestion_method.create(op.get_bind(), checkfirst=True)

    parser_type = postgresql.ENUM(
        "tei_parser", "museum_html_parser", "json_api_parser", "pdf_parser",
        name="parser_type", create_type=True,
    )
    parser_type.create(op.get_bind(), checkfirst=True)

    discovered_record_status = postgresql.ENUM(
        "new", "queued", "fetched", "failed", "skipped",
        name="discovered_record_status", create_type=True,
    )
    discovered_record_status.create(op.get_bind(), checkfirst=True)

    record_status = postgresql.ENUM(
        "draft", "normalized", "reviewed", "published",
        name="record_status", create_type=True,
    )
    record_status.create(op.get_bind(), checkfirst=True)

    provenance_status = postgresql.ENUM(
        "verified", "unverified", "disputed", "unknown",
        name="provenance_status", create_type=True,
    )
    provenance_status.create(op.get_bind(), checkfirst=True)

    date_type = postgresql.ENUM(
        "composition", "copy_witness", "object_creation", "archaeological_context",
        "discovery", "recorded", "publication",
        name="date_type", create_type=True,
    )
    date_type.create(op.get_bind(), checkfirst=True)

    dating_confidence = postgresql.ENUM(
        "certain", "probable", "approximate", "uncertain", "speculative",
        name="dating_confidence", create_type=True,
    )
    dating_confidence.create(op.get_bind(), checkfirst=True)

    version_type = postgresql.ENUM(
        "original", "transliteration", "translation", "ocr", "museum_description", "edition",
        name="version_type", create_type=True,
    )
    version_type.create(op.get_bind(), checkfirst=True)

    copyright_status = postgresql.ENUM(
        "public_domain", "cc_by", "cc_by_sa", "cc_by_nc", "fair_use", "restricted", "unknown",
        name="copyright_status", create_type=True,
    )
    copyright_status.create(op.get_bind(), checkfirst=True)

    segment_type = postgresql.ENUM(
        "tablet", "section", "line_range", "paragraph", "verse",
        "object_summary", "inscription_block", "provenance_block", "description_block",
        "trench_layer_block", "findings_block", "dating_block",
        "speaker_block", "episode_block", "motif_block",
        name="segment_type", create_type=True,
    )
    segment_type.create(op.get_bind(), checkfirst=True)

    review_status = postgresql.ENUM(
        "pending", "approved", "rejected", "needs_review",
        name="review_status", create_type=True,
    )
    review_status.create(op.get_bind(), checkfirst=True)

    job_type = postgresql.ENUM(
        "discover", "fetch", "normalize", "segment", "embed", "reprocess",
        name="job_type", create_type=True,
    )
    job_type.create(op.get_bind(), checkfirst=True)

    job_status = postgresql.ENUM(
        "queued", "running", "succeeded", "failed", "partial", "skipped", "paused", "canceled",
        name="job_status", create_type=True,
    )
    job_status.create(op.get_bind(), checkfirst=True)

    run_type = postgresql.ENUM(
        "discovery", "full_ingest", "reprocess",
        name="run_type", create_type=True,
    )
    run_type.create(op.get_bind(), checkfirst=True)

    run_status = postgresql.ENUM(
        "queued", "running", "paused", "succeeded", "failed", "canceled", "partial",
        name="run_status", create_type=True,
    )
    run_status.create(op.get_bind(), checkfirst=True)

    # --- trusted_sources ---
    op.create_table(
        "trusted_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("slug", sa.String(256), nullable=False, unique=True),
        sa.Column("domain", sa.String(512), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("source_category", source_category, nullable=False),
        sa.Column("trust_tier", trust_tier, nullable=False, server_default="secondary"),
        sa.Column("ingestion_method", ingestion_method, nullable=False),
        sa.Column("parser_type", parser_type, nullable=False),
        sa.Column("content_types_supported", postgresql.ARRAY(sa.String(128)), nullable=True),
        sa.Column("robots_or_access_notes", sa.Text, nullable=True),
        sa.Column("license_notes", sa.Text, nullable=True),
        sa.Column("default_language", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("100")),
        sa.Column("rate_limit_rpm", sa.Integer, nullable=True),
        sa.Column("crawl_frequency_hours", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_trusted_sources_slug", "trusted_sources", ["slug"])
    op.create_index("ix_trusted_sources_active", "trusted_sources", ["active"])

    # --- discovered_records ---
    op.create_table(
        "discovered_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("external_id", sa.String(1024), nullable=False),
        sa.Column("record_url", sa.String(4096), nullable=False),
        sa.Column("title_hint", sa.Text, nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("discovery_metadata_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("status", discovered_record_status, nullable=False, server_default="new"),
    )
    op.create_index("ix_discovered_records_source", "discovered_records", ["trusted_source_id"])
    op.create_index("ix_discovered_records_external_id", "discovered_records", ["external_id"])
    op.create_index("ix_discovered_records_status", "discovered_records", ["status"])
    op.create_index(
        "ix_discovered_records_source_external",
        "discovered_records",
        ["trusted_source_id", "external_id"],
        unique=True,
    )

    # --- raw_objects ---
    op.create_table(
        "raw_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("discovered_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("discovered_records.id"), nullable=True),
        sa.Column("external_id", sa.String(1024), nullable=False),
        sa.Column("source_url", sa.String(4096), nullable=False),
        sa.Column("content_type", sa.String(256), nullable=True),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("r2_key", sa.String(2048), nullable=False, unique=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("raw_metadata_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("parser_hint", sa.String(256), nullable=True),
    )
    op.create_index("ix_raw_objects_source", "raw_objects", ["trusted_source_id"])
    op.create_index("ix_raw_objects_discovered_record", "raw_objects", ["discovered_record_id"])
    op.create_index("ix_raw_objects_external_id", "raw_objects", ["external_id"])
    op.create_index("ix_raw_objects_checksum", "raw_objects", ["checksum"])

    # --- source_records ---
    op.create_table(
        "source_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("raw_objects.id"), nullable=False),
        sa.Column("canonical_title", sa.String(2048), nullable=False),
        sa.Column("source_category", source_category, nullable=False),
        sa.Column("culture", sa.String(512), nullable=True),
        sa.Column("language_family", sa.String(256), nullable=True),
        sa.Column("origin_place_name", sa.String(512), nullable=True),
        sa.Column("repository_institution", sa.String(512), nullable=True),
        sa.Column("provenance_status", provenance_status, nullable=False, server_default="unknown"),
        sa.Column("authenticity_notes", sa.Text, nullable=True),
        sa.Column("rights_notes", sa.Text, nullable=True),
        sa.Column("record_status", record_status, nullable=False, server_default="draft"),
        sa.Column("metadata_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_records_raw_object", "source_records", ["raw_object_id"])
    op.create_index("ix_source_records_status", "source_records", ["record_status"])

    # --- source_dates ---
    op.create_table(
        "source_dates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("date_type", date_type, nullable=False),
        sa.Column("date_start", sa.Integer, nullable=True),
        sa.Column("date_end", sa.Integer, nullable=True),
        sa.Column("date_label", sa.String(512), nullable=True),
        sa.Column("dating_method", sa.String(256), nullable=True),
        sa.Column("dating_confidence", dating_confidence, nullable=False, server_default="uncertain"),
        sa.Column("source_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_dates_record", "source_dates", ["source_record_id"])

    # --- source_versions ---
    op.create_table(
        "source_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("version_type", version_type, nullable=False),
        sa.Column("language", sa.String(128), nullable=True),
        sa.Column("translator_editor", sa.String(512), nullable=True),
        sa.Column("publication_year", sa.Integer, nullable=True),
        sa.Column("publisher", sa.String(512), nullable=True),
        sa.Column("edition_title", sa.String(1024), nullable=True),
        sa.Column("license_notes", sa.Text, nullable=True),
        sa.Column("copyright_status", copyright_status, nullable=False, server_default="unknown"),
        sa.Column("is_preferred", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("r2_key", sa.String(2048), nullable=True),
        sa.Column("text_extracted", sa.Text, nullable=True),
        sa.Column("metadata_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_versions_record", "source_versions", ["source_record_id"])

    # --- segments ---
    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_versions.id"), nullable=False),
        sa.Column("segment_type", segment_type, nullable=False),
        sa.Column("segment_order", sa.Integer, nullable=False),
        sa.Column("citation_ref", sa.String(1024), nullable=True),
        sa.Column("original_text", sa.Text, nullable=True),
        sa.Column("normalized_text", sa.Text, nullable=True),
        sa.Column("metadata_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("review_status", review_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_segments_version", "segments", ["source_version_id"])
    op.create_index("ix_segments_order", "segments", ["source_version_id", "segment_order"])

    # --- embeddings ---
    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("segments.id"), nullable=False),
        sa.Column("embedding", sa.Column, nullable=False),
        sa.Column("embedding_model", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # pgvector column needs raw SQL
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_index("ix_embeddings_segment", "embeddings", ["segment_id"])
    op.execute(
        "CREATE INDEX ix_embeddings_vector ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # --- ingestion_jobs ---
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("payload_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_found", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("records_processed", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_log", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ingestion_jobs_source", "ingestion_jobs", ["trusted_source_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    # --- source_runs ---
    op.create_table(
        "source_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("run_type", run_type, nullable=False),
        sa.Column("status", run_status, nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by", sa.String(256), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_runs_source", "source_runs", ["trusted_source_id"])
    op.create_index("ix_source_runs_status", "source_runs", ["status"])

    # --- queued_jobs ---
    op.create_table(
        "queued_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_runs.id"), nullable=True),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("100")),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(256), nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("payload_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("error_log", sa.Text, nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_queued_jobs_source_run", "queued_jobs", ["source_run_id"])
    op.create_index("ix_queued_jobs_source", "queued_jobs", ["trusted_source_id"])
    op.create_index("ix_queued_jobs_status", "queued_jobs", ["status"])
    op.create_index("ix_queued_jobs_claimable", "queued_jobs", ["status", "priority", "scheduled_for"])

    # --- job_checkpoints ---
    op.create_table(
        "job_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("queued_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("queued_jobs.id"), nullable=False),
        sa.Column("checkpoint_type", sa.String(256), nullable=False),
        sa.Column("cursor_value", sa.String(2048), nullable=True),
        sa.Column("external_id_last_processed", sa.String(1024), nullable=True),
        sa.Column("records_processed", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("records_total_estimate", sa.Integer, nullable=True),
        sa.Column("bytes_processed", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("stage_percent", sa.Float, nullable=True),
        sa.Column("checkpoint_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_checkpoints_job", "job_checkpoints", ["queued_job_id"])

    # --- source_progress ---
    op.create_table(
        "source_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False, unique=True),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_runs.id"), nullable=True),
        sa.Column("discovered_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("fetched_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("normalized_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("segmented_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("embedded_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("total_bytes_stored", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("last_successful_checkpoint", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_progress_source", "source_progress", ["trusted_source_id"])


def downgrade() -> None:
    op.drop_table("source_progress")
    op.drop_table("job_checkpoints")
    op.drop_table("queued_jobs")
    op.drop_table("source_runs")
    op.drop_table("ingestion_jobs")
    op.drop_table("embeddings")
    op.drop_table("segments")
    op.drop_table("source_versions")
    op.drop_table("source_dates")
    op.drop_table("source_records")
    op.drop_table("raw_objects")
    op.drop_table("discovered_records")
    op.drop_table("trusted_sources")

    for enum_name in [
        "run_status", "run_type", "job_status", "job_type",
        "review_status", "segment_type", "copyright_status",
        "version_type", "dating_confidence", "date_type",
        "provenance_status", "record_status", "discovered_record_status",
        "parser_type", "ingestion_method", "trust_tier", "source_category",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
