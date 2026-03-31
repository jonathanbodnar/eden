# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Eden Ingestion Platform — a source-governed, queue-driven, checkpointed ingestion pipeline for archival material with an admin UI. See `README.md` for full architecture and API reference.

### Services

| Service | Tech | How to run | Port |
|---------|------|-----------|------|
| **PostgreSQL + pgvector** | `pgvector/pgvector:pg16` Docker image | `docker run -d --name eden-postgres -e POSTGRES_USER=eden -e POSTGRES_PASSWORD=eden -e POSTGRES_DB=eden -p 5432:5432 pgvector/pgvector:pg16` | 5432 |
| **FastAPI API** | Python 3.12, uvicorn | `PYTHONPATH=. uvicorn src.ingestion.api.app:app --reload --port 8000` | 8000 |
| **Frontend (Vite)** | React 19, TypeScript | `cd frontend && npm run dev` | 3000 |
| **Workers** (optional) | Python 3.12 | `python -m src.ingestion.workers.runner all` | — |

### Database setup gotchas

- The Alembic migration (`001_initial_schema.py`) has a bug: it creates PostgreSQL ENUM types explicitly (with `create_type=True`) and then again implicitly when `create_table` triggers SQLAlchemy's automatic enum creation, causing `DuplicateObject` errors. **Workaround**: create the enums and tables directly from SQLAlchemy models, then stamp Alembic:
  ```bash
  PYTHONPATH=. python3 -c "
  from sqlalchemy import create_engine, text
  from src.ingestion.models import Base
  engine = create_engine('postgresql://eden:eden@localhost:5432/eden')
  with engine.connect() as conn:
      conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
      conn.execute(text('CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"'))
      conn.commit()
  # Create enum types using Python enum .name values (uppercase)
  from src.ingestion.models import enums as e
  import inspect
  enum_classes = {name: obj for name, obj in inspect.getmembers(e) if inspect.isclass(obj) and issubclass(obj, e.enum.Enum) and obj is not e.enum.Enum}
  # ... then create_all and stamp
  "
  PYTHONPATH=. alembic stamp 001
  ```
- The models use `create_type=False` on ENUM columns, so PostgreSQL enum types must exist before `Base.metadata.create_all()` runs. The enum values stored in the DB use the Python enum `.name` attribute (e.g., `TEXT_CORPUS`), not `.value` (e.g., `text_corpus`).
- Alembic uses the **sync** database URL (`postgresql://...`), which requires `psycopg2-binary`. The FastAPI app uses the **async** URL (`postgresql+asyncpg://...`).

### Lint / Test / Build

- **Python lint**: `ruff check src/ tests/` (pre-existing warnings exist in the repo)
- **Python tests**: `PYTHONPATH=. pytest tests/ -v` (test directory exists but is empty)
- **Frontend type check**: `cd frontend && npx tsc --noEmit`
- **Frontend build**: `cd frontend && npm run build`
- **Frontend dev**: `cd frontend && npm run dev`

### Environment variables

All config uses `EDEN_` prefix. Defaults connect to `eden:eden@localhost:5432/eden`. See `.env.example` for full list. R2 and OpenAI keys are only needed for actual ingestion pipeline runs (workers), not for API/UI development.
