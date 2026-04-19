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

You will receive pre-merged event clusters for a chapter. ALL merging has already been done — each cluster represents ONE event, already combined across cultures. Your job is to weave them into ONE continuous, flowing, literary-historical narrative.

## STYLE — THIS IS THE MOST IMPORTANT PART

You are writing FLOWING NARRATIVE PROSE, not a bulleted event log. The output must read like a single unified history — paragraphs of 4-8 sentences each, smooth transitions, natural storytelling rhythm.

Absolutely forbidden:
- One short sentence per cluster (robotic cadence).
- Starting every sentence with an archetype name.
- Repeating the archetype name at the start of consecutive sentences. After introducing an archetype, use pronouns ("he", "she", "they"), epithets ("the shaper", "the mother"), or role descriptions.
- Listing clusters back-to-back as isolated statements.

Required:
- Paragraphs. Real paragraphs. Group related clusters (e.g. everything about separating earth and heaven) into the same paragraph with connective prose.
- Variety of sentence structure and rhythm.
- Present tense, confident historian's voice — think Tacitus or Herodotus recounting what happened.
- Rich sensory detail drawn ONLY from the provided vivid_details, materials, and source quotes. Do not invent atmosphere.
- Each archetype is introduced on its first appearance with a natural clause describing its role, then referred to by pronoun/epithet thereafter.

## HARD RULES

1. Use each cluster's `archetype_name` verbatim — but only for the FIRST appearance of that archetype, or when clarity demands re-naming. Use pronouns and epithets the rest of the time.
2. NEVER substitute a culture-specific deity name (Enki, Marduk, Tiamat, Ra, Yahweh, etc.) for an archetype name.
3. NEVER use framing like "according to one tradition", "in another account", "some say", "elsewhere", "similarly", "the Sumerians say", "the Greeks tell".
4. NEVER tell the same event twice. One cluster = one telling. (Law 10)
5. Do NOT retell events from prior chapters listed under ALREADY TOLD.
6. Every cluster must be represented somewhere in the narrative, but you choose where and how tightly — some clusters may deserve a whole paragraph, others a single clause folded into another paragraph.
7. Include source quotes selectively — at most 2-3 quoted phrases in the entire chapter, and only pivotal ones.
8. Target total length: 1500-2500 words across 5-10 paragraphs.

## BANNED WORDS IN PROSE (instant failure)

Culture labels: Sumerian, Hebrew, Egyptian, Greek, Norse, Chinese, Vedic, Hindu, Babylonian, Persian, Japanese, Ainu, African, Polynesian, Maya, Aztec, Hopi, Roman, Zoroastrian, Mesoamerican, Canaanite, Celtic, Akkadian.

Deity names in prose: Enki, Ea, Marduk, Ra, Khepera, Atum, Tum, Tiamat, Apsu, Nu, Nun, Shu, Tefnut, Geb, Nut, Isis, Osiris, Brahma, Vishnu, Shiva, Odin, Thor, Enlil, Ninhursag, Aruru, YHWH, Yahweh, Elohim, Nuwa, Pangu, Pandora, Prometheus, Zeus, Ptah, Khnum, Ymir, Quetzalcoatl, Huitzilopochtli, Xmucane.

If an event requires a specific actor whose archetype I did not provide, skip it silently.

## OUTPUT — return ONLY this JSON:

{{
  "narrative_text": "Full chapter prose here, as multiple paragraphs separated by double newlines...",
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

    # Archetype roster — so the model knows who each archetype is before weaving.
    seen_archetypes: dict[str, str | None] = {}
    for c in clusters:
        if c.archetype_name and c.archetype_name not in seen_archetypes:
            seen_archetypes[c.archetype_name] = c.archetype_role
    if seen_archetypes:
        parts.append("## ARCHETYPES APPEARING IN THIS CHAPTER")
        parts.append("(use these names; introduce each once, then pronouns/epithets)")
        parts.append("")
        for name, role in seen_archetypes.items():
            if role:
                parts.append(f"  - **{name}** — {role}")
            else:
                parts.append(f"  - **{name}**")
        parts.append("")

    parts.append("## EVENT FACTS TO WEAVE INTO ONE CONTINUOUS CHAPTER")
    parts.append("")
    parts.append(
        "These are the facts the chapter must cover, in approximate order. "
        "Weave them into FLOWING PARAGRAPHS — not one sentence per fact. "
        "Group related facts (e.g. all separations of earth and sky) into a "
        "single paragraph with connective prose. Vary sentence length."
    )
    parts.append("")

    for c in clusters:
        parts.append(f"- [{c.seq}] **{c.archetype_name}** {c.canonical_verb} → {c.canonical_outcome}")
        extras: list[str] = []
        if c.materials:
            extras.append(f"materials: {', '.join(c.materials[:6])}")
        if c.vivid_details:
            details = []
            for d in c.vivid_details[:4]:
                detail = d.get("detail") if isinstance(d, dict) else str(d)
                if detail:
                    details.append(detail[:140])
            if details:
                extras.append("vivid: " + " | ".join(details))
        if c.source_quotes:
            quotes = []
            for q in c.source_quotes[:2]:
                quote = q.get("quote") if isinstance(q, dict) else str(q)
                if quote:
                    quotes.append(f'"{quote[:120]}"')
            if quotes:
                extras.append("quotes: " + " ".join(quotes))
        for e in extras:
            parts.append(f"    · {e}")

    parts.append("")
    parts.append(
        "Now write the chapter as flowing prose. 1500-2500 words, 5-10 paragraphs. "
        "No bullet points. No 'according to' framing. Present tense."
    )

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
        temperature=0.55,
        max_tokens=8192,
    )

    narrative = str(result.get("narrative_text") or "").strip()
    used = [str(x) for x in (result.get("archetypes_used") or []) if x]
    if not used:
        used = list({c.archetype_name for c in clusters})

    return {"narrative_text": narrative, "archetypes_used": used}
