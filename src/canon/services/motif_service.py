"""Motif-service: assigns motifs to canonical entities using keyword matching + LLM classification."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.enums import CanonicalType
from src.canon.models.motif import Motif, MotifAssignment

logger = logging.getLogger(__name__)

SEED_MOTIFS = [
    ("flood", "Great flood or deluge narrative — divine punishment, survival, renewal"),
    ("creation", "Cosmogonic creation narrative — primordial waters, divine speech, separation of elements"),
    ("descent", "Descent to the underworld — death, rebirth, liminal passage"),
    ("divine_kingship", "Sacred kingship — divine mandate, shepherd metaphor, temple-building"),
    ("sacred_garden", "Paradise or sacred garden — Edenic space, tree of life, forbidden knowledge"),
    ("sky_beings", "Celestial beings or sky gods — heavenly council, astral deities"),
    ("trickster", "Trickster figure — cunning, boundary-crossing, culture hero"),
    ("hero_journey", "Hero's journey — quest, trials, transformation, return"),
    ("sacred_marriage", "Hieros gamos — divine or ritual marriage, fertility"),
    ("dying_god", "Dying and rising deity — seasonal cycle, lamentation, resurrection"),
    ("monster_slaying", "Combat with chaos monster — primordial dragon, cosmic order"),
    ("exile", "Exile and return — displacement, wandering, restoration"),
    ("deluge_survivor", "Survivor of catastrophe — chosen one, ark-builder, covenant"),
    ("tower_hubris", "Tower or monument of hubris — overreach, divine punishment, scattering"),
    ("ancestral_lineage", "Genealogy and ancestral lineage — succession lists, dynastic legitimacy"),
]

KEYWORD_MAP: dict[str, list[str]] = {
    "flood": ["flood", "deluge", "inundation", "ziusudra", "utnapishtim", "atrahasis", "noah"],
    "creation": ["creation", "genesis", "cosmogon", "primordial", "enuma elish", "origin"],
    "descent": ["descent", "underworld", "netherworld", "inanna", "kur", "irkalla", "sheol"],
    "divine_kingship": ["king", "kingship", "shepherd", "mandate", "divine right", "lugal"],
    "sacred_garden": ["garden", "eden", "paradise", "dilmun", "tree of life"],
    "sky_beings": ["sky", "heaven", "celestial", "anu", "enlil", "astral"],
    "trickster": ["trickster", "cunning", "enki", "loki", "hermes", "coyote"],
    "hero_journey": ["hero", "quest", "gilgamesh", "trial", "journey"],
    "sacred_marriage": ["marriage", "hieros gamos", "inanna", "dumuzi", "fertility"],
    "dying_god": ["dying god", "tammuz", "dumuzi", "adonis", "resurrection", "lament"],
    "monster_slaying": ["dragon", "tiamat", "monster", "chaos", "marduk", "combat"],
    "exile": ["exile", "wander", "displace", "banish", "scatter"],
    "deluge_survivor": ["ark", "survivor", "ziusudra", "utnapishtim", "atrahasis", "covenant"],
    "tower_hubris": ["tower", "babel", "hubris", "scatter", "language"],
    "ancestral_lineage": ["genealogy", "lineage", "dynasty", "ancestor", "succession", "king list"],
}

MOTIF_CLASSIFICATION_PROMPT = """You are a motif classifier for ancient Near Eastern mythology and history.
Given a canonical entity (actor, event, or place) with its name, type, and summary,
identify which motifs from this list are relevant:

{motif_list}

Return a JSON array of objects with "label" (motif label) and "confidence" (0.0-1.0).
Only include motifs with confidence >= 0.3. Return empty array if no motifs match."""

MOTIF_TOOL = {
    "name": "assign_motifs",
    "description": "Assign motifs to a canonical entity with confidence scores.",
    "input_schema": {
        "type": "object",
        "properties": {
            "motifs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["label", "confidence"],
                },
            }
        },
        "required": ["motifs"],
    },
}


class MotifService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def ensure_seed_motifs(self, session: AsyncSession) -> dict[str, uuid.UUID]:
        """Create seed motifs if they don't exist. Returns label->id map."""
        existing_q = select(Motif)
        existing = {m.label: m.id for m in (await session.execute(existing_q)).scalars().all()}

        for label, description in SEED_MOTIFS:
            if label not in existing:
                motif = Motif(id=uuid.uuid4(), label=label, description=description)
                session.add(motif)
                existing[label] = motif.id

        await session.flush()
        return existing

    def _keyword_match(self, text: str) -> list[tuple[str, float]]:
        """Match motifs using keyword rules. Returns (label, confidence) pairs."""
        text_lower = text.lower()
        matches = []
        for label, keywords in KEYWORD_MAP.items():
            hit_count = sum(1 for kw in keywords if kw in text_lower)
            if hit_count > 0:
                confidence = min(0.4 + (hit_count * 0.15), 0.85)
                matches.append((label, confidence))
        return matches

    async def _llm_classify(self, entity_text: str, motif_labels: list[str]) -> list[tuple[str, float]]:
        """Use Anthropic to classify motifs for an entity."""
        if not settings.anthropic_api_key:
            return []

        motif_list = "\n".join(f"- {label}" for label in motif_labels)
        prompt = MOTIF_CLASSIFICATION_PROMPT.format(motif_list=motif_list)

        try:
            response = await self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=prompt,
                tools=[MOTIF_TOOL],
                tool_choice={"type": "tool", "name": "assign_motifs"},
                messages=[{"role": "user", "content": entity_text}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "assign_motifs":
                    return [(m["label"], m["confidence"]) for m in block.input.get("motifs", [])]
        except Exception:
            logger.exception("LLM motif classification failed")
        return []

    async def assign_motifs_to_entity(
        self,
        session: AsyncSession,
        entity_id: uuid.UUID,
        entity_type: CanonicalType,
        entity_text: str,
        motif_map: dict[str, uuid.UUID],
    ) -> list[MotifAssignment]:
        """Assign motifs to a single entity using keyword + optional LLM."""
        keyword_results = self._keyword_match(entity_text)

        llm_results = []
        if settings.anthropic_api_key:
            llm_results = await self._llm_classify(entity_text, list(motif_map.keys()))

        merged: dict[str, float] = {}
        for label, conf in keyword_results:
            merged[label] = conf
        for label, conf in llm_results:
            if label in merged:
                merged[label] = max(merged[label], conf)
            else:
                merged[label] = conf

        assignments = []
        for label, confidence in merged.items():
            if confidence < 0.3 or label not in motif_map:
                continue
            existing_q = select(MotifAssignment).where(
                MotifAssignment.motif_id == motif_map[label],
                MotifAssignment.target_type == entity_type,
                MotifAssignment.target_id == entity_id,
            )
            if (await session.execute(existing_q)).scalar_one_or_none():
                continue

            assignment = MotifAssignment(
                id=uuid.uuid4(),
                motif_id=motif_map[label],
                target_type=entity_type,
                target_id=entity_id,
                confidence=confidence,
            )
            session.add(assignment)
            assignments.append(assignment)

        return assignments

    async def run_full_motif_assignment(self, session: AsyncSession) -> dict:
        """Run motif assignment across all current canonical entities."""
        motif_map = await self.ensure_seed_motifs(session)
        total_assignments = 0

        actors_q = select(CanonicalActor).where(CanonicalActor.is_current.is_(True))
        for actor in (await session.execute(actors_q)).scalars().all():
            text = f"Actor: {actor.canonical_name} ({actor.actor_type.value})\n{actor.summary or ''}"
            assigns = await self.assign_motifs_to_entity(
                session, actor.id, CanonicalType.ACTOR, text, motif_map
            )
            total_assignments += len(assigns)

        events_q = select(CanonicalEvent).where(CanonicalEvent.is_current.is_(True))
        for event in (await session.execute(events_q)).scalars().all():
            text = f"Event: {event.canonical_name} ({event.event_type.value})\n{event.summary or ''}"
            assigns = await self.assign_motifs_to_entity(
                session, event.id, CanonicalType.EVENT, text, motif_map
            )
            total_assignments += len(assigns)

        places_q = select(CanonicalPlace).where(CanonicalPlace.is_current.is_(True))
        for place in (await session.execute(places_q)).scalars().all():
            text = f"Place: {place.canonical_name} ({place.place_type.value})\n{place.summary or ''}"
            assigns = await self.assign_motifs_to_entity(
                session, place.id, CanonicalType.PLACE, text, motif_map
            )
            total_assignments += len(assigns)

        await session.flush()
        logger.info("Assigned %d motifs total", total_assignments)
        return {"motifs_seeded": len(motif_map), "assignments_created": total_assignments}
