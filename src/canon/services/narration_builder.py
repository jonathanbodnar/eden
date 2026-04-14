"""Narration-packet-builder: creates structured narration content for each chapter.
Uses Anthropic to generate intro/core/branch summaries from canon data."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_branch import CanonBranch
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.narration_packet import NarrationPacket
from src.canon.models.enums import CanonicalType

logger = logging.getLogger(__name__)

NARRATION_SYSTEM_PROMPT = """You are a scholarly narrator for an interactive historical/mythological experience.
Given structured data about a chapter (time period, actors, events, places, branches),
produce a narration packet with:
- intro_summary: 2-3 sentences setting the scene for this time period
- core_summary: 3-5 sentences describing the main events and actors
- branch_summary: 1-2 sentences noting alternative interpretations or uncertain elements (if any)

Write in an authoritative but accessible tone. Preserve ambiguity where sources disagree.
Do NOT fabricate details not present in the input data."""

NARRATION_TOOL = {
    "name": "create_narration",
    "description": "Create a structured narration packet for a chapter.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intro_summary": {"type": "string"},
            "core_summary": {"type": "string"},
            "branch_summary": {"type": "string"},
        },
        "required": ["intro_summary", "core_summary", "branch_summary"],
    },
}


class NarrationBuilderService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def _gather_chapter_data(
        self, session: AsyncSession, chapter: CanonicalChapter
    ) -> dict:
        """Gather all canonical data for a chapter."""
        epoch = await session.get(CanonicalEpoch, chapter.epoch_id)

        deps_q = select(CanonDependency).where(
            CanonDependency.parent_type == CanonicalType.CHAPTER,
            CanonDependency.parent_id == chapter.id,
        )
        deps = (await session.execute(deps_q)).scalars().all()

        actors, events, places = [], [], []
        for dep in deps:
            if dep.child_type == CanonicalType.ACTOR:
                a = await session.get(CanonicalActor, dep.child_id)
                if a and a.is_current:
                    actors.append(a)
            elif dep.child_type == CanonicalType.EVENT:
                e = await session.get(CanonicalEvent, dep.child_id)
                if e and e.is_current:
                    events.append(e)
            elif dep.child_type == CanonicalType.PLACE:
                p = await session.get(CanonicalPlace, dep.child_id)
                if p and p.is_current:
                    places.append(p)

        branches_q = select(CanonBranch).where(
            CanonBranch.parent_type == CanonicalType.CHAPTER,
            CanonBranch.parent_id == chapter.id,
            CanonBranch.is_current.is_(True),
        )
        branches = (await session.execute(branches_q)).scalars().all()

        return {
            "epoch": epoch,
            "chapter": chapter,
            "actors": actors,
            "events": events,
            "places": places,
            "branches": branches,
        }

    def _build_narration_prompt(self, data: dict) -> str:
        """Build a prompt describing the chapter for narration generation."""
        ch = data["chapter"]
        parts = [f"Chapter: {ch.title}"]

        if data["epoch"]:
            parts.append(f"Epoch: {data['epoch'].title}")
        if ch.time_start is not None or ch.time_end is not None:
            parts.append(f"Time period: {ch.time_start or '?'} to {ch.time_end or '?'}")

        if data["actors"]:
            parts.append("\nActors:")
            for a in data["actors"]:
                parts.append(f"  - {a.canonical_name} ({a.actor_type.value}): {a.summary or 'No summary'}")

        if data["events"]:
            parts.append("\nEvents:")
            for e in data["events"]:
                parts.append(f"  - {e.canonical_name} ({e.event_type.value}): {e.summary or 'No summary'}")

        if data["places"]:
            parts.append("\nPlaces:")
            for p in data["places"]:
                parts.append(f"  - {p.canonical_name} ({p.place_type.value}): {p.summary or 'No summary'}")

        if data["branches"]:
            parts.append("\nAlternative interpretations:")
            for b in data["branches"]:
                parts.append(f"  - {b.branch_title}: {b.branch_reason or ''}")

        return "\n".join(parts)

    async def _generate_narration_llm(self, prompt: str) -> dict:
        """Use Anthropic to generate narration content."""
        if not settings.anthropic_api_key:
            return {
                "intro_summary": "Narration generation requires Anthropic API key.",
                "core_summary": "",
                "branch_summary": "",
            }

        try:
            response = await self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=NARRATION_SYSTEM_PROMPT,
                tools=[NARRATION_TOOL],
                tool_choice={"type": "tool", "name": "create_narration"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "create_narration":
                    return block.input
        except Exception:
            logger.exception("Narration LLM call failed")

        return {"intro_summary": "", "core_summary": "", "branch_summary": ""}

    def _generate_narration_rules(self, data: dict) -> dict:
        """Rule-based fallback narration when LLM is unavailable."""
        ch = data["chapter"]
        actor_names = [a.canonical_name for a in data["actors"][:5]]
        event_names = [e.canonical_name for e in data["events"][:5]]
        place_names = [p.canonical_name for p in data["places"][:5]]

        intro = f"This chapter covers the period of {ch.title}."
        if place_names:
            intro += f" Key locations include {', '.join(place_names)}."

        core_parts = []
        if actor_names:
            core_parts.append(f"Notable figures: {', '.join(actor_names)}.")
        if event_names:
            core_parts.append(f"Significant events: {', '.join(event_names)}.")
        core = " ".join(core_parts) if core_parts else "No detailed canon data available yet."

        branch = ""
        if data["branches"]:
            branch = "Alternative interpretations exist: " + "; ".join(
                b.branch_title for b in data["branches"][:3]
            )

        return {"intro_summary": intro, "core_summary": core, "branch_summary": branch}

    async def build_packet_for_chapter(
        self, session: AsyncSession, chapter: CanonicalChapter
    ) -> NarrationPacket:
        """Build or update a narration packet for a single chapter."""
        data = await self._gather_chapter_data(session, chapter)

        if settings.anthropic_api_key:
            prompt = self._build_narration_prompt(data)
            narration = await self._generate_narration_llm(prompt)
        else:
            narration = self._generate_narration_rules(data)

        existing_q = select(NarrationPacket).where(
            NarrationPacket.chapter_id == chapter.id
        ).order_by(NarrationPacket.version.desc()).limit(1)
        existing = (await session.execute(existing_q)).scalar_one_or_none()

        actor_ids = [str(a.id) for a in data["actors"]]
        event_ids = [str(e.id) for e in data["events"]]
        place_ids = [str(p.id) for p in data["places"]]

        if existing:
            existing.intro_summary = narration["intro_summary"]
            existing.core_summary = narration["core_summary"]
            existing.branch_summary = narration["branch_summary"]
            existing.key_actor_ids_json = actor_ids
            existing.key_event_ids_json = event_ids
            existing.key_place_ids_json = place_ids
            existing.version += 1
            return existing

        packet = NarrationPacket(
            id=uuid.uuid4(),
            chapter_id=chapter.id,
            intro_summary=narration["intro_summary"],
            core_summary=narration["core_summary"],
            branch_summary=narration["branch_summary"],
            key_actor_ids_json=actor_ids,
            key_event_ids_json=event_ids,
            key_place_ids_json=place_ids,
            version=1,
        )
        session.add(packet)
        return packet

    async def run_full_build(self, session: AsyncSession) -> dict:
        """Build narration packets for all current chapters."""
        q = select(CanonicalChapter).where(CanonicalChapter.is_current.is_(True))
        chapters = (await session.execute(q)).scalars().all()

        built = 0
        for ch in chapters:
            await self.build_packet_for_chapter(session, ch)
            built += 1

        await session.flush()
        logger.info("Built %d narration packets", built)
        return {"narration_packets_built": built}
