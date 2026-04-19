"""Stage 1 — culture fact sheet.

For each culture with sources in the chapter scope, produce a comprehensive
prose history AND a strictly structured fact sheet. The fact sheet feeds
Stage 2; the prose history is what the UI culture dropdown displays.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.canon.services.narrative_v2.llm import call_deepseek
from src.canon.services.narrative_v2.shared import LAWS_OF_SYNTHESIS

logger = logging.getLogger(__name__)


FACT_SHEET_SYSTEM_PROMPT = f"""You are a historian compiling the definitive account of ONE ancient culture's tradition for ONE SPECIFIC chapter topic.

You will receive source texts from a single cultural tradition. Your job is to produce TWO outputs in a single JSON response:

1. `prose_history`: 1500-2500 words of flowing historical prose COVERING ONLY THE CHAPTER TOPIC. Readable, faithful, exhaustive within the topic scope. This is what readers see when they select this culture.

2. `fact_sheet`: a strictly structured record of every actor, event, place, material, and detail present in the sources THAT PERTAINS TO THE CHAPTER TOPIC.

{LAWS_OF_SYNTHESIS}

## ⚠️ CHAPTER SCOPE — READ BEFORE EXTRACTING ANYTHING

The sources provided may contain content that goes BEYOND the chapter topic. You MUST stay strictly within the chapter's scope. Examples:

- If the chapter is about "The Primordial Void / First Stirrings", you ONLY include: emergence of the first being(s), the formless state before creation, the first movement or separation. You DO NOT include: creation of humans, garden of Eden, first sins, floods, kings, patriarchs, exile. Those belong to LATER chapters.
- If the chapter is about "Creation of Humanity from Clay", you ONLY include: the shaping of the first humans, their materials, their purpose. You DO NOT include: the primordial void, the garden, the fall, the flood.
- If a source continues into later events, TRUNCATE. Only extract the portion that matches the topic.

When in doubt, ASK YOURSELF: "Does this specific event/detail belong to the chapter titled above, or to a later chapter?" If later — EXCLUDE it.

An empty `fact_sheet.events` list is ACCEPTABLE if the culture has nothing to contribute to THIS specific chapter. A bloated fact_sheet that crosses into later-chapter material is WRONG.

## HARD RULES

- Use ONLY information from the sources provided. Never invent. (Law 2, 14)
- Preserve every culture-specific name verbatim (Enki, Nu, Tiamat, YHWH). Do not paraphrase names. (Law 2)
- Record direct quotes when present in sources. (Law 14)
- Do NOT interpret or explain. Report what sources state. (Law 3, 9)
- Present tense for vividness.
- When motivation ("why") appears in sources, include it verbatim. Do NOT fabricate motive.
- Include epithets ("god of wisdom", "lord of the Abzu", "the bright one") next to each actor.
- Every event in the fact_sheet should be atomic: one verb, one actor set, one outcome.
- DO NOT record "absence statements" as events. Lines like "X had not yet been made", "no reed had sprung up", "the earth did not yet exist" are scene-setting. If the source opens with such lines, mention them once in `prose_history` but do NOT add them to `fact_sheet.events`.
- An `event` requires a real actor (deity, mythic figure, human) performing an action. A place (Nippur, Eridu) cannot be the actor of an event.
- If the source discusses content OUTSIDE the chapter topic, SKIP IT. Do not let the LLM's knowledge of the full narrative leak into the wrong chapter.

## OUTPUT FORMAT — return ONLY valid JSON with these exact keys:

{{
  "prose_history": "Full 1500-2500 word flowing history...",
  "fact_sheet": {{
    "actors": [
      {{
        "name": "Enki",
        "epithets": ["god of wisdom", "lord of the Abzu"],
        "role": "shaper of humanity"
      }}
    ],
    "events": [
      {{
        "seq": 1,
        "actors": ["Enki"],
        "verb": "descends",
        "objects": [],
        "materials": [],
        "place": "Abzu",
        "outcome": "takes his dwelling in the freshwater ocean",
        "quoted_phrase": "Enki descended into the Abzu",
        "source_ref": "Enuma Elish Tablet I, line 60"
      }}
    ],
    "places": [
      {{"name": "Abzu", "description": "underground freshwater ocean"}}
    ],
    "materials": ["clay", "divine blood"],
    "unique_details": [
      "Seven male and seven female humans created simultaneously"
    ]
  }}
}}
"""


@dataclass(frozen=True)
class SourceInput:
    source_id: str
    title: str
    text: str
    weight: float = 1.0


def build_user_prompt(
    culture_label: str,
    chapter_title: str,
    chapter_summary: str,
    sources: list[SourceInput],
) -> str:
    parts: list[str] = []
    parts.append("=" * 70)
    parts.append(f"# CHAPTER TOPIC: {chapter_title}")
    parts.append("=" * 70)
    parts.append("")
    parts.append(f"## CHAPTER SUMMARY (STRICT SCOPE — DO NOT GO BEYOND):")
    parts.append(chapter_summary or "(no summary provided)")
    parts.append("")
    parts.append(
        "⚠️ Everything you extract MUST fit the chapter scope above. "
        "If a source contains material for LATER chapters (creation of humans, "
        "garden, fall, flood, kings, exile, etc. when this chapter is about "
        "the primordial state), SKIP it. An empty events list is acceptable."
    )
    parts.append("")
    parts.append(f"# CULTURE: {culture_label}")
    parts.append("")
    parts.append(
        "Produce the prose_history and fact_sheet ONLY from the sources below, "
        "AND only the parts of those sources that fit the chapter scope. "
        "Do not include any knowledge that is not in these sources."
    )
    parts.append("")
    parts.append("## SOURCES:")
    parts.append("")

    for i, src in enumerate(sources, start=1):
        parts.append(f"### SOURCE [{i}] — {src.title}")
        parts.append(f"(source_id: {src.source_id})")
        parts.append("")
        parts.append(src.text[:6000])
        parts.append("")
        parts.append("---")
        parts.append("")

    return "\n".join(parts)


async def generate_fact_sheet(
    culture_label: str,
    chapter_title: str,
    chapter_summary: str,
    sources: list[SourceInput],
) -> dict[str, Any]:
    """Produce prose_history + fact_sheet for one culture/chapter.

    Returns an empty dict on failure; callers should check for "prose_history"
    before persisting.
    """

    if not sources:
        return {}

    user_prompt = build_user_prompt(
        culture_label=culture_label,
        chapter_title=chapter_title,
        chapter_summary=chapter_summary,
        sources=sources,
    )

    result = await call_deepseek(
        user_prompt=user_prompt,
        system_prompt=FACT_SHEET_SYSTEM_PROMPT,
        temperature=0.35,
        max_tokens=8192,
    )

    if "prose_history" not in result or "fact_sheet" not in result:
        logger.warning(
            "Stage 1 output for %s missing required keys (got: %s)",
            culture_label,
            list(result.keys()),
        )
        return {}

    return result
