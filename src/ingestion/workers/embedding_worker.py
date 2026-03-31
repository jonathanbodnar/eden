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
        last_segment_id = None
        records_processed = 0
        if checkpoint:
            last_segment_id = checkpoint.external_id_last_processed
            records_processed = checkpoint.records_processed

        query = (
            select(Segment)
            .where(Segment.review_status != ReviewStatus.REJECTED)
            .order_by(Segment.created_at)
        )

        result = await session.execute(query)
        segments = result.scalars().all()

        skip = True if last_segment_id else False
        to_embed = []

        for seg in segments:
            if skip:
                if str(seg.id) == last_segment_id:
                    skip = False
                continue

            existing = await session.execute(
                select(Embedding).where(Embedding.segment_id == seg.id).limit(1)
            )
            if existing.scalar_one_or_none():
                records_processed += 1
                continue

            text = seg.normalized_text or seg.original_text
            if not text or not text.strip():
                records_processed += 1
                continue

            to_embed.append(seg)

            if len(to_embed) >= BATCH_SIZE:
                await self._embed_batch(session, to_embed)
                records_processed += len(to_embed)
                to_embed = []

                await self.maybe_checkpoint(
                    session, job,
                    checkpoint_type="embed",
                    external_id_last_processed=str(seg.id),
                    records_processed=records_processed,
                )

        if to_embed:
            await self._embed_batch(session, to_embed)
            records_processed += len(to_embed)

        await self.maybe_checkpoint(
            session, job,
            checkpoint_type="embed",
            records_processed=records_processed,
            stage_percent=100.0,
            force=True,
        )

        await update_source_progress(
            session,
            job.trusted_source_id,
            embedded_count=records_processed,
        )
        await session.commit()

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
