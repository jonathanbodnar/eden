"""AI-assisted source intake endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.enums import IntakeStatus, RunType
from src.ingestion.models.source_intake_run import SourceIntakeRun
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import create_source_run
from src.ingestion.schemas.intake import (
    DomainGroup,
    IntakeAnalyzeRequest,
    IntakeAnalyzeResponse,
    IntakeRunResponse,
)
from src.ingestion.schemas.trusted_source import TrustedSourceResponse
from src.ingestion.services.source_intake import analyze_urls

router = APIRouter()


class BatchApproveRequest(BaseModel):
    groups: list[DomainGroup] = Field(..., min_length=1)


class BatchApproveResponse(BaseModel):
    created: list[TrustedSourceResponse]
    skipped: list[str]


@router.post("/analyze", response_model=IntakeAnalyzeResponse)
async def analyze_intake(
    body: IntakeAnalyzeRequest,
    session: AsyncSession = Depends(get_session),
):
    run = SourceIntakeRun(
        submitted_urls_jsonb={"urls": body.urls},
        status=IntakeStatus.FETCHING,
    )
    session.add(run)
    await session.flush()

    try:
        run.status = IntakeStatus.ANALYZING
        await session.flush()

        groups = await analyze_urls(body.urls)

        run.status = IntakeStatus.COMPLETED
        run.grouped_domains_jsonb = {
            "domains": [g.domain for g in groups],
            "url_count": sum(len(g.urls) for g in groups),
        }
        run.analysis_result_jsonb = {
            "groups": [g.model_dump() for g in groups],
        }
        await session.commit()

        return IntakeAnalyzeResponse(
            id=run.id,
            groups=groups,
            status="completed",
        )

    except Exception as exc:
        run.status = IntakeStatus.FAILED
        run.error_log = str(exc)[:2000]
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Intake analysis failed: {str(exc)[:200]}")


@router.post("/approve-all", response_model=BatchApproveResponse)
async def approve_all_intake(
    body: BatchApproveRequest,
    session: AsyncSession = Depends(get_session),
):
    existing_slugs_result = await session.execute(
        select(TrustedSource.slug).where(
            TrustedSource.slug.in_([g.suggested_source.slug for g in body.groups])
        )
    )
    existing_slugs = set(existing_slugs_result.scalars().all())

    created: list[TrustedSourceResponse] = []
    skipped: list[str] = []

    new_sources: list[TrustedSource] = []

    for group in body.groups:
        s = group.suggested_source
        if s.slug in existing_slugs:
            skipped.append(s.slug)
            continue

        source = TrustedSource(
            name=s.name,
            slug=s.slug,
            domain=s.domain,
            base_url=s.base_url,
            source_category=s.source_category,
            trust_tier=s.trust_tier,
            ingestion_method=s.ingestion_method,
            parser_type=s.parser_type,
            priority=s.priority,
            default_language=s.default_language or None,
            rate_limit_rpm=s.rate_limit_rpm,
            crawl_frequency_hours=s.crawl_frequency_hours,
            license_notes=s.license_notes or None,
            notes=s.notes or None,
            is_secondary_source=s.is_secondary_source,
        )
        session.add(source)
        await session.flush()
        new_sources.append(source)
        existing_slugs.add(s.slug)

    for source in new_sources:
        await create_source_run(
            session,
            trusted_source_id=source.id,
            run_type=RunType.FULL_INGEST,
            requested_by="auto",
            notes="Automatically queued on batch intake approval",
        )

    created = [TrustedSourceResponse.model_validate(src) for src in new_sources]

    return BatchApproveResponse(created=created, skipped=skipped)


@router.get("/runs", response_model=list[IntakeRunResponse])
async def list_intake_runs(
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SourceIntakeRun).order_by(SourceIntakeRun.created_at.desc()).limit(20)
    )
    runs = result.scalars().all()
    return [IntakeRunResponse.model_validate(r) for r in runs]


@router.get("/runs/{run_id}", response_model=IntakeRunResponse)
async def get_intake_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    run = await session.get(SourceIntakeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Intake run not found")
    return IntakeRunResponse.model_validate(run)
