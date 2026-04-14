"""Canon-synth-service: groups extracted hints by similarity,
creates canonical actors/events/places with support links."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.extracted_hint import ExtractedHint
from src.canon.models.enums import (
    ActorType,
    ArchiveObjectType,
    CanonicalType,
    EventType,
    HintType,
    PlaceType,
    SupportType,
)

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalize a name for grouping: lowercase, strip whitespace/diacritics."""
    return name.strip().lower()


def _infer_actor_type(hints: list[ExtractedHint]) -> ActorType:
    """Infer actor type from hint descriptions using keyword matching."""
    combined = " ".join((h.description or "") + " " + h.name for h in hints).lower()
    if any(w in combined for w in ["god", "goddess", "deity", "divine"]):
        return ActorType.DEITY
    if any(w in combined for w in ["king", "ruler", "pharaoh", "emperor", "queen"]):
        return ActorType.RULER
    if any(w in combined for w in ["hero", "mythic", "legend", "demigod"]):
        return ActorType.MYTHIC_FIGURE
    if any(w in combined for w in ["people", "tribe", "nation", "army"]):
        return ActorType.COLLECTIVE
    return ActorType.UNKNOWN


def _infer_event_type(hints: list[ExtractedHint]) -> EventType:
    combined = " ".join((h.description or "") + " " + h.name for h in hints).lower()
    if any(w in combined for w in ["creat", "genesis", "origin"]):
        return EventType.CREATION
    if any(w in combined for w in ["flood", "deluge"]):
        return EventType.FLOOD
    if any(w in combined for w in ["war", "battle", "siege", "conquest"]):
        return EventType.WAR
    if any(w in combined for w in ["migrat", "exodus", "journey"]):
        return EventType.MIGRATION
    if any(w in combined for w in ["found", "establish", "built"]):
        return EventType.FOUNDING
    if any(w in combined for w in ["ritual", "ceremony", "sacrifice"]):
        return EventType.RITUAL
    if any(w in combined for w in ["death", "die", "slay", "kill"]):
        return EventType.DEATH
    return EventType.UNKNOWN


def _infer_place_type(hints: list[ExtractedHint]) -> PlaceType:
    combined = " ".join((h.description or "") + " " + h.name for h in hints).lower()
    if any(w in combined for w in ["city", "ur ", "uruk", "babylon", "nineveh"]):
        return PlaceType.CITY
    if any(w in combined for w in ["temple", "shrine", "sanctuary"]):
        return PlaceType.TEMPLE
    if any(w in combined for w in ["river", "tigris", "euphrates", "nile"]):
        return PlaceType.RIVER
    if any(w in combined for w in ["mountain", "mount"]):
        return PlaceType.MOUNTAIN
    if any(w in combined for w in ["underworld", "netherworld", "kur"]):
        return PlaceType.UNDERWORLD
    if any(w in combined for w in ["heaven", "sky", "celestial"]):
        return PlaceType.CELESTIAL
    return PlaceType.UNKNOWN


class CanonSynthService:
    async def get_unmerged_hints(
        self, session: AsyncSession, hint_type: HintType | None = None
    ) -> list[ExtractedHint]:
        q = select(ExtractedHint).where(ExtractedHint.merged_into_id.is_(None))
        if hint_type:
            q = q.where(ExtractedHint.hint_type == hint_type)
        q = q.order_by(ExtractedHint.name)
        result = await session.execute(q)
        return list(result.scalars().all())

    def group_hints_by_name(self, hints: list[ExtractedHint]) -> dict[str, list[ExtractedHint]]:
        """Group hints by normalized name. Level 1 merge (alias)."""
        groups: dict[str, list[ExtractedHint]] = defaultdict(list)
        for h in hints:
            key = _normalize_name(h.name)
            groups[key].append(h)
        return dict(groups)

    def _best_description(self, hints: list[ExtractedHint]) -> str:
        """Pick the longest description as the most informative."""
        descriptions = [h.description for h in hints if h.description]
        if not descriptions:
            return ""
        return max(descriptions, key=len)

    def _time_range(self, hints: list[ExtractedHint]) -> tuple[int | None, int | None]:
        starts = [h.time_start for h in hints if h.time_start is not None]
        ends = [h.time_end for h in hints if h.time_end is not None]
        return (min(starts) if starts else None, max(ends) if ends else None)

    def _avg_confidence(self, hints: list[ExtractedHint]) -> float:
        confs = [h.confidence for h in hints]
        return sum(confs) / len(confs) if confs else 0.5

    async def synthesize_actors(self, session: AsyncSession) -> list[CanonicalActor]:
        """Create canonical actors from actor hints."""
        hints = await self.get_unmerged_hints(session, HintType.ACTOR)
        groups = self.group_hints_by_name(hints)
        actors = []

        for norm_name, group in groups.items():
            best_name = group[0].name
            for h in group:
                if len(h.name) > len(best_name):
                    best_name = h.name

            t_start, t_end = self._time_range(group)
            actor = CanonicalActor(
                id=uuid.uuid4(),
                canonical_name=best_name,
                actor_type=_infer_actor_type(group),
                summary=self._best_description(group),
                time_start=t_start,
                time_end=t_end,
                merge_confidence=self._avg_confidence(group),
                version=1,
                is_current=True,
            )
            session.add(actor)
            actors.append(actor)

            for h in group:
                h.merged_into_id = actor.id
                archive_id = h.source_segment_id or h.source_statement_id or h.source_record_id
                if archive_id is None:
                    continue
                link = CanonSupportLink(
                    id=uuid.uuid4(),
                    canonical_type=CanonicalType.ACTOR,
                    canonical_id=actor.id,
                    archive_object_type=(
                        ArchiveObjectType.SEGMENT if h.source_segment_id
                        else ArchiveObjectType.CONTEXTUAL_STATEMENT if h.source_statement_id
                        else ArchiveObjectType.SOURCE_RECORD
                    ),
                    archive_object_id=archive_id,
                    support_type=SupportType.PRIMARY_EVIDENCE,
                    weight=h.confidence,
                )
                session.add(link)

        await session.flush()
        logger.info("Synthesized %d canonical actors from %d hints", len(actors), len(hints))
        return actors

    async def synthesize_events(self, session: AsyncSession) -> list[CanonicalEvent]:
        hints = await self.get_unmerged_hints(session, HintType.EVENT)
        groups = self.group_hints_by_name(hints)
        events = []

        for norm_name, group in groups.items():
            best_name = group[0].name
            for h in group:
                if len(h.name) > len(best_name):
                    best_name = h.name

            t_start, t_end = self._time_range(group)
            event = CanonicalEvent(
                id=uuid.uuid4(),
                canonical_name=best_name,
                event_type=_infer_event_type(group),
                summary=self._best_description(group),
                time_start=t_start,
                time_end=t_end,
                merge_confidence=self._avg_confidence(group),
                version=1,
                is_current=True,
            )
            session.add(event)
            events.append(event)

            for h in group:
                h.merged_into_id = event.id
                archive_id = h.source_segment_id or h.source_statement_id or h.source_record_id
                if archive_id is None:
                    continue
                link = CanonSupportLink(
                    id=uuid.uuid4(),
                    canonical_type=CanonicalType.EVENT,
                    canonical_id=event.id,
                    archive_object_type=(
                        ArchiveObjectType.SEGMENT if h.source_segment_id
                        else ArchiveObjectType.CONTEXTUAL_STATEMENT if h.source_statement_id
                        else ArchiveObjectType.SOURCE_RECORD
                    ),
                    archive_object_id=archive_id,
                    support_type=SupportType.PRIMARY_EVIDENCE,
                    weight=h.confidence,
                )
                session.add(link)

        await session.flush()
        logger.info("Synthesized %d canonical events from %d hints", len(events), len(hints))
        return events

    async def synthesize_places(self, session: AsyncSession) -> list[CanonicalPlace]:
        hints = await self.get_unmerged_hints(session, HintType.PLACE)
        groups = self.group_hints_by_name(hints)
        places = []

        for norm_name, group in groups.items():
            best_name = group[0].name
            for h in group:
                if len(h.name) > len(best_name):
                    best_name = h.name

            t_start, t_end = self._time_range(group)
            place = CanonicalPlace(
                id=uuid.uuid4(),
                canonical_name=best_name,
                place_type=_infer_place_type(group),
                summary=self._best_description(group),
                time_start=t_start,
                time_end=t_end,
                merge_confidence=self._avg_confidence(group),
                version=1,
                is_current=True,
            )
            session.add(place)
            places.append(place)

            for h in group:
                h.merged_into_id = place.id
                archive_id = h.source_segment_id or h.source_statement_id or h.source_record_id
                if archive_id is None:
                    continue
                link = CanonSupportLink(
                    id=uuid.uuid4(),
                    canonical_type=CanonicalType.PLACE,
                    canonical_id=place.id,
                    archive_object_type=(
                        ArchiveObjectType.SEGMENT if h.source_segment_id
                        else ArchiveObjectType.CONTEXTUAL_STATEMENT if h.source_statement_id
                        else ArchiveObjectType.SOURCE_RECORD
                    ),
                    archive_object_id=archive_id,
                    support_type=SupportType.PRIMARY_EVIDENCE,
                    weight=h.confidence,
                )
                session.add(link)

        await session.flush()
        logger.info("Synthesized %d canonical places from %d hints", len(places), len(hints))
        return places

    async def run_full_synthesis(self, session: AsyncSession) -> dict:
        actors = await self.synthesize_actors(session)
        events = await self.synthesize_events(session)
        places = await self.synthesize_places(session)
        return {
            "actors": len(actors),
            "events": len(events),
            "places": len(places),
        }
