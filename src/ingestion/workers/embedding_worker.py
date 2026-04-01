"""Embedding worker: generates vector embeddings for segments."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.config import settings
from src.ingestion.models.embedding import Embedding
from src.ingestion.models.enums import JobType, ReviewStatus
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.segment import Segment
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    """Calls OpenAI embeddings API."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or settings.embedding_model
        self.api_key = api_key or settings.openai_api_key

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("EDEN_OPENAI_API_KEY not configured")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": texts,
                },
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]


class EmbeddingWorker(BaseWorker):
    job_types = [JobType.EMBED]

    def __init__(
        self,
        worker_id: str | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        super().__init__(worker_id)
        self.provider = provider or OpenAIEmbeddingProvider()

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        import asyncio
        from src.ingestion.queue.manager import is_upstream_done

        records_processed = 0
        empty_polls = 0

        while True:
            result = await session.execute(
                select(Segment)
                .where(Segment.review_status != ReviewStatus.REJECTED)
                .where(~Segment.id.in_(
                    select(Embedding.segment_id)
                ))
                .where(
                    (Segment.normalized_text.isnot(None)) & (Segment.normalized_text != "")
                    | (Segment.original_text.isnot(None)) & (Segment.original_text != "")
                )
                .order_by(Segment.created_at)
                .limit(BATCH_SIZE)
            )
            batch = result.scalars().all()

            if not batch:
                upstream_done = await is_upstream_done(session, job.source_run_id, job.job_type)
                if upstream_done:
                    empty_polls += 1
                    if empty_polls >= 2:
                        logger.info("Embed: upstream done, no more segments")
                        break
                await asyncio.sleep(5.0)
                continue

            empty_polls = 0
            try:
                await self._embed_batch(session, batch)
                records_processed += len(batch)
                await session.commit()
                logger.info("Embed: %d segments embedded (committed)", records_processed)
            except Exception as exc:
                logger.error("Embedding batch failed: %s", exc)
                await session.rollback()
                await asyncio.sleep(10.0)

        await update_source_progress(
            session,
            job.trusted_source_id,
            embedded_count=records_processed,
        )

    async def _embed_batch(
        self,
        session: AsyncSession,
        segments: list[Segment],
    ) -> None:
        texts = [
            (seg.normalized_text or seg.original_text or "").strip()
            for seg in segments
        ]

        try:
            vectors = await self.provider.embed(texts)
        except Exception as exc:
            logger.error("Embedding API call failed: %s", exc)
            raise

        for seg, vector in zip(segments, vectors):
            embedding = Embedding(
                segment_id=seg.id,
                embedding=vector,
                embedding_model=settings.embedding_model,
            )
            session.add(embedding)

        await session.flush()
        logger.info("Embedded batch of %d segments", len(segments))
