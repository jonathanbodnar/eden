"""Image Prompt Builder: constructs rich SDXL prompts from narrative + world packets + visual refs.

For each chapter's image_prompts_json entries, builds:
  - Positive prompt incorporating world environment, materials, and scene description
  - Negative prompt for quality control
  - Reference image URLs from matching object_images for IP Adapter input
  - Style config for ControlNet / LoRA settings
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.image_generation_job import ImageGenerationJob
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.world_packet import WorldPacket
from src.canon.models.system_a import SAObjectImage, SASourceRecord, SARawObject, SASourceDate

logger = logging.getLogger(__name__)

NEGATIVE_PROMPT = (
    "modern clothing, modern buildings, cars, electricity, plastic, "
    "cartoon, anime, 3d render, low quality, blurry, text, watermark, "
    "logo, signature, deformed, ugly, mutation, extra limbs, "
    "photorealistic modern person, stock photo, digital art style"
)

STYLE_LORA_TAG = "ancient_world_cinematic_v1"


class ImagePromptBuilder:

    async def _find_reference_images(
        self, session: AsyncSession, chapter: CanonicalChapter,
        scene_description: str, max_refs: int = 4
    ) -> list[str]:
        """Find relevant visual reference images from object_images
        matching the chapter's culture/time period."""
        time_start = chapter.time_start
        time_end = chapter.time_end

        q = (
            select(SAObjectImage.image_url)
            .select_from(SAObjectImage)
            .join(SARawObject, SARawObject.id == SAObjectImage.raw_object_id)
            .join(SASourceRecord, SASourceRecord.raw_object_id == SARawObject.id)
            .where(SARawObject.r2_key.like("visual-library/%"))
        )

        if time_start is not None and time_end is not None:
            q = q.join(
                SASourceDate,
                SASourceDate.source_record_id == SASourceRecord.id,
            ).where(
                SASourceDate.date_start <= time_end + 1000,
                SASourceDate.date_end >= time_start - 1000,
            )

        q = q.order_by(func.random()).limit(max_refs)

        try:
            result = await session.execute(q)
            return [row[0] for row in result.all()]
        except Exception:
            logger.exception("Failed to find reference images")
            return []

    def _build_positive_prompt(
        self, scene: dict, world_packet: WorldPacket | None
    ) -> str:
        """Construct a detailed positive prompt from scene description + world context."""
        parts = [
            "masterpiece, best quality, highly detailed, cinematic lighting,",
            "ancient world, historical accuracy, archaeological accuracy,",
        ]

        parts.append(scene.get("description", "ancient scene"))

        if scene.get("mood"):
            parts.append(f"{scene['mood']} atmosphere,")
        if scene.get("period"):
            parts.append(f"{scene['period']} era,")

        if world_packet:
            env = world_packet.environment_profile_json or {}
            if isinstance(env, dict):
                if env.get("landscape"):
                    parts.append(f"{env['landscape']} landscape,")
                if env.get("climate"):
                    parts.append(f"{env['climate']} climate,")
                if env.get("sky"):
                    parts.append(f"{env['sky']} sky,")

            mat = world_packet.material_culture_json or {}
            if isinstance(mat, dict):
                if mat.get("architecture"):
                    parts.append(f"{mat['architecture']} architecture,")
                if mat.get("materials"):
                    parts.append(f"built with {mat['materials']},")

        parts.append("epic scale, wide angle, volumetric lighting, matte painting style")

        return " ".join(parts)

    async def build_jobs_for_chapter(
        self, session: AsyncSession, story_chapter: StoryChapter
    ) -> list[ImageGenerationJob]:
        """Build image generation jobs for a story chapter's image prompts."""
        image_prompts = story_chapter.image_prompts_json or []
        if not image_prompts:
            return []

        chapter = await session.get(CanonicalChapter, story_chapter.chapter_id)
        if not chapter:
            return []

        wp_q = select(WorldPacket).where(
            WorldPacket.chapter_id == chapter.id
        ).order_by(WorldPacket.packet_version.desc()).limit(1)
        world_packet = (await session.execute(wp_q)).scalar_one_or_none()

        existing_q = select(func.count(ImageGenerationJob.id)).where(
            ImageGenerationJob.story_chapter_id == story_chapter.id,
            ImageGenerationJob.status != "failed",
        )
        existing_count = (await session.execute(existing_q)).scalar() or 0
        if existing_count >= len(image_prompts):
            return []

        jobs = []
        for i, scene in enumerate(image_prompts):
            if not isinstance(scene, dict):
                continue

            existing_job_q = select(ImageGenerationJob).where(
                ImageGenerationJob.story_chapter_id == story_chapter.id,
                ImageGenerationJob.prompt_text.contains(scene.get("description", "")[:100]),
            )
            if (await session.execute(existing_job_q)).scalar_one_or_none():
                continue

            positive = self._build_positive_prompt(scene, world_packet)
            ref_images = await self._find_reference_images(
                session, chapter, scene.get("description", ""), max_refs=4
            )

            job = ImageGenerationJob(
                id=uuid.uuid4(),
                story_chapter_id=story_chapter.id,
                prompt_text=positive,
                negative_prompt=NEGATIVE_PROMPT,
                reference_image_urls=ref_images,
                style_config={
                    "lora": STYLE_LORA_TAG,
                    "controlnet": "depth" if ref_images else None,
                    "ip_adapter_weight": 0.35 if ref_images else 0.0,
                    "scene_index": i,
                },
                status="pending",
                width=1344,
                height=768,
            )
            session.add(job)
            jobs.append(job)

        await session.flush()
        return jobs

    async def build_all_pending(self, session: AsyncSession) -> dict:
        """Build image generation jobs for all story chapters that have prompts."""
        sc_q = select(StoryChapter).where(
            StoryChapter.image_prompts_json.isnot(None)
        )
        story_chapters = (await session.execute(sc_q)).scalars().all()

        total_jobs = 0
        for sc in story_chapters:
            jobs = await self.build_jobs_for_chapter(session, sc)
            total_jobs += len(jobs)

        await session.flush()
        logger.info("Built %d image generation jobs", total_jobs)
        return {"jobs_created": total_jobs}
