"""Stage 4 — narrative rendering.

Takes pre-merged `event_clusters` with resolved archetype names and produces
flowing literary-historical prose for ONE chapter. DeepSeek's job here is
radically narrow: render each cluster as 3-6 sentences, transition between
clusters, use the provided archetype names verbatim. No merging decisions,
no name choices, no selection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.canon.services.narrative_v2.llm import call_deepseek
from src.canon.services.narrative_v2.shared import LAWS_OF_SYNTHESIS

logger = logging.getLogger(__name__)


RENDER_SYSTEM_PROMPT = f"""You are a historian writing one chapter of a unified ancient world history.

{LAWS_OF_SYNTHESIS}

## WHAT YOU ARE DOING

You will receive pre-merged event clusters for a chapter. ALL merging has already been done — each cluster represents ONE event, already combined across cultures. Your job is ONLY to render them as literary-historical prose.

## WHAT YOU ARE NOT DOING

- You are NOT merging events. That is already done.
- You are NOT selecting events. Every cluster I give you must appear.
- You are NOT choosing names. Use the exact archetype names I provide.
- You are NOT introducing culture-specific deity names. They are forbidden.

## HARD RULES

1. Use each cluster's `archetype_name` verbatim every time you mention that role. Never substitute a culture-specific name.
2. Render each cluster as 3-6 sentences. Target 80-150 words per cluster.
3. NEVER use framing like "according to one tradition", "in another account", "some say", "elsewhere", "similarly", "the [Culture]s tell of".
4. NEVER tell the same event twice. One cluster = one telling. (Law 10)
5. Do NOT retell events from prior chapters listed under ALREADY TOLD.
6. Include sensory detail and motive ONLY when present in the cluster's `vivid_details` or `source_quotes`. Do not invent atmosphere.
7. Include source quotes selectively — prefer paraphrase but a pivotal quoted phrase can anchor a paragraph.
8. Target total length: 1500-2500 words across all clusters.

## STYLE

Literary historical. A confident historian's voice. Rich sensory detail drawn from the provided vivid_details, but no thematic drama, no modern commentary, no speculation. Think Tacitus recounting what happened, not a novelist dramatizing it.

Present tense. Direct. Specific. Anchored in verifiable elements (materials, places, outcomes, quotes) from each cluster.

## BANNED WORDS IN PROSE (instant failure)

Culture labels: Sumerian, Hebrew, Egyptian, Greek, Norse, Chinese, Vedic, Hindu, Babylonian, Persian, Japanese, Ainu, African, Polynesian, Maya, Aztec, Hopi, Roman, Zoroastrian, Mesoamerican, Canaanite, Celtic, Akkadian.

Deity names in prose: Enki, Marduk, Ra, Khepera, Tum, Tiamat, Apsu, Nu, Shu, Tefnut, Geb, Nut, Isis, Osiris, Brahma, Vishnu, Shiva, Odin, Thor, Enlil, YHWH, Yahweh, Elohim, Nuwa, Pangu, Pandora, Prometheus, Zeus, Ptah, Khnum, Atum, Ymir, Quetzalcoatl.

If an event requires a specific actor whose archetype I did not provide, skip it.

## OUTPUT — return ONLY this JSON:

{{
  "narrative_text": "Full chapter prose here...",
  "archetypes_used": ["The Divine Craftsman", "The Primordial Waters", ...]
}}
"""


@dataclass(frozen=True)
class ClusterForRendering:
    seq: int
    archetype_name: str
    archetype_role: str | None
    verb_family: str
    canonical_verb: str
    canonical_outcome: str
    materials: list[str]
    vivid_details: list[dict]
    source_quotes: list[dict]
    contributing_deities: list[str]


def build_user_prompt(
    chapter_title: str,
    chapter_summary: str,
    prior_summaries: list[str],
    clusters: list[ClusterForRendering],
) -> str:
    parts: list[str] = []
    parts.append(f"# CHAPTER: {chapter_title}")
    parts.append(f"TOPIC: {chapter_summary}")
    parts.append("")

    if prior_summaries:
        parts.append("## ALREADY TOLD IN PRIOR CHAPTERS — do not retell:")
        for s in prior_summaries:
            parts.append(f"  - {s}")
        parts.append("")

    parts.append("## CLUSTERS TO RENDER, IN ORDER")
    parts.append("")
    parts.append(
        "Each cluster is one event. Render it as literary-historical prose. "
        "Use the archetype_name verbatim every time you reference that role."
    )
    parts.append("")

    for c in clusters:
        parts.append(f"### [{c.seq}] {c.archetype_name}")
        if c.archetype_role:
            parts.append(f"role: {c.archetype_role}")
        parts.append(f"action: {c.canonical_verb} — {c.canonical_outcome}")
        if c.materials:
            parts.append(f"materials: {', '.join(c.materials)}")
        if c.vivid_details:
            parts.append("vivid details (weave naturally, do not list):")
            for d in c.vivid_details[:6]:
                detail = d.get("detail") if isinstance(d, dict) else str(d)
                parts.append(f"  - {detail}")
        if c.source_quotes:
            parts.append("source quotes (use selectively):")
            for q in c.source_quotes[:3]:
                quote = q.get("quote") if isinstance(q, dict) else str(q)
                parts.append(f'  - "{quote}"')
        if c.contributing_deities:
            parts.append(
                f"NAMES IN SOURCES — DO NOT USE IN PROSE, metadata only: "
                f"{', '.join(c.contributing_deities[:10])}"
            )
        parts.append("")

    return "\n".join(parts)


async def render_chapter(
    chapter_title: str,
    chapter_summary: str,
    prior_summaries: list[str],
    clusters: list[ClusterForRendering],
) -> dict[str, Any]:
    if not clusters:
        return {"narrative_text": "", "archetypes_used": []}

    prompt = build_user_prompt(
        chapter_title=chapter_title,
        chapter_summary=chapter_summary,
        prior_summaries=prior_summaries,
        clusters=clusters,
    )
    result = await call_deepseek(
        user_prompt=prompt,
        system_prompt=RENDER_SYSTEM_PROMPT,
        temperature=0.4,
        max_tokens=8192,
    )

    narrative = str(result.get("narrative_text") or "").strip()
    used = [str(x) for x in (result.get("archetypes_used") or []) if x]
    if not used:
        used = list({c.archetype_name for c in clusters})

    return {"narrative_text": narrative, "archetypes_used": used}
