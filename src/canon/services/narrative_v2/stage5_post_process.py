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
    """Replace every culture-specific also_known_as name with the archetype name.

    Guards:
      - Skip aka tokens that are substrings of the archetype name (avoids
        "Primordial Void" → "The Primordial Void" producing "Primordial The
        Primordial Void" when the descriptor word is already present).
      - Skip generic nouns (temple, city, river, serpent...) to avoid false
        positives.
      - Collapse "the X" → "X" when replacing X with "The Archetype" would
        otherwise produce "the The Archetype".
    """
    text = narrative
    for a in archetypes:
        arch_name = a.archetype_name or ""
        arch_tokens = {t.lower() for t in re.findall(r"[A-Za-z]+", arch_name) if len(t) >= 3}

        aka = [n for n in (a.also_known_as or []) if n and len(n) >= 3]
        aka = [n for n in aka if _looks_like_proper_name(n)]
        # Skip aka tokens already embedded in the archetype name.
        aka = [n for n in aka if n.lower() not in arch_tokens]
        pattern = _build_name_regex(aka)
        if pattern is None:
            continue
        replacement = arch_name

        def _sub(m: re.Match[str], repl=replacement) -> str:
            # Look at the word immediately before the match.
            start = m.start()
            pre_text = text[max(0, start - 20):start]
            # Find the last word before the match
            prev_word_match = re.search(r"(\w+)\s*$", pre_text)
            if prev_word_match:
                prev_word = prev_word_match.group(1).lower()
                # If the previous word is already in the archetype name, drop the
                # duplicate descriptor from the replacement. e.g.
                # "Primordial Void" → trigger → "Primordial The Primordial Void"
                # would start with the same word "Primordial" as the preceding
                # word. Strip everything before the distinct suffix.
                repl_words = repl.split()
                # Skip leading "The" in replacement for this match
                if repl_words and repl_words[0].lower() == "the":
                    # "the Void" followed by replacement "The Primordial Void":
                    # match replaces "Void" — but if preceded by "the", caller
                    # sees "the The Primordial Void". Drop the leading "The".
                    if prev_word == "the":
                        return " ".join(repl_words[1:])
                # General de-duplication: if the previous word matches any word
                # in the replacement, drop up to that word from the replacement.
                for i, w in enumerate(repl_words):
                    if w.lower() == prev_word:
                        # Drop everything up to and including this duplicate
                        tail = repl_words[i + 1:]
                        if tail:
                            return " ".join(tail)
            return repl

        text = pattern.sub(_sub, text)
    return text


_GENERIC_NOUNS = {
    "temple", "city", "cities", "river", "rivers", "mountain",
    "mountains", "sea", "seas", "wall", "walls", "gate", "gates",
    "palace", "palaces", "house", "houses", "land", "lands",
    "field", "fields", "garden", "gardens", "tower", "towers",
    "street", "road", "earth", "sky", "heaven", "heavens",
    "serpent", "snake", "dragon", "beast", "void", "chaos",
    "abyss", "deep", "waters", "water", "light", "dark",
    "darkness", "day", "night", "moon", "sun", "stars",
    "world", "cosmos", "universe", "life", "death",
    "man", "men", "woman", "women",
}


def _looks_like_proper_name(s: str) -> bool:
    """Heuristic: is this a proper name (deity/place) vs a generic noun?"""
    if not s:
        return False
    s_norm = s.strip().lower()
    if s_norm in _GENERIC_NOUNS:
        return False
    # Capitalized or contains non-ASCII → likely a name
    if s[0].isupper():
        return True
    # All-lowercase generic words — skip
    return False


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


def normalize_duplicate_archetype_phrases(
    text: str, archetypes: list[ArchetypeRegistry]
) -> str:
    """Collapse patterns like 'Primordial The Primordial Void' to 'The Primordial Void'.

    These arise when a previous scrub run replaced a token that was already
    adjacent to a descriptor word shared with the archetype name.
    """
    for a in archetypes:
        name = a.archetype_name
        if not name:
            continue

        # Pattern 1: "Word1 The Word1 Word2..." where Word1 is a token of the
        # archetype name. E.g. "Primordial The Primordial Void" → "The Primordial Void".
        tokens = [t for t in name.split() if len(t) >= 4 and t.lower() != "the"]
        for tok in tokens:
            pat = re.compile(rf"\b{re.escape(tok)}\s+({re.escape(name)})\b", re.IGNORECASE)
            text = pat.sub(r"\1", text)

        # Pattern 2: "the [Name]" where [Name] starts with "The " → drop one "the".
        pat2 = re.compile(rf"\b[Tt]he\s+({re.escape(name)})\b")
        text = pat2.sub(r"\1", text)

        # Pattern 3: doubled name, e.g. "The X The X" → "The X".
        pat3 = re.compile(rf"\b({re.escape(name)})\s+\1\b")
        text = pat3.sub(r"\1", text)

    return text


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
    cleaned = normalize_duplicate_archetype_phrases(cleaned, archetypes)
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
