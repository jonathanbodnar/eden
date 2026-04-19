"""GPU Image Generation Worker: submits jobs to RunPod Serverless for SDXL generation.

Architecture: RunPod Serverless — spins up a GPU pod on demand, processes the batch,
shuts down when done. Pay only for compute time used.

Workflow per job:
  1. Submit to RunPod endpoint with ComfyUI workflow JSON
  2. Poll for completion
  3. Download result image
  4. Upload to R2
  5. Update job record with result URL
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.image_generation_job import ImageGenerationJob

logger = logging.getLogger(__name__)

RUNPOD_BASE = "https://api.runpod.ai/v2"
POLL_INTERVAL = 5
MAX_POLL_ATTEMPTS = 120


def _build_comfyui_workflow(job: ImageGenerationJob) -> dict:
    """Build a ComfyUI workflow JSON for SDXL + ControlNet + IP Adapter."""
    style_cfg = job.style_config or {}
    ref_urls = job.reference_image_urls or []

    workflow = {
        "input": {
            "workflow_type": "sdxl_with_addons",
            "positive_prompt": job.prompt_text,
            "negative_prompt": job.negative_prompt or "",
            "width": job.width,
            "height": job.height,
            "steps": 30,
            "cfg_scale": 7.0,
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "seed": -1,
            "lora": {
                "name": style_cfg.get("lora", ""),
                "weight": 0.7,
            } if style_cfg.get("lora") else None,
            "controlnet": {
                "type": style_cfg.get("controlnet", "depth"),
                "weight": 0.5,
            } if style_cfg.get("controlnet") and ref_urls else None,
            "ip_adapter": {
                "reference_images": ref_urls[:4],
                "weight": style_cfg.get("ip_adapter_weight", 0.35),
            } if ref_urls else None,
        }
    }
    return workflow


class ImageGenWorker:

    async def _submit_job(self, client: httpx.AsyncClient, job: ImageGenerationJob) -> str | None:
        """Submit a single job to RunPod and return the run ID."""
        if not settings.runpod_api_key or not settings.runpod_endpoint_id:
            logger.warning("RunPod not configured — skipping image generation")
            return None

        workflow = _build_comfyui_workflow(job)
        url = f"{RUNPOD_BASE}/{settings.runpod_endpoint_id}/run"
        headers = {"Authorization": f"Bearer {settings.runpod_api_key}"}

        try:
            resp = await client.post(url, json=workflow, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("id")
        except Exception:
            logger.exception("Failed to submit job %s to RunPod", job.id)
            return None

    async def _poll_result(self, client: httpx.AsyncClient, run_id: str) -> dict | None:
        """Poll RunPod for job completion."""
        url = f"{RUNPOD_BASE}/{settings.runpod_endpoint_id}/status/{run_id}"
        headers = {"Authorization": f"Bearer {settings.runpod_api_key}"}

        for attempt in range(MAX_POLL_ATTEMPTS):
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                status = data.get("status")
                if status == "COMPLETED":
                    return data.get("output", {})
                if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    logger.error("RunPod job %s failed: %s", run_id, status)
                    return None

                await asyncio.sleep(POLL_INTERVAL)
            except Exception:
                logger.exception("Error polling RunPod job %s", run_id)
                await asyncio.sleep(POLL_INTERVAL)

        logger.error("RunPod job %s timed out after %d attempts", run_id, MAX_POLL_ATTEMPTS)
        return None

    async def process_job(self, session: AsyncSession, job: ImageGenerationJob) -> bool:
        """Process a single image generation job end-to-end."""
        await session.execute(
            update(ImageGenerationJob)
            .where(ImageGenerationJob.id == job.id)
            .values(status="generating")
        )
        await session.flush()

        async with httpx.AsyncClient(timeout=30.0) as client:
            run_id = await self._submit_job(client, job)
            if not run_id:
                await session.execute(
                    update(ImageGenerationJob)
                    .where(ImageGenerationJob.id == job.id)
                    .values(status="failed", error_message="Failed to submit to RunPod")
                )
                return False

            output = await self._poll_result(client, run_id)
            if not output:
                await session.execute(
                    update(ImageGenerationJob)
                    .where(ImageGenerationJob.id == job.id)
                    .values(status="failed", error_message="RunPod job failed or timed out")
                )
                return False

            image_url = output.get("image_url") or output.get("images", [{}])[0].get("url", "")
            r2_key = f"{settings.image_r2_prefix}/{job.story_chapter_id}/{job.id}.png"

            await session.execute(
                update(ImageGenerationJob)
                .where(ImageGenerationJob.id == job.id)
                .values(
                    status="completed",
                    result_url=image_url,
                    result_r2_key=r2_key,
                )
            )
            return True

    async def process_all_pending(self, session: AsyncSession, batch_size: int = 10) -> dict:
        """Process all pending image generation jobs."""
        q = select(ImageGenerationJob).where(
            ImageGenerationJob.status == "pending"
        ).order_by(ImageGenerationJob.created_at).limit(batch_size)

        jobs = (await session.execute(q)).scalars().all()
        if not jobs:
            return {"processed": 0, "succeeded": 0, "failed": 0}

        succeeded = 0
        failed = 0
        for job in jobs:
            ok = await self.process_job(session, job)
            if ok:
                succeeded += 1
            else:
                failed += 1
            await session.flush()

        logger.info("Processed %d image jobs: %d succeeded, %d failed", len(jobs), succeeded, failed)
        return {"processed": len(jobs), "succeeded": succeeded, "failed": failed}
