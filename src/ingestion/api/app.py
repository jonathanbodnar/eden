"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.ingestion.api.routes import archive, jobs, progress, sources
from src.ingestion.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Source-governed ingestion pipeline admin API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources.router, prefix="/admin/sources", tags=["Trusted Sources"])
app.include_router(jobs.router, prefix="/admin/jobs", tags=["Jobs & Queue"])
app.include_router(progress.router, prefix="/admin/progress", tags=["Progress"])
app.include_router(archive.router, prefix="/admin/archive", tags=["Archive Inspection"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.app_name}
