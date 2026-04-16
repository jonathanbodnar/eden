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


FACT_SHEET_SYSTEM_PROMPT = f"""You are a historian compiling the definitive account of ONE ancient culture's tradition for one chapter topic.

You will receive source texts from a single cultural tradition. Your job is to produce TWO outputs in a single JSON response:

1. `prose_history`: 1500-2500 words of flowing historical prose. Readable, faithful, exhaustive. This is what readers see when they select this culture.

2. `fact_sheet`: a strictly structured record of every actor, event, place, material, and detail present in the sources.

{LAWS_OF_SYNTHESIS}

## HARD RULES

- Use ONLY information from the sources provided. Never invent. (Law 2, 14)
- Preserve every culture-specific name verbatim (Enki, Nu, Tiamat, YHWH). Do not paraphrase names. (Law 2)
- Record direct quotes when present in sources. (Law 14)
- Do NOT interpret or explain. Report what sources state. (Law 3, 9)
- Present tense for vividness.
- When motivation ("why") appears in sources, include it verbatim. Do NOT fabricate motive.
- Include epithets ("god of wisdom", "lord of the Abzu", "the bright one") next to each actor.
- Every event in the fact_sheet should be atomic: one verb, one actor set, one outcome.

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
    parts.append(f"# CHAPTER TOPIC: {chapter_title}")
    parts.append(f"{chapter_summary}")
    parts.append("")
    parts.append(f"# CULTURE: {culture_label}")
    parts.append("")
    parts.append(
        "Produce the prose_history and fact_sheet ONLY from the sources below. "
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
