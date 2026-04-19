# Eden Ingestion Platform

Source-governed, queue-driven, checkpointed, resumable, and observable ingestion pipeline for archival material.

## Architecture

```
Admin UI (React)
  |
  v
FastAPI Admin API
  |
  +--> Trusted Sources Registry
  +--> Queue Control (Postgres-backed)
  +--> Progress / Status API
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

## Pipeline Stages

| Stage | Worker | Input | Output |
|-------|--------|-------|--------|
| **Discovery** | `discovery_worker` | Trusted source config, APIs, feeds | Discovered records with external IDs |
| **Fetch** | `fetch_worker` | Discovered records | Raw files in R2 + metadata in Postgres |
| **Normalize** | `normalization_worker` | Raw objects | Canonical source records, dates, versions |
| **Segment** | `segmentation_worker` | Source versions | Citation-friendly text segments |
| **Embed** | `embedding_worker` | Segments | pgvector embeddings |

## Stack

- **API**: FastAPI (Python)
- **Database**: PostgreSQL with pgvector
- **Object Storage**: Cloudflare R2
- **Queue**: Postgres-backed job queue with row-level locking
- **Frontend**: React + Vite + TypeScript
- **Containers**: Docker / Docker Compose

## Quick Start

### Docker Compose (recommended)

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your R2 and OpenAI credentials

# Start everything
docker compose up -d

# Access:
#   Admin UI:  http://localhost:3000
#   API:       http://localhost:8000
#   API Docs:  http://localhost:8000/docs
```

### Local Development

```bash
# Backend
pip install -r requirements.txt
export EDEN_DATABASE_URL="postgresql+asyncpg://eden:eden@localhost:5432/eden"

# Run migrations
alembic upgrade head

# Start API
uvicorn src.ingestion.api.app:app --reload --port 8000

# Start workers (all in one process)
python -m src.ingestion.workers.runner all

# Or start individual workers
python -m src.ingestion.workers.runner discovery
python -m src.ingestion.workers.runner fetch
python -m src.ingestion.workers.runner normalize
python -m src.ingestion.workers.runner segment
python -m src.ingestion.workers.runner embed

# Frontend
cd frontend
npm install
npm run dev
```

## API Endpoints

### Trusted Sources

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/sources` | List all trusted sources |
| `POST` | `/admin/sources` | Register a new trusted source |
| `GET` | `/admin/sources/{id}` | Get source details |
| `PATCH` | `/admin/sources/{id}` | Update source config |
| `POST` | `/admin/sources/{id}/pause` | Deactivate source |
| `POST` | `/admin/sources/{id}/resume` | Reactivate source |
| `POST` | `/admin/sources/{id}/run` | Start ingestion run |
| `POST` | `/admin/sources/{id}/reprocess` | Re-derive from existing raw objects |

### Queue & Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/jobs` | List jobs with filters |
| `GET` | `/admin/jobs/{id}` | Get job details |
| `GET` | `/admin/jobs/{id}/checkpoints` | Get job checkpoints |
| `POST` | `/admin/jobs/enqueue` | Manually enqueue a job |
| `POST` | `/admin/jobs/{id}/pause` | Pause a running job |
| `POST` | `/admin/jobs/{id}/resume` | Resume a paused job |
| `POST` | `/admin/jobs/{id}/retry` | Retry a failed job |
| `POST` | `/admin/jobs/{id}/cancel` | Cancel a queued job |
| `POST` | `/admin/jobs/recover-stalled` | Recover stalled jobs |

### Progress

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/progress/overview` | System-wide stats |
| `GET` | `/admin/progress/sources` | Per-source progress |
| `GET` | `/admin/progress/sources/{id}` | Single source progress |

### Archive Inspection

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/archive/raw-objects` | List raw objects |
| `GET` | `/admin/archive/raw-objects/{id}` | Get raw object metadata |
| `GET` | `/admin/archive/source-records` | List source records |
| `GET` | `/admin/archive/source-records/{id}` | Get source record |
| `GET` | `/admin/archive/source-records/{id}/dates` | List typed dates |
| `GET` | `/admin/archive/source-records/{id}/versions` | List source versions |
| `GET` | `/admin/archive/versions/{id}/segments` | List segments |
| `GET` | `/admin/archive/provenance/{id}` | Full provenance chain |

## Database Schema

### Core Tables

- **trusted_sources** — Approved source registry (whitelist)
- **discovered_records** — External records found during discovery
- **raw_objects** — Immutable raw file metadata + R2 key references
- **source_records** — Canonical normalized metadata
- **source_dates** — Typed date records (composition, discovery, publication, etc.)
- **source_versions** — Translations, transliterations, OCR, editions
- **segments** — Retrieval-ready text chunks with citations
- **embeddings** — pgvector embeddings for semantic search

### Operations Tables

- **ingestion_jobs** — Legacy job tracking
- **source_runs** — Execution runs per source
- **queued_jobs** — Durable queue with row-level locking
- **job_checkpoints** — Resumable progress state
- **source_progress** — Aggregate per-source progress

## Worker Behavior

- **Heartbeat**: Every 30s, workers update `last_heartbeat_at`
- **Checkpointing**: Every 50 items or 60 seconds, whichever comes first
- **Resume**: On restart, workers load the latest checkpoint and skip completed items
- **Stalled recovery**: Jobs with stale heartbeats (>120s) can be reclaimed
- **Pause**: Workers finish the current atomic unit, save checkpoint, then stop
- **Rate limiting**: Per-source configurable RPM limits respected during fetch

## Configuration

All settings via environment variables with `EDEN_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `EDEN_DATABASE_URL` | `postgresql+asyncpg://eden:eden@localhost:5432/eden` | Async database URL |
| `EDEN_DATABASE_URL_SYNC` | `postgresql://eden:eden@localhost:5432/eden` | Sync database URL (migrations) |
| `EDEN_R2_ENDPOINT_URL` | — | Cloudflare R2 S3-compatible endpoint |
| `EDEN_R2_ACCESS_KEY_ID` | — | R2 access key |
| `EDEN_R2_SECRET_ACCESS_KEY` | — | R2 secret key |
| `EDEN_R2_BUCKET_NAME` | `eden-raw` | R2 bucket name |
| `EDEN_OPENAI_API_KEY` | — | OpenAI API key for embeddings |
| `EDEN_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EDEN_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `EDEN_WORKER_HEARTBEAT_INTERVAL_SECONDS` | `30` | Heartbeat frequency |
| `EDEN_WORKER_STALE_THRESHOLD_SECONDS` | `120` | Stale job detection threshold |
| `EDEN_WORKER_CHECKPOINT_INTERVAL_ITEMS` | `50` | Checkpoint every N items |
| `EDEN_WORKER_MAX_ATTEMPTS` | `3` | Max retry attempts |
| `EDEN_DEFAULT_RATE_LIMIT_RPM` | `60` | Default fetch rate limit |

## R2 Storage Layout

```
raw/{source_slug}/{yyyy}/{mm}/{dd}/{external_id}/original
raw/{source_slug}/{yyyy}/{mm}/{dd}/{external_id}/metadata.json

derived/{source_slug}/{source_record_id}/normalized.json
derived/{source_slug}/{source_record_id}/versions/{version_id}.json
derived/{source_slug}/{source_record_id}/segments/{version_id}.jsonl
```

## Design Principles

1. **Source-governed only** — Ingest only from approved trusted sources
2. **Raw-first** — Store every fetched payload unchanged before any transformation
3. **Derived, never destructive** — Normalization and segmentation create new records, never overwrite raw data
4. **Full provenance chain** — Every object traces back to its trusted source
5. **Reprocessable** — Re-derive from stored raw objects without re-fetching
6. **Type-aware** — Dates and translations are first-class entities, not freeform notes
