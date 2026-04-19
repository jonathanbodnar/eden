# Eden Ingestion Platform — Dev Specification v1

## 1. Purpose

Build a provenance-first ingestion system that pulls only from approved sources, stores raw historical material unchanged, normalizes metadata into a canonical schema, segments content into retrievable units, and prepares structured data for later extraction and LLM retrieval.

**This document covers only:**

- trusted source governance
- ingestion pipeline
- storage architecture
- canonical data flow
- storage schema responsibilities
- operations layer (admin UI, queueing, resumability, progress tracking)

**It does not cover:**

- frontend/world-model UI
- narration layer
- chapter generation
- Neo4j graph layer
- OpenSearch
- advanced orchestration beyond v1

---

## 2. Locked-In v1 Stack

| Component | Choice |
|---|---|
| Object storage | Cloudflare R2 |
| Primary database | PostgreSQL |
| Vector search | pgvector in PostgreSQL |
| Graph | deferred to v2 |
| Search | deferred until needed |
| Workers/jobs | containerized Python workers |
| API layer | FastAPI |
| Orchestration | cron + queue initially, Airflow/Temporal later |
| Frontend | React + Vite + TypeScript |

---

## 3. Core Design Principles

### 3.1 Source-governed only
The system must only ingest from approved sources listed in the trusted source registry.

### 3.2 Raw-first
Every fetched file or payload must be stored unchanged before any parsing or transformation.

### 3.3 Derived, never destructive
Normalization, segmentation, and extraction create derived records. They never overwrite raw material.

### 3.4 Full provenance chain
Every downstream object must trace back to:
```
trusted source → raw object → canonical source record → source version → segment
```

### 3.5 Reprocessable
We must be able to rerun normalization or segmentation later without re-fetching source material.

### 3.6 Type-aware dates and translations
Dates and translations are first-class entities, not just freeform notes.

---

## 4. System Scope

**v1 is responsible for:**

- maintaining a whitelist of trusted sources
- discovering source records from those sources
- fetching raw materials
- storing raw materials in R2
- storing fetch metadata in Postgres
- creating canonical source records
- creating typed date records
- creating version records for translations / transliterations / OCR / editions
- segmenting content into retrievable chunks
- generating embeddings for segments
- exposing storage and retrieval-ready records through internal APIs

**v1 is NOT responsible for:**

- speculative entity merging
- theory inference
- narrative generation
- public search UX
- graph reasoning

---

## 5. High-Level Architecture

```
Admin UI (React)
  |
  v
FastAPI Admin/API
  |
  +--> Trusted Sources Registry
  +--> Queue Control (Postgres-backed)
  +--> Progress / Status API
  |
  v
Job Queue (Postgres)
  |
  v
Pipeline Workers
  |
  +--> Cloudflare R2 (raw immutable objects)
  +--> PostgreSQL (metadata, lineage, embeddings)
  |
  v
Checkpoint + Heartbeat State
```

### Provenance Chain

Every downstream object traces back through:
```
trusted_source → discovered_record → raw_object → source_record → source_dates → source_versions → segments → embeddings
```

---

## 6. Trusted Source Governance

### 6.1 Purpose
Prevent random scraping and enforce ingest-from-approved-only behavior.

### 6.2 Trusted source registry

Create a `trusted_sources` table that acts as the control plane.

**Required fields:**
- `id`
- `name`
- `slug`
- `domain`
- `base_url`
- `source_category`
- `trust_tier`
- `ingestion_method`
- `parser_type`
- `content_types_supported`
- `robots_or_access_notes`
- `license_notes`
- `default_language`
- `active`
- `priority`
- `created_at`
- `updated_at`

**Example values:**
- source category: `text_corpus`, `museum_collection`, `site_archive`, `gazetteer`, `public_domain_library`
- ingestion method: `api`, `xml_feed`, `html_scrape`, `iiif`, `pdf_download`, `manual_import`
- parser type: `tei_parser`, `museum_html_parser`, `json_api_parser`, `pdf_parser`

### 6.3 Governance rules

- only active trusted sources may be ingested
- each source must have an assigned parser strategy
- each source must have license/access notes
- source-specific workers must reject URLs outside approved domains
- all manual imports must still map to a trusted source entry

---

## 7. Pipeline Stages

### 7.1 Stage 1: Discovery

**Purpose:** identify source records that should be fetched.

**Inputs:**
- trusted source config
- optional cursors
- source APIs / listing pages / sitemaps / feeds

**Outputs:**
- discovered external IDs
- discovered record URLs
- light metadata snapshot
- queued fetch jobs

**Responsibilities:**
- detect new or updated source records
- deduplicate against prior discoveries
- enqueue fetch tasks

**Stored in Postgres — `discovered_records`:**
- `id`
- `trusted_source_id`
- `external_id`
- `record_url`
- `title_hint`
- `discovered_at`
- `last_seen_at`
- `discovery_metadata_jsonb`
- `status`

### 7.2 Stage 2: Fetch

**Purpose:** retrieve the raw source material and store it unchanged.

**Inputs:**
- fetch job
- trusted source config
- discovered record URL or API endpoint

**Outputs:**
- raw file or raw payload written to R2
- raw object metadata written to Postgres

**Responsibilities:**
- download HTML, JSON, XML, PDF, image, IIIF manifest, etc.
- calculate checksum
- assign deterministic storage key
- save fetch-time metadata
- never parse before raw storage succeeds

**Stored in R2:**
```
/raw/{source_slug}/{yyyy}/{mm}/{dd}/{external_id}/original
/raw/{source_slug}/{yyyy}/{mm}/{dd}/{external_id}/metadata.json
```

**Stored in Postgres — `raw_objects`:**
- `id`
- `trusted_source_id`
- `discovered_record_id`
- `external_id`
- `source_url`
- `content_type`
- `checksum`
- `byte_size`
- `r2_key`
- `fetched_at`
- `http_status`
- `raw_metadata_jsonb`
- `parser_hint`

**Raw storage rules:**
- raw objects are immutable
- re-fetching creates a new raw object row if content differs
- content hash is used for dedupe and change detection
- R2 key should be stable and human-inspectable

### 7.3 Stage 3: Normalization

**Purpose:** convert source-specific metadata into canonical source records.

**Inputs:**
- raw object
- source-specific parser
- source config

**Outputs:**
- canonical `source_record`
- canonical metadata JSON
- typed date rows
- initial source version rows

**Responsibilities:**
- map varied source metadata into unified schema
- classify item type
- identify institution/repository
- capture origin location if present
- create typed dates
- create one or more source versions

**Stored in Postgres — `source_records`:**
- `id`
- `raw_object_id`
- `canonical_title`
- `source_category`
- `culture`
- `language_family`
- `origin_place_name`
- `repository_institution`
- `provenance_status`
- `authenticity_notes`
- `rights_notes`
- `record_status`
- `metadata_jsonb`
- `created_at`
- `updated_at`

**Stored in Postgres — `source_dates`:**
- `id`
- `source_record_id`
- `date_type`
- `date_start`
- `date_end`
- `date_label`
- `dating_method`
- `dating_confidence`
- `source_note`

**Stored in Postgres — `source_versions`:**
- `id`
- `source_record_id`
- `version_type`
- `language`
- `translator_editor`
- `publication_year`
- `publisher`
- `edition_title`
- `license_notes`
- `copyright_status`
- `is_preferred`
- `quality_score`
- `r2_key`
- `text_extracted`
- `metadata_jsonb`

**Supported date types:**
`composition`, `copy_witness`, `object_creation`, `archaeological_context`, `discovery`, `recorded`, `publication`

**Supported version types:**
`original`, `transliteration`, `translation`, `ocr`, `museum_description`, `edition`

### 7.4 Stage 4: Segmentation

**Purpose:** break content into citation-friendly, retrieval-friendly units.

**Inputs:**
- source version
- extracted text or structured content

**Outputs:**
- ordered segment rows
- citation references
- segment metadata

**Responsibilities:**
- segment based on source type
- preserve order
- preserve citation granularity
- store original and normalized text separately

**Stored in Postgres — `segments`:**
- `id`
- `source_version_id`
- `segment_type`
- `segment_order`
- `citation_ref`
- `original_text`
- `normalized_text`
- `metadata_jsonb`
- `review_status`

**Segmentation rules by type:**

| Type | Segments |
|---|---|
| Texts | tablet, section, line range, paragraph, verse |
| Artifacts | object summary, inscription block, provenance/findspot block, description block |
| Reports | section, trench/layer block, findings block, dating block |
| Oral records | speaker block, episode block, motif block |

**Segment requirements:**
- small enough for retrieval
- large enough to preserve meaning
- individually citable
- linked to a single source version

### 7.5 Stage 5: Embedding

**Purpose:** make segments retrievable by semantic meaning.

**Inputs:**
- segments
- embedding model

**Outputs:**
- vector rows stored in Postgres via pgvector

**Stored in Postgres — `embeddings`:**
- `id`
- `target_type`
- `target_id`
- `embedding`
- `embedding_model`
- `created_at`

**Rules:**
- embeddings are generated only for finalized segments
- embedding rows are replaceable if model changes
- embeddings should not be stored in raw files
- segment text remains the canonical retrieval payload

---

## 8. Storage Layout

### 8.1 Cloudflare R2

R2 stores:
- raw downloaded files
- raw metadata snapshots
- derived normalized JSON if needed
- OCR output files if external OCR is used
- text extracts too large for DB fields
- source version file assets

**Key layout:**
```
raw/{source_slug}/{yyyy}/{mm}/{dd}/{external_id}/original
raw/{source_slug}/{yyyy}/{mm}/{dd}/{external_id}/metadata.json

derived/{source_slug}/{source_record_id}/normalized.json
derived/{source_slug}/{source_record_id}/versions/{version_id}.json
derived/{source_slug}/{source_record_id}/segments/{version_id}.jsonl
```

**R2 rules:**
- raw and derived must be separated
- raw objects are never mutated
- derived objects may be regenerated
- every DB row referencing a file must include the R2 key

### 8.2 PostgreSQL

Postgres stores:
- trusted source registry
- job state
- discovery records
- raw object ledger
- canonical source records
- typed dates
- source versions
- segments
- embeddings
- processing status
- error state

**Why Postgres is canonical:**
- transactional integrity
- easy lineage tracking
- typed schema
- good fit for metadata-heavy records
- jsonb for parser-specific leftovers
- pgvector support in same DB

---

## 9. Canonical Lineage

Every downstream object must be traceable through this chain:
```
trusted_source
  → discovered_record
    → raw_object
      → source_record
        → source_date(s)
        → source_version(s)
          → segment(s)
            → embedding(s)
```

**This lineage is non-negotiable.**

---

## 10. Processing Jobs

### 10.1 Job types

Use an `ingestion_jobs` table for lifecycle tracking.

**Job types:** `discover`, `fetch`, `normalize`, `segment`, `embed`, `reprocess`

**Fields:**
- `id`, `trusted_source_id`, `job_type`, `status`, `payload_jsonb`
- `started_at`, `completed_at`, `records_found`, `records_processed`, `error_log`

**Status values:** `queued`, `running`, `succeeded`, `failed`, `partial`, `skipped`

### 10.2 Worker model

Each stage should be a separate Python worker responsibility.

**Workers:** `discovery_worker`, `fetch_worker`, `normalization_worker`, `segmentation_worker`, `embedding_worker`

**Rule:** Workers communicate through DB state + queue, not direct coupling.

---

## 11. Deduplication and Versioning

### 11.1 Raw dedupe
Use checksum + source/external ID to detect identical content.

### 11.2 Canonical dedupe
Two different raw objects may map to the same underlying source record. Example: same text from two mirrors, same museum object through two pages, same translation from multiple repositories.

**Rule:** Do not dedupe by title alone.

### 11.3 Versioning
New translations, OCR revisions, or updated source snapshots should create new `source_versions`, not overwrite old ones.

---

## 12. Translation Handling

Translations must be explicitly modeled as `source_versions`.

A single source may have:
- original language version
- transliteration
- literal translation
- interpretive translation
- museum prose summary
- OCR-derived text

**Rules:**
- translations are not stored as notes on the source
- each translation has its own metadata
- each translation can be segmented independently
- preferred translation can be flagged
- multiple translations may coexist for later comparison

---

## 13. Date Handling

Dates must be stored in `source_dates`, not flattened into one field.

A source may have:
- composition date
- extant witness date
- object creation date
- excavation context date
- discovery date
- translation publication date

**Rules:**
- use `date_start` + `date_end` for uncertain ranges
- store date type explicitly
- allow BCE ranges as signed integers or agreed canonical format
- preserve textual labels where exact dating is uncertain

---

## 14. Internal API Scope

FastAPI should expose internal endpoints for pipeline operations and archive inspection.

### Trusted Sources
| Method | Path | Description |
|---|---|---|
| GET | `/admin/sources` | List all trusted sources |
| POST | `/admin/sources` | Register a new trusted source |
| GET | `/admin/sources/{id}` | Get source details |
| PATCH | `/admin/sources/{id}` | Update source config |
| POST | `/admin/sources/{id}/pause` | Deactivate source |
| POST | `/admin/sources/{id}/resume` | Reactivate source |
| POST | `/admin/sources/{id}/run` | Start ingestion run |
| POST | `/admin/sources/{id}/reprocess` | Re-derive from existing raw objects |

### Queue & Jobs
| Method | Path | Description |
|---|---|---|
| GET | `/admin/jobs` | List jobs with filters |
| GET | `/admin/jobs/{id}` | Get job details |
| GET | `/admin/jobs/{id}/checkpoints` | Get job checkpoints |
| POST | `/admin/jobs/enqueue` | Manually enqueue a job |
| POST | `/admin/jobs/{id}/pause` | Pause a running job |
| POST | `/admin/jobs/{id}/resume` | Resume a paused job |
| POST | `/admin/jobs/{id}/retry` | Retry a failed job |
| POST | `/admin/jobs/{id}/cancel` | Cancel a queued job |
| POST | `/admin/jobs/recover-stalled` | Recover stalled jobs |

### Progress
| Method | Path | Description |
|---|---|---|
| GET | `/admin/progress/overview` | System-wide stats |
| GET | `/admin/progress/sources` | Per-source progress |
| GET | `/admin/progress/sources/{id}` | Single source progress |

### Archive Inspection
| Method | Path | Description |
|---|---|---|
| GET | `/admin/archive/raw-objects` | List raw objects |
| GET | `/admin/archive/raw-objects/{id}` | Get raw object metadata |
| GET | `/admin/archive/source-records` | List source records |
| GET | `/admin/archive/source-records/{id}` | Get source record |
| GET | `/admin/archive/source-records/{id}/dates` | List typed dates |
| GET | `/admin/archive/source-records/{id}/versions` | List source versions |
| GET | `/admin/archive/versions/{id}/segments` | List segments |
| GET | `/admin/archive/provenance/{id}` | Full provenance chain |

---

## 15. Error Handling

**Requirements:**
- failed stages should not corrupt prior stages
- partial failures must be visible in job logs
- failed normalization does not delete raw objects
- failed segmentation does not delete source versions
- retries must be safe and idempotent where possible

**Store failures in:**
- `ingestion_jobs.error_log`
- parser-specific structured error payloads in jsonb

---

## 16. Reprocessing Strategy

Reprocessing is a built-in requirement.

**Examples:** improved parser, better segmentation rules, better OCR, new preferred translation, revised metadata mapping.

**Rule:** Reprocessing uses existing raw objects from R2 and creates fresh derived records as needed. No re-fetch required unless the source itself changed.

---

## 17. Operations Layer

### 17.1 Requirements

The system must support:
- adding and editing trusted sources through an interface
- placing sources or source jobs into a queue
- running long ingestion jobs in the background
- saving progress continuously so a stop/crash does not lose work
- resuming from the last checkpoint
- showing visible progress by source, stage, and total archive growth

### 17.2 Operations tables

**`source_runs`** — Represents an execution run for a source:
- `id`, `trusted_source_id`, `run_type` (discovery, full_ingest, reprocess)
- `status`, `started_at`, `completed_at`, `paused_at`, `last_heartbeat_at`
- `requested_by`, `notes`

**`queued_jobs`** — Stage-specific background jobs:
- `id`, `source_run_id`, `trusted_source_id`, `job_type`
- `status`, `priority`, `scheduled_for`, `started_at`, `completed_at`
- `worker_id`, `attempt_count`, `max_attempts`
- `payload_jsonb`, `error_log`

**`job_checkpoints`** — Resumable progress:
- `id`, `queued_job_id`, `checkpoint_type`
- `cursor_value`, `external_id_last_processed`
- `records_processed`, `records_total_estimate`, `bytes_processed`, `stage_percent`
- `checkpoint_jsonb`, `updated_at`

**`source_progress`** — Aggregate per-source progress:
- `id`, `trusted_source_id`, `last_run_id`
- `discovered_count`, `fetched_count`, `normalized_count`, `segmented_count`, `embedded_count`
- `failed_count`, `skipped_count`, `total_bytes_stored`
- `last_successful_checkpoint`, `last_updated_at`

### 17.3 Checkpointing rules

Workers should checkpoint at least:
- every N items (default: 50)
- every M seconds (default: 60)
- before shutdown
- on caught exceptions
- on pause signal

**Per-worker checkpoint contents:**

| Worker | Checkpoint fields |
|---|---|
| Discovery | current page, cursor/token, last listing URL, discovered count |
| Fetch | last external id fetched, bytes downloaded, fetched count, queue backlog |
| Normalize | last raw_object_id normalized, success/failure counts |
| Segment | last source_version_id segmented, segments created |
| Embed | last segment id embedded, embeddings created |

### 17.4 Pause/resume behavior

**Pause flow:**
1. No new jobs are claimed
2. Active worker finishes current atomic unit
3. Worker writes checkpoint
4. Job status becomes `paused`

**Resume flow:**
1. Worker loads latest checkpoint
2. Continues from cursor / last processed id
3. Does not reprocess completed items unless explicitly told to

### 17.5 Heartbeat and recovery

- Each running worker updates `last_heartbeat_at` every 30s
- Jobs with stale heartbeats (>120s) are marked recoverable
- Another worker can reclaim recoverable jobs
- Retries respect max attempts
- Failed record does not kill whole source run unless failure threshold is exceeded

### 17.6 Progress tracking model

Three kinds of progress:

| Type | When | Display |
|---|---|---|
| Deterministic | Source tells total items | Exact percent bar |
| Estimated | Partial information available | Estimated percent, labeled clearly |
| Open-ended | Continuous/incremental feed | Counts + throughput only |

**Per source:** current stage, status, records processed, records total (if known), percent (if known), bytes downloaded, last processed item, checkpoint timestamp, average throughput.

**System-wide:** total active sources, queued/running/failed jobs, total raw objects, total segments, total storage, 24h throughput.

### 17.7 Execution model for v1

- Cron triggers source discovery on schedule
- FastAPI enqueues jobs into `queued_jobs`
- Workers poll and claim jobs using row-level locking (DB-safe claiming)
- Worker claims → marks as running → writes worker id → begins processing

---

## 18. Admin UI

### 18.1 Trusted Sources page

**Columns:** source name, domain, type, status, priority, last run, next scheduled run, items discovered, items ingested, progress state, actions

**Actions:** edit, run now, pause, resume, disable

### 18.2 Queue page

**Columns:** job id, source, stage, status, started at, elapsed time, records processed, records total, checkpoint, worker id, error summary

### 18.3 Progress dashboard

**Cards:** total trusted sources, total raw objects, total source records, total versions, total segments, total bytes stored, jobs running, failed jobs needing review

**Progress bars:** per source, per stage, daily ingestion volume, backlog remaining

### 18.4 Failures / retry view

**Shows:** failed jobs, failed URLs, parser errors, rate-limit issues, resumable retry button

---

## 19. Non-Negotiable Operational Rules

1. Every job must be resumable
2. Every running job must write heartbeat
3. Every stage must checkpoint progress
4. Raw objects already stored must never be re-downloaded unless requested
5. Pause must preserve state
6. Retry must continue from checkpoint when safe
7. Progress must distinguish exact vs estimated vs unknown
8. Failures must be isolated to item or stage when possible

---

## 20. Minimum Deliverables for v1

### Infrastructure
- R2 bucket setup
- Postgres setup with pgvector enabled
- FastAPI service
- Python worker containers
- queue + cron scheduling

### Database
- migration files for all v1 tables
- indexes for lineage and retrieval
- enums or lookup tables for categories/types

### Pipeline
- source registry CRUD
- one discovery worker
- one fetch worker
- one normalization worker
- one segmentation worker
- one embedding worker

### Operations
- trusted source CRUD API
- queue/job models
- checkpoint models
- source progress aggregation
- pause/resume/retry logic
- stalled job recovery
- checkpoint writes in workers
- heartbeats in workers
- resumable processing
- graceful pause handling

### Admin UI
- source registry screen
- queue screen
- progress dashboard
- failure/retry screen

---

## 21. v1 Success Criteria

The pipeline is successful when an operator can:

1. Add a trusted source
2. Run discovery against it
3. Fetch raw records into R2
4. See raw object metadata in Postgres
5. Normalize a fetched object into a canonical source record
6. Attach typed dates
7. Attach one or more versions including translations
8. Segment one version into retrievable chunks
9. Generate embeddings for those chunks
10. Inspect the full provenance chain end to end
11. Pause and resume an in-progress ingestion
12. See per-source and system-wide progress
13. Retry failed jobs from checkpoint

---

## 22. Summary

The source-governed ingestion pipeline is a controlled archival system, not a generic scraper.

Its job is to:
- ingest only from approved sources
- store raw material immutably in R2
- normalize source metadata into Postgres
- model dates and translations explicitly
- segment source versions into retrieval-ready chunks
- generate embeddings in pgvector
- preserve a strict provenance chain through every layer
- be queue-driven, checkpointed, resumable, and observable

The core v1 lineage:
```
trusted source → discovered record → raw object → source record → source dates → source versions → segments → embeddings
```

**The ingestion system must be source-governed, queue-driven, checkpointed, resumable, and observable.**
