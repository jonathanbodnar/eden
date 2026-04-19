"""World-packet-builder: converts chapters into structured world descriptions
for the AI runtime. Each chapter produces a world packet containing environment,
material culture, symbols, constraints, and key entity references."""

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
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.motif import Motif, MotifAssignment
from src.canon.models.world_packet import WorldPacket
from src.canon.models.enums import CanonicalType

logger = logging.getLogger(__name__)

WORLD_PACKET_SYSTEM_PROMPT = """You are a world-building engine for an interactive historical/mythological experience.
Given a chapter with its actors, events, places, and motifs, produce a structured world packet.
This packet will be used by an AI runtime to generate an explorable 3D environment.

Output a JSON object with these fields:
- world_summary: 2-3 sentence overview of this world state
- environment_profile: landscape, climate, vegetation, water features, sky description
- material_culture: architecture style, materials, tools, clothing, artifacts
- symbol_system: religious symbols, writing systems, iconography, ritual objects
- motifs: recurring thematic patterns present in this chapter
- hard_constraints: facts that MUST be preserved (names, major events, timeline)
- soft_constraints: details that can vary (exact layout, architectural variation, weather)"""

WORLD_PACKET_TOOL = {
    "name": "create_world_packet",
    "description": "Create a structured world packet for runtime visualization.",
    "input_schema": {
        "type": "object",
        "properties": {
            "world_summary": {"type": "string"},
            "environment_profile": {"type": "object"},
            "material_culture": {"type": "object"},
            "symbol_system": {"type": "object"},
            "motifs": {"type": "array", "items": {"type": "string"}},
            "hard_constraints": {"type": "object"},
            "soft_constraints": {"type": "object"},
        },
        "required": [
            "world_summary", "environment_profile", "material_culture",
            "symbol_system", "motifs", "hard_constraints", "soft_constraints",
        ],
    },
}


class WorldPacketBuilderService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def _gather_chapter_context(
        self, session: AsyncSession, chapter: CanonicalChapter
    ) -> dict:
        """Gather full context for world packet generation."""
        epoch = await session.get(CanonicalEpoch, chapter.epoch_id)

        deps_q = select(CanonDependency).where(
            CanonDependency.parent_type == CanonicalType.CHAPTER,
            CanonDependency.parent_id == chapter.id,
        )
        deps = (await session.execute(deps_q)).scalars().all()

        actors, events, places = [], [], []
        all_entity_ids = []
        for dep in deps:
            if dep.child_type == CanonicalType.ACTOR:
                a = await session.get(CanonicalActor, dep.child_id)
                if a and a.is_current:
                    actors.append(a)
                    all_entity_ids.append((CanonicalType.ACTOR, a.id))
            elif dep.child_type == CanonicalType.EVENT:
                e = await session.get(CanonicalEvent, dep.child_id)
                if e and e.is_current:
                    events.append(e)
                    all_entity_ids.append((CanonicalType.EVENT, e.id))
            elif dep.child_type == CanonicalType.PLACE:
                p = await session.get(CanonicalPlace, dep.child_id)
                if p and p.is_current:
                    places.append(p)
                    all_entity_ids.append((CanonicalType.PLACE, p.id))

        motif_labels = set()
        for entity_type, entity_id in all_entity_ids:
            mq = select(MotifAssignment).where(
                MotifAssignment.target_type == entity_type,
                MotifAssignment.target_id == entity_id,
            )
            for ma in (await session.execute(mq)).scalars().all():
                motif = await session.get(Motif, ma.motif_id)
                if motif:
                    motif_labels.add(motif.label)

        return {
            "epoch": epoch,
            "chapter": chapter,
            "actors": actors,
            "events": events,
            "places": places,
            "motif_labels": list(motif_labels),
        }

    def _build_world_prompt(self, data: dict) -> str:
        ch = data["chapter"]
        parts = [f"Chapter: {ch.title}"]

        if data["epoch"]:
            parts.append(f"Epoch: {data['epoch'].title}")
        if ch.time_start is not None:
            parts.append(f"Time range: {ch.time_start} to {ch.time_end or '?'}")

        if data["actors"]:
            parts.append("\nActors:")
            for a in data["actors"]:
                parts.append(f"  - {a.canonical_name} ({a.actor_type.value}): {a.summary or ''}")

        if data["events"]:
            parts.append("\nEvents:")
            for e in data["events"]:
                parts.append(f"  - {e.canonical_name} ({e.event_type.value}): {e.summary or ''}")

        if data["places"]:
            parts.append("\nPlaces:")
            for p in data["places"]:
                geo = p.geo_hint_json or {}
                parts.append(f"  - {p.canonical_name} ({p.place_type.value}): {p.summary or ''}")

        if data["motif_labels"]:
            parts.append(f"\nMotifs: {', '.join(data['motif_labels'])}")

        return "\n".join(parts)

    async def _generate_world_packet_llm(self, prompt: str) -> dict:
        if not settings.anthropic_api_key:
            return self._generate_world_packet_rules_fallback(prompt)

        try:
            response = await self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=WORLD_PACKET_SYSTEM_PROMPT,
                tools=[WORLD_PACKET_TOOL],
                tool_choice={"type": "tool", "name": "create_world_packet"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "create_world_packet":
                    return block.input
        except Exception:
            logger.exception("World packet LLM call failed")

        return self._generate_world_packet_rules_fallback(prompt)

    def _generate_world_packet_rules_fallback(self, prompt: str) -> dict:
        return {
            "world_summary": "World packet generated without LLM. See chapter data for details.",
            "environment_profile": {"description": "Ancient Near Eastern landscape"},
            "material_culture": {"description": "Mesopotamian material culture"},
            "symbol_system": {"description": "Cuneiform and religious iconography"},
            "motifs": [],
            "hard_constraints": {},
            "soft_constraints": {},
        }

    async def build_packet_for_chapter(
        self, session: AsyncSession, chapter: CanonicalChapter
    ) -> WorldPacket:
        data = await self._gather_chapter_context(session, chapter)
        prompt = self._build_world_prompt(data)
        wp_data = await self._generate_world_packet_llm(prompt)

        existing_q = select(WorldPacket).where(
            WorldPacket.chapter_id == chapter.id
        ).order_by(WorldPacket.packet_version.desc()).limit(1)
        existing = (await session.execute(existing_q)).scalar_one_or_none()

        actor_refs = [{"id": str(a.id), "name": a.canonical_name, "type": a.actor_type.value} for a in data["actors"]]
        event_refs = [{"id": str(e.id), "name": e.canonical_name, "type": e.event_type.value} for e in data["events"]]
        place_refs = [{"id": str(p.id), "name": p.canonical_name, "type": p.place_type.value} for p in data["places"]]

        if existing:
            existing.world_summary = wp_data.get("world_summary")
            existing.environment_profile_json = wp_data.get("environment_profile")
            existing.material_culture_json = wp_data.get("material_culture")
            existing.symbol_system_json = wp_data.get("symbol_system")
            existing.motifs_json = wp_data.get("motifs")
            existing.key_actors_json = actor_refs
            existing.key_events_json = event_refs
            existing.key_places_json = place_refs
            existing.hard_constraints_json = wp_data.get("hard_constraints")
            existing.soft_constraints_json = wp_data.get("soft_constraints")
            existing.packet_version += 1
            return existing

        packet = WorldPacket(
            id=uuid.uuid4(),
            chapter_id=chapter.id,
            canon_version=chapter.version,
            packet_version=1,
            time_start=chapter.time_start,
            time_end=chapter.time_end,
            world_summary=wp_data.get("world_summary"),
            environment_profile_json=wp_data.get("environment_profile"),
            material_culture_json=wp_data.get("material_culture"),
            symbol_system_json=wp_data.get("symbol_system"),
            motifs_json=wp_data.get("motifs"),
            key_actors_json=actor_refs,
            key_events_json=event_refs,
            key_places_json=place_refs,
            hard_constraints_json=wp_data.get("hard_constraints"),
            soft_constraints_json=wp_data.get("soft_constraints"),
        )
        session.add(packet)
        return packet

    async def run_full_build(self, session: AsyncSession) -> dict:
        q = select(CanonicalChapter).where(CanonicalChapter.is_current.is_(True))
        chapters = (await session.execute(q)).scalars().all()

        built = 0
        for ch in chapters:
            await self.build_packet_for_chapter(session, ch)
            built += 1

        await session.flush()
        logger.info("Built %d world packets", built)
        return {"world_packets_built": built}
