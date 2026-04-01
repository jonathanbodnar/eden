"""AI-assisted source intake endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.enums import IntakeStatus
from src.ingestion.models.source_intake_run import SourceIntakeRun
from src.ingestion.schemas.intake import (
    IntakeAnalyzeRequest,
    IntakeAnalyzeResponse,
    IntakeRunResponse,
)
from src.ingestion.services.source_intake import analyze_urls

router = APIRouter()


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
