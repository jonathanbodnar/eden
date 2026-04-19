"""Context layer endpoints: CRUD and review for contextual statements."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.database import get_session
from src.ingestion.models.contextual_statement import ContextualStatement
from src.ingestion.models.enums import ContextType, ExtractionMethod, ReviewStatus, StatementConfidence
from src.ingestion.schemas.context import (
    ContextStats,
    ContextualStatementCreate,
    ContextualStatementListResponse,
    ContextualStatementResponse,
    ContextualStatementUpdate,
    ReviewBatchRequest,
)

router = APIRouter()


@router.get("/statements", response_model=ContextualStatementListResponse)
async def list_statements(
    source_record_id: uuid.UUID | None = Query(None),
    segment_id: uuid.UUID | None = Query(None),
    context_type: ContextType | None = Query(None),
    confidence: StatementConfidence | None = Query(None),
    review_status: ReviewStatus | None = Query(None),
    extraction_method: ExtractionMethod | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    query = select(ContextualStatement)
    count_query = select(func.count(ContextualStatement.id))

    filters = []
    if source_record_id:
        filters.append(ContextualStatement.source_record_id == source_record_id)
    if segment_id:
        filters.append(ContextualStatement.segment_id == segment_id)
    if context_type:
        filters.append(ContextualStatement.context_type == context_type)
    if confidence:
        filters.append(ContextualStatement.confidence == confidence)
    if review_status:
        filters.append(ContextualStatement.review_status == review_status)
    if extraction_method:
        filters.append(ContextualStatement.extraction_method == extraction_method)

    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)

    query = query.order_by(ContextualStatement.created_at.desc()).offset(offset).limit(limit)

    total = (await session.execute(count_query)).scalar() or 0
    items = (await session.execute(query)).scalars().all()

    return ContextualStatementListResponse(
        items=[ContextualStatementResponse.model_validate(s) for s in items],
        total=total,
    )


@router.get("/stats", response_model=ContextStats)
async def get_stats(session: AsyncSession = Depends(get_session)):
    total = (await session.execute(
        select(func.count(ContextualStatement.id))
    )).scalar() or 0

    type_rows = (await session.execute(
        select(ContextualStatement.context_type, func.count(ContextualStatement.id))
        .group_by(ContextualStatement.context_type)
    )).all()

    confidence_rows = (await session.execute(
        select(ContextualStatement.confidence, func.count(ContextualStatement.id))
        .group_by(ContextualStatement.confidence)
    )).all()

    review_rows = (await session.execute(
        select(ContextualStatement.review_status, func.count(ContextualStatement.id))
        .group_by(ContextualStatement.review_status)
    )).all()

    method_rows = (await session.execute(
        select(ContextualStatement.extraction_method, func.count(ContextualStatement.id))
        .group_by(ContextualStatement.extraction_method)
    )).all()

    return ContextStats(
        total=total,
        by_type={str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in type_rows},
        by_confidence={str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in confidence_rows},
        by_review_status={str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in review_rows},
        by_extraction_method={str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in method_rows},
    )


@router.get("/statements/{statement_id}", response_model=ContextualStatementResponse)
async def get_statement(
    statement_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    stmt = await session.get(ContextualStatement, statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")
    return ContextualStatementResponse.model_validate(stmt)


@router.post("/statements", response_model=ContextualStatementResponse, status_code=201)
async def create_statement(
    body: ContextualStatementCreate,
    session: AsyncSession = Depends(get_session),
):
    statement = ContextualStatement(**body.model_dump())
    session.add(statement)
    await session.commit()
    await session.refresh(statement)
    return ContextualStatementResponse.model_validate(statement)


@router.patch("/statements/{statement_id}", response_model=ContextualStatementResponse)
async def update_statement(
    statement_id: uuid.UUID,
    body: ContextualStatementUpdate,
    session: AsyncSession = Depends(get_session),
):
    stmt = await session.get(ContextualStatement, statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(stmt, key, value)

    await session.commit()
    await session.refresh(stmt)
    return ContextualStatementResponse.model_validate(stmt)


@router.post("/statements/review", response_model=dict)
async def batch_review(
    body: ReviewBatchRequest,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        update(ContextualStatement)
        .where(ContextualStatement.id.in_(body.ids))
        .values(review_status=body.review_status)
        .returning(ContextualStatement.id)
    )
    updated_ids = [row[0] for row in result.fetchall()]
    await session.commit()
    return {"updated": len(updated_ids), "ids": [str(uid) for uid in updated_ids]}
