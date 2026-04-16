"""Stage 2 — atomic event distillation.

Given a Stage 1 fact_sheet, produce strictly-schemad atomic events and compute
an action embedding for each. These rows feed the deterministic clusterer in
Stage 3.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.canon.services.narrative_v2.llm import call_deepseek, embed_texts
from src.canon.services.narrative_v2.shared import (
    LAWS_OF_SYNTHESIS,
    VERB_FAMILIES,
    classify_verb,
)

logger = logging.getLogger(__name__)


# Patterns that indicate a Sumerian/ancient-text "absence" statement:
# "X had not yet been made", "Y did not exist", "no reed had sprung up".
# These are scene-setting/context, NOT events with real actors. We skip them
# from atomic-event extraction — they'd otherwise turn places into "actors"
# and poison clustering/archetype minting.
_ABSENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bhad not (?:yet )?been (?:made|built|constructed|laid|erected|formed|completed|constituted|raised)\b", re.IGNORECASE),
    re.compile(r"\bhad not (?:yet )?been\b", re.IGNORECASE),
    re.compile(r"\bhad not (?:yet )?(?:sprung|grown|come|arisen|existed|arrived)\b", re.IGNORECASE),
    re.compile(r"\bdid not (?:yet )?exist\b", re.IGNORECASE),
    re.compile(r"\bwas not (?:yet )?(?:made|built|born|created|shaped|formed)\b", re.IGNORECASE),
    re.compile(r"\bwere not (?:yet )?(?:made|built|born|created|shaped|formed)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:no|not)\b", re.IGNORECASE),
    re.compile(r"\bno\s+\w+\s+(?:had|exists|existed|was|were)\b", re.IGNORECASE),
    re.compile(r"\bhas not been\b", re.IGNORECASE),
]


def _is_absence_event(event: dict[str, Any]) -> bool:
    """True if the 'event' describes non-existence rather than an action."""
    blob = " ".join(
        [
            str(event.get("outcome") or ""),
            str(event.get("quoted_phrase") or ""),
            str(event.get("verb") or ""),
        ]
    )
    for pat in _ABSENCE_PATTERNS:
        if pat.search(blob):
            return True
    return False


# Generic plurals that are NOT real actors — they're descriptions of classes
# of beings. Appearing as a sole actor means the event is under-specified.
_GENERIC_PLURAL_ACTORS: set[str] = {
    "gods", "goddesses", "deities", "divinities",
    "animals", "beasts", "creatures", "monsters",
    "birds", "fish", "cattle",
    "humans", "humanity", "mankind", "men", "women", "people", "mortals",
    "spirits", "demons", "angels",
    "the gods", "the animals", "the beasts",
}


def _filter_actors(actors: list[str]) -> list[str]:
    """Remove generic plurals from actor list. Keep real names (proper nouns).

    A real actor is capitalized (proper name) OR is a role word paired with a
    proper noun. Generic plurals alone don't anchor an event.
    """
    cleaned: list[str] = []
    for a in actors:
        if not a or not a.strip():
            continue
        a = a.strip()
        if a.lower() in _GENERIC_PLURAL_ACTORS:
            continue
        cleaned.append(a)
    return cleaned


_VERB_LIST_FOR_PROMPT = "\n".join(
    f"  {family}: {', '.join(verbs)}" for family, verbs in VERB_FAMILIES.items()
)


ATOMIC_EVENT_SYSTEM_PROMPT = f"""You extract atomic events from a structured cultural fact sheet.

Each atomic event captures ONE verb, ONE primary actor set, ONE outcome. No color, no narration, no "then" or "afterwards". Just structured facts.

{LAWS_OF_SYNTHESIS}

## VERB FAMILIES — every event MUST use a verb from one of these lists:

{_VERB_LIST_FOR_PROMPT}

If the source verb isn't literally on the list, choose the closest verb from the same family.

## RULES

1. Extract EVERY TRUE EVENT from the fact_sheet. An event requires an actor performing an action producing an outcome. (Law 14)
2. Do NOT extract "absence statements" — sentences describing what had not yet happened or did not exist ("X had not yet been made", "no reed had sprung up", "no city existed"). These are scene-setting, not events. Skip them entirely.
3. The `actors` field must contain beings (deities, mythic figures, humans), NOT places, objects, or temples. If a sentence's grammatical subject is a place (Nippur, Eridu, Abzu), do NOT create an event for it.
4. Keep culture-specific names verbatim in `actors` (e.g. "Enki", "Tiamat").
5. Preserve direct quotes verbatim in `quoted_phrase` when available.
6. Include source_ref if present in the fact_sheet.
7. `outcome_keywords` should be 2-5 normalized lowercase keywords for matching (e.g. ["humanity", "serve"], ["sky", "earth", "separated"], ["void", "beginning"]). Prefer universal/cross-cultural nouns ("human" over "mankind", "water" over "sea").
8. `materials` covers physical substances (clay, dust, blood, breath, water, maize, wood).
9. Do NOT interpret. Do NOT add motivation unless the fact_sheet explicitly states it.

## OUTPUT — return ONLY valid JSON:

{{
  "events": [
    {{
      "seq": 1,
      "actors": ["Enki"],
      "verb": "descends",
      "verb_family": "MOVE",
      "objects": [],
      "materials": [],
      "place": "Abzu",
      "outcome": "takes dwelling in the freshwater ocean",
      "outcome_keywords": ["dwelling", "waters"],
      "quoted_phrase": "Enki descended into the Abzu",
      "source_ref": "Enuma Elish Tablet I"
    }},
    {{
      "seq": 2,
      "actors": ["Enki", "Ninhursag"],
      "verb": "molds",
      "verb_family": "MAKE",
      "objects": ["first humans"],
      "materials": ["clay", "blood of Qingu"],
      "place": "Abzu",
      "outcome": "humanity comes into being to serve the gods",
      "outcome_keywords": ["humanity", "serve", "clay"],
      "quoted_phrase": "Let man be created out of the blood of a slain god",
      "source_ref": "Enuma Elish Tablet VI"
    }}
  ]
}}
"""


def build_user_prompt(fact_sheet: dict[str, Any]) -> str:
    import json as _json

    return (
        "Extract atomic events from this fact sheet. "
        "Every event in the fact sheet's `events` array must appear here "
        "as an atomic event. If an event in the fact sheet is compound "
        "(multiple verbs), split it into multiple atomic events.\n\n"
        "FACT SHEET:\n"
        + _json.dumps(fact_sheet, indent=2, ensure_ascii=False)
    )


async def distil_atomic_events(fact_sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of atomic event dicts (no embeddings yet)."""

    if not fact_sheet or not fact_sheet.get("events"):
        return []

    user_prompt = build_user_prompt(fact_sheet)
    result = await call_deepseek(
        user_prompt=user_prompt,
        system_prompt=ATOMIC_EVENT_SYSTEM_PROMPT,
        temperature=0.15,
        max_tokens=6000,
    )

    events: list[dict[str, Any]] = result.get("events", [])
    if not isinstance(events, list):
        logger.warning("Stage 2 returned non-list events: %r", type(events))
        return []

    normalized: list[dict[str, Any]] = []
    dropped_absence = 0
    for i, ev in enumerate(events, start=1):
        if not isinstance(ev, dict):
            continue
        verb = str(ev.get("verb") or "").strip()
        outcome = str(ev.get("outcome") or "").strip()
        if not verb or not outcome:
            continue
        if _is_absence_event(ev):
            dropped_absence += 1
            continue
        raw_actors = [str(a).strip() for a in (ev.get("actors") or []) if a]
        actors = _filter_actors(raw_actors)
        if not actors:
            # All actors were generic plurals — skip this event
            continue
        family = str(ev.get("verb_family") or "").strip().upper()
        if family not in VERB_FAMILIES:
            family = classify_verb(verb)
        normalized.append(
            {
                "seq": int(ev.get("seq") or i),
                "actors": actors,
                "verb": verb,
                "verb_family": family,
                "objects": [str(o) for o in (ev.get("objects") or [])],
                "materials": [str(m) for m in (ev.get("materials") or [])],
                "place": (str(ev.get("place")) if ev.get("place") else None),
                "outcome": outcome,
                "outcome_keywords": [
                    str(k).lower().strip()
                    for k in (ev.get("outcome_keywords") or [])
                ],
                "quoted_phrase": ev.get("quoted_phrase") or None,
                "source_ref": ev.get("source_ref") or None,
            }
        )

    if dropped_absence:
        logger.info(
            "Stage 2: dropped %d absence-statement events (scene-setting context)",
            dropped_absence,
        )

    return normalized


def build_action_string(event: dict[str, Any]) -> str:
    """Build the text used for embedding similarity in Stage 3."""
    parts: list[str] = []
    parts.append(event.get("verb") or "")
    objs = event.get("objects") or []
    if objs:
        parts.append(" ".join(objs))
    mats = event.get("materials") or []
    if mats:
        parts.append(" ".join(mats))
    outcome = event.get("outcome") or ""
    if outcome:
        parts.append(outcome)
    return " ".join(p for p in parts if p).strip()


async def compute_embeddings(
    events: list[dict[str, Any]],
) -> list[list[float]]:
    """Return a parallel list of embeddings for `events`."""

    if not events:
        return []
    texts = [build_action_string(e) for e in events]
    return await embed_texts(texts)
