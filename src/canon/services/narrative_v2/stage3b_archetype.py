"""Stage 3B — archetype resolution.

For each cluster, determine its `primary_archetype_name` from the global
archetype_registry. If no existing archetype matches, make a one-shot LLM
call to mint a new archetype and write it to the registry.

Resolution order (deterministic → LLM):
  1. Direct name hit in registry.also_known_as
  2. Entity-equivalence hit (via canonical_actors + entity_equivalences)
  3. New archetype — one-shot LLM
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.narrative_v2 import ArchetypeRegistry
from src.canon.services.narrative_v2.llm import call_deepseek

logger = logging.getLogger(__name__)


ARCHETYPE_NAMER_SYSTEM_PROMPT = """You name archetypes for a unified ancient world history.

An archetype is the stable English phrase the unified narrative uses for a role across all cultures. Examples:
  - "The Divine Craftsman" (covers Enki, Ea, Khnum, Ptah, Prometheus)
  - "The Mother of Chaos" (covers Tiamat, Omuroca)
  - "The Primordial Waters" (covers Nu, Apsu, Tehom, Ginnungagap)
  - "The First Man" (covers Adam, Adapa, Manu, Yima, Ymir, Askr)

## RULES

1. The archetype name MUST be a title-case English phrase.
2. NEVER use a culture-specific deity name in the archetype name itself.
3. The name describes a ROLE, not a personality. Think job title, not character.
4. Keep names short: 2-5 words. "The [Adjective] [Noun]" or "[Noun] of the [Noun]" work well.
5. Never reuse another archetype's name. This is a new archetype.
6. The archetype MUST describe a BEING (a deity, primordial entity, mythic figure, or class of beings). Do NOT create archetypes for places, cities, temples, rivers, or inanimate objects. If the contributing names are clearly places/objects (Nippur, Eridu, Uruk, Mount Meru), respond with {"archetype_name": "", "role_description": "NOT_AN_ACTOR"}.
7. Do NOT create archetypes that merely describe an absence or negative state ("The Void Maker", "The Unbuilt", "The Cityless"). If the cluster describes non-existence, respond with {"archetype_name": "", "role_description": "NOT_AN_ACTOR"}.

## OUTPUT — return ONLY this JSON:

{"archetype_name": "The Divine Craftsman", "role_description": "shapes matter into beings, especially humanity"}
"""


# Tokens that suggest a cluster is about a place, building, or inanimate object
# rather than a real actor. Used as a defensive pre-check before Stage 3B LLM.
_PLACE_TOKENS: set[str] = {
    "nippur", "eridu", "uruk", "ur", "lagash", "kish", "babylon", "akkad",
    "abzu", "apsu", "kur", "duku", "ekur", "etemenanki",
    "eden", "sheol", "zion", "jerusalem", "sinai",
    "olympus", "meru", "asgard", "midgard", "valhalla",
    "e-anna", "ebabbar", "esagila", "eanna",
    "heliopolis", "memphis", "thebes",
    "city", "cities", "temple", "temples", "shrine", "shrines",
    "river", "rivers", "mountain", "mountains", "sea", "seas",
    "foundation", "brick", "bricks", "dwelling", "dwellings",
    "settlement", "settlements", "field", "fields",
    "wall", "walls", "tower", "towers",
    # Generic plurals — not specific actors
    "gods", "goddesses", "deities", "divinities",
    "animals", "beasts", "creatures", "monsters",
    "humans", "humanity", "mankind", "men", "women", "people", "mortals",
    "spirits", "demons", "angels",
    "birds", "fish", "cattle",
}


def _is_non_actor_cluster(cluster_row: dict[str, Any]) -> bool:
    """Heuristic: does the cluster describe places/objects rather than beings?

    Checks whether all contributing 'actor' names are actually places/objects,
    or whether the canonical outcome describes non-existence.
    """
    contrib = cluster_row.get("contributing_cultures") or {}
    all_names: list[str] = []
    for names in contrib.values():
        for n in names:
            if n:
                all_names.append(n)
    if not all_names:
        return True

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.lower())

    # If EVERY contributing name looks like a place/object token, it's not an actor.
    if all_names and all(_norm(n) in _PLACE_TOKENS for n in all_names):
        return True

    # Outcome clearly describes absence/non-existence.
    outcome = (cluster_row.get("canonical_outcome") or "").lower()
    if any(
        phrase in outcome
        for phrase in [
            "no ",
            "not yet",
            "had not been",
            "did not exist",
            "was not made",
        ]
    ):
        return True

    return False


def _normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


async def _find_registry_by_aka(
    session: AsyncSession,
    candidate_names: list[str],
    entity_type: str,
) -> ArchetypeRegistry | None:
    """Look for an existing archetype whose also_known_as overlaps candidates."""

    norm_candidates = [_normalize_name(n) for n in candidate_names if n]
    if not norm_candidates:
        return None

    rows = (
        await session.execute(
            select(ArchetypeRegistry).where(
                ArchetypeRegistry.entity_type == entity_type
            )
        )
    ).scalars().all()

    for row in rows:
        for aka in row.also_known_as or []:
            if _normalize_name(aka) in norm_candidates:
                return row
    return None


async def _find_canonical_ids_for_names(
    session: AsyncSession,
    names: list[str],
    entity_type: str,
) -> list[uuid.UUID]:
    """Find canonical_actors / canonical_places rows matching any of these names.

    Also follows entity_equivalences to discover additional merged IDs.
    """

    table = CanonicalActor if entity_type == "actor" else CanonicalPlace
    ids: list[uuid.UUID] = []
    seen: set[str] = set()

    for name in names:
        if not name:
            continue
        try:
            row = (
                await session.execute(
                    select(table.id)
                    .where(
                        table.canonical_name.ilike(name.strip()),
                        table.is_current.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row and str(row) not in seen:
                seen.add(str(row))
                ids.append(row)
        except Exception:
            logger.debug("canonical lookup failed for %r", name, exc_info=True)

    # Equivalences
    if entity_type == "actor":
        for name in names:
            if not name:
                continue
            try:
                eq_rows = (
                    await session.execute(
                        text(
                            """
                            SELECT ee.primary_entity_id, ee.equivalent_entity_id
                            FROM entity_equivalences ee
                            JOIN canonical_actors ca ON ca.id = ee.equivalent_entity_id
                            WHERE LOWER(ca.canonical_name) = :n
                              AND ee.primary_entity_type = 'actor'
                            """
                        ),
                        {"n": name.strip().lower()},
                    )
                ).all()
                for a, b in eq_rows:
                    for eid in (a, b):
                        if eid and str(eid) not in seen:
                            seen.add(str(eid))
                            ids.append(eid)
            except Exception:
                logger.debug("equivalence lookup failed for %r", name, exc_info=True)

    return ids


async def resolve_archetype(
    session: AsyncSession,
    cluster_row: dict[str, Any],
    epoch_id: uuid.UUID | None,
    chapter_id: uuid.UUID | None,
    entity_type: str = "actor",
) -> ArchetypeRegistry | None:
    """Resolve a cluster to an ArchetypeRegistry row (creating one if needed).

    Returns None for clusters that don't describe a real actor (e.g. place
    clusters, absence statements). Caller should skip those clusters.

    The returned object (if non-None) is already flushed in the session. Caller
    should attach `cluster_row["primary_archetype_name"]` and
    `cluster_row["archetype_registry_id"]` and then commit.
    """

    # Guard: don't mint archetypes for place/object clusters or absence events.
    if _is_non_actor_cluster(cluster_row):
        logger.info(
            "Stage 3B: skipping non-actor cluster (verb=%s outcome=%r)",
            cluster_row.get("canonical_verb"),
            (cluster_row.get("canonical_outcome") or "")[:60],
        )
        return None

    contrib = cluster_row.get("contributing_cultures") or {}
    all_actor_names: list[str] = []
    for names in contrib.values():
        for n in names:
            if n and n not in all_actor_names:
                all_actor_names.append(n)

    # (1) Direct hit in registry by AKA
    existing = await _find_registry_by_aka(session, all_actor_names, entity_type)
    if existing is not None:
        changed = False
        for n in all_actor_names:
            if n and n not in (existing.also_known_as or []):
                existing.also_known_as = (existing.also_known_as or []) + [n]
                changed = True
        existing.usage_count = (existing.usage_count or 0) + 1
        if changed:
            new_ids = await _find_canonical_ids_for_names(
                session, all_actor_names, entity_type
            )
            merged = list(existing.canonical_ids or [])
            for cid in new_ids:
                if cid not in merged:
                    merged.append(cid)
            existing.canonical_ids = merged
        await session.flush()
        return existing

    # (2) No registry match — one-shot LLM to mint a new archetype
    role_summary = (
        f"verb_family: {cluster_row.get('verb_family')}\n"
        f"canonical_verb: {cluster_row.get('canonical_verb')}\n"
        f"canonical_outcome: {cluster_row.get('canonical_outcome')}\n"
        f"materials: {cluster_row.get('materials')}\n"
        f"contributing deities across cultures: {all_actor_names}"
    )
    user_prompt = (
        "Name the archetype for the following cluster. Review existing "
        "archetypes before naming to avoid duplicates.\n\n"
        f"CLUSTER ROLE:\n{role_summary}\n"
    )

    llm_result = await call_deepseek(
        user_prompt=user_prompt,
        system_prompt=ARCHETYPE_NAMER_SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=256,
    )

    archetype_name = str(llm_result.get("archetype_name") or "").strip()
    role_description = str(llm_result.get("role_description") or "").strip() or None

    # LLM can veto with NOT_AN_ACTOR when it recognises a non-actor cluster.
    if role_description == "NOT_AN_ACTOR" or (not archetype_name and role_description == "NOT_AN_ACTOR"):
        logger.info(
            "Stage 3B: LLM vetoed non-actor cluster (verb=%s)",
            cluster_row.get("canonical_verb"),
        )
        return None

    if not archetype_name:
        # Fallback: deterministic name from oldest member's role
        archetype_name = _fallback_archetype_name(cluster_row)

    # Defensive: if the LLM echoed a forbidden culture name, fall back
    if _looks_like_deity_name(archetype_name, all_actor_names):
        archetype_name = _fallback_archetype_name(cluster_row)

    # Check if this archetype name already exists (another cluster minted it
    # while we were thinking) — reuse instead of duplicating.
    existing_by_name = (
        await session.execute(
            select(ArchetypeRegistry).where(
                ArchetypeRegistry.archetype_name == archetype_name
            )
        )
    ).scalar_one_or_none()
    if existing_by_name is not None:
        existing = existing_by_name
        for n in all_actor_names:
            if n and n not in (existing.also_known_as or []):
                existing.also_known_as = (existing.also_known_as or []) + [n]
        existing.usage_count = (existing.usage_count or 0) + 1
        await session.flush()
        return existing

    canonical_ids = await _find_canonical_ids_for_names(
        session, all_actor_names, entity_type
    )

    new_row = ArchetypeRegistry(
        archetype_name=archetype_name,
        role_description=role_description,
        entity_type=entity_type,
        also_known_as=all_actor_names,
        canonical_ids=canonical_ids,
        role_signature={
            "verb_family": cluster_row.get("verb_family"),
            "canonical_verb": cluster_row.get("canonical_verb"),
        },
        first_seen_chapter_id=chapter_id,
        first_seen_epoch_id=epoch_id,
        usage_count=1,
    )
    session.add(new_row)
    await session.flush()
    return new_row


def _fallback_archetype_name(cluster_row: dict[str, Any]) -> str:
    verb = (cluster_row.get("canonical_verb") or "").strip().title() or "Being"
    family = (cluster_row.get("verb_family") or "").upper()
    suffix_map = {
        "MAKE": "Maker",
        "DESTROY": "Destroyer",
        "SEPARATE": "Divider",
        "JOIN": "Uniter",
        "SPEAK": "Namer",
        "MOVE": "Traveler",
        "GIVE": "Giver",
        "TAKE": "Taker",
        "CONTEND": "Champion",
        "TRANSFORM": "Transformer",
    }
    suffix = suffix_map.get(family, "One")
    return f"The {suffix}"


def _looks_like_deity_name(
    candidate: str, forbidden: list[str]
) -> bool:
    cand_norm = _normalize_name(candidate)
    for name in forbidden:
        if not name:
            continue
        if _normalize_name(name) and _normalize_name(name) in cand_norm:
            return True
    return False
