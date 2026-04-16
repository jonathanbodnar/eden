"""Stage 5 — post-processing.

Deterministic. Takes the Stage 4 prose and a list of archetypes used and:
  1. Scrubs any leaked culture-specific deity names, replacing with archetype
  2. Inserts [[actor:Archetype]] annotations on first mention
  3. Populates entity_mentions_json for the UI right panel
  4. Validates: fails if any banned culture word remains
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.narrative_v2 import ArchetypeRegistry

logger = logging.getLogger(__name__)


BANNED_CULTURE_LABELS: list[str] = [
    "Sumerian", "Babylonian", "Akkadian", "Mesopotamian",
    "Egyptian", "Hebrew", "Israelite", "Vedic", "Hindu",
    "Greek", "Norse", "Chinese", "Japanese", "Ainu",
    "Zoroastrian", "Persian", "Mesoamerican", "Canaanite",
    "Celtic", "Maya", "Aztec", "Hopi", "Roman",
]

_BANNED_FRAMING: list[str] = [
    r"\baccording to\s+(?:one|the|another)\s+tradition",
    r"\bin\s+(?:one|another)\s+account",
    r"\bsome\s+say\b",
    r"\belsewhere\s*,\s+(?:from|in)",
    r"\bit is\s+(?:believed|said|told)",
]


def _build_name_regex(names: list[str]) -> re.Pattern[str] | None:
    """Word-boundary regex that matches any name, sorted longest-first."""
    cleaned = sorted(
        {n.strip() for n in names if n and len(n.strip()) >= 2},
        key=len,
        reverse=True,
    )
    if not cleaned:
        return None
    alts = [re.escape(n) for n in cleaned]
    pattern = r"\b(?:" + "|".join(alts) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


async def load_archetypes_by_name(
    session: AsyncSession, archetype_names: list[str]
) -> list[ArchetypeRegistry]:
    if not archetype_names:
        return []
    rows = (
        await session.execute(
            select(ArchetypeRegistry).where(
                ArchetypeRegistry.archetype_name.in_(archetype_names)
            )
        )
    ).scalars().all()
    return list(rows)


def scrub_leaked_names(narrative: str, archetypes: list[ArchetypeRegistry]) -> str:
    """Replace every culture-specific also_known_as name with the archetype name."""
    text = narrative
    for a in archetypes:
        aka = [n for n in (a.also_known_as or []) if n]
        pattern = _build_name_regex(aka)
        if pattern is None:
            continue
        replacement = a.archetype_name

        def _sub(m: re.Match[str]) -> str:
            return replacement

        text = pattern.sub(_sub, text)

        # Possessives: "The Archetype's" already works naturally because we
        # replaced the name and the apostrophe-s remains attached outside \b.
    return text


def insert_annotations(
    narrative: str, archetypes: list[ArchetypeRegistry]
) -> str:
    """Wrap the first occurrence of each archetype name in [[actor:Name]]."""
    text = narrative
    for a in archetypes:
        name = a.archetype_name
        if not name:
            continue
        already = re.search(r"\[\[(?:actor|place):" + re.escape(name) + r"\]\]", text)
        if already:
            continue
        entity_kind = a.entity_type or "actor"
        annotation = f"[[{entity_kind}:{name}]]"
        # First occurrence: match case-sensitively at word boundary
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        text = pattern.sub(annotation, text, count=1)
    return text


def build_entity_mentions(
    archetypes: list[ArchetypeRegistry],
    cluster_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build entity_mentions_json: one entry per archetype used in this chapter."""

    # Map archetype_name -> role_in_chapter (first cluster's canonical_outcome)
    role_map: dict[str, str] = {}
    for cr in cluster_rows:
        name = cr.get("primary_archetype_name")
        if name and name not in role_map:
            role_map[name] = cr.get("canonical_outcome") or ""

    mentions: list[dict[str, Any]] = []
    for a in archetypes:
        primary: uuid.UUID | None = None
        all_ids: list[str] = []
        for cid in a.canonical_ids or []:
            s = str(cid)
            if s not in all_ids:
                all_ids.append(s)
            if primary is None:
                primary = cid

        mentions.append(
            {
                "name": a.archetype_name,
                "type": a.entity_type or "actor",
                "also_known_as": list(a.also_known_as or []),
                "canonical_id": str(primary) if primary else None,
                "all_canonical_ids": all_ids,
                "archetype_registry_id": str(a.id),
                "role_in_chapter": role_map.get(a.archetype_name, ""),
            }
        )
    return mentions


def validate(narrative: str, archetypes: list[ArchetypeRegistry]) -> list[str]:
    """Return a list of validation warnings. Empty list = clean."""

    problems: list[str] = []

    # Banned culture labels
    for label in BANNED_CULTURE_LABELS:
        if re.search(r"\b" + re.escape(label) + r"\b", narrative):
            problems.append(f"banned culture label '{label}' still present")

    # Banned framing
    for frame_re in _BANNED_FRAMING:
        if re.search(frame_re, narrative, re.IGNORECASE):
            problems.append(f"banned framing '{frame_re}' still present")

    # Any also_known_as leak that didn't get scrubbed
    for a in archetypes:
        for aka in a.also_known_as or []:
            if not aka or len(aka) < 3:
                continue
            if re.search(r"\b" + re.escape(aka) + r"\b", narrative):
                problems.append(
                    f"deity name '{aka}' (archetype: {a.archetype_name}) still present"
                )
                break  # one per archetype is enough signal

    return problems


async def post_process(
    session: AsyncSession,
    narrative_text: str,
    archetype_names: list[str],
    cluster_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the full post-processing pipeline.

    Returns {narrative_text, entity_mentions_json, archetypes_used, problems}.
    """

    archetypes = await load_archetypes_by_name(session, archetype_names)

    cleaned = scrub_leaked_names(narrative_text, archetypes)
    cleaned = insert_annotations(cleaned, archetypes)

    entity_mentions = build_entity_mentions(archetypes, cluster_rows)
    problems = validate(cleaned, archetypes)
    if problems:
        logger.warning("Stage 5 validation problems: %s", problems)

    return {
        "narrative_text": cleaned,
        "entity_mentions_json": entity_mentions,
        "archetypes_used": [a.archetype_name for a in archetypes],
        "problems": problems,
    }
