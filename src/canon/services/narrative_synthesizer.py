"""Narrative Synthesizer: generates the unified ancient history narrative using DeepSeek.

Implements all 16 Laws of Synthesis to produce a single, continuous, source-backed
narrative across all epochs and chapters. Each chapter is generated sequentially so
the prior chapter's text provides narrative continuity (Law 10, 12).
"""

from __future__ import annotations

import json
import logging
import re
import uuid

import httpx
from sqlalchemy import select, func, text, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.canon_score import CanonScore
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.enums import CanonicalType
from src.canon.models.narration_packet import NarrationPacket
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.world_packet import WorldPacket
from src.canon.models.system_a import SASourceRecord, SASourceVersion

logger = logging.getLogger(__name__)

NARRATIVE_SYSTEM_PROMPT = """You are the narrator of a unified ancient world history — an alternative bible woven from every surviving tradition on Earth.

## YOUR ABSOLUTE LAWS (violating any is a failure):

1. MYTH AS RECORDED MEMORY: Treat all ancient narratives as records of perceived events. No dismissal. No blind literalization. Always data input.

2. SOURCE-ONLY INPUT: You may only use information derived from the source data provided below. No external theory. No modern explanation. No inferred intent.

3. NO INTERPRETATION INJECTION: Do NOT introduce meaning, purpose, motive, symbolism, or causation ("why") unless explicitly present in a source.

4. AGE-WEIGHTED PRIORITY: Earlier recorded versions of a narrative get higher priority. Later versions are supporting or derivative. Later cannot override earlier without stronger pattern support.

5. CROSS-CULTURAL CONVERGENCE: Independent recurrence of a pattern across separate cultures increases its structural weight. Requirements: geographic separation OR cultural independence, similar structure (not just vague similarity).

6. DISTRIBUTION INDEPENDENCE: Frequency or popularity of a narrative does NOT increase its truth weight. Modern prominence is irrelevant.

7. PATTERN DOMINANCE: Recurring structural patterns outweigh isolated claims. One-off claims = weak. Repeated structure across sources = strong.

8. ENTITY CONVERGENCE: When entities from different cultures share the same role, actions, context, and pattern, they may be treated as referring to the same being/entity. The equivalences provided below have been verified.

9. MINIMAL ASSUMPTION: When multiple interpretations are possible, select the one requiring the fewest unsupported assumptions.

10. NARRATIVE CONTINUITY: Construct a single continuous timeline that integrates all compatible sources without contradiction. No "this culture says / that culture says" framing. Instead: unified narrative with merged or parallel threads where needed.

11. CONTRADICTION HANDLING: When sources conflict, prioritize the older source with stronger pattern support, or maintain parallel accounts within the same timeline.

12. STRUCTURAL CONSISTENCY: Once an entity, event, or pattern is established, it must remain consistent across all outputs.

13. IMAGE CONSTRAINT: Visual evidence informs environment and material context but cannot define narrative meaning.

14. TRACEABILITY: Every narrative element must be traceable to at least one source or pattern cluster.

15. SYNTHESIS CONSTRAINT: Combine sources into a unified narrative only where compatibility exists; otherwise, layer or parallelize them.

16. ANCIENT TIME ANCHORING: Ancient sources' own timelines and sequences are prioritized over modern chronological reconstructions.

## WRITING STYLE:
- Write in an epic, cinematic, authoritative tone — as if narrating a grand history
- Use present tense for vividness where appropriate
- Do NOT hedge with "perhaps" or "it is believed" — state what the sources state
- Weave cultures together, don't segregate them
- When multiple cultures describe the same event, merge their accounts into one narrative thread
- Include specific names, places, and details from the sources
- This should read like an alternative bible — profound, sweeping, specific

## OUTPUT FORMAT:
Return ONLY valid JSON with this structure:
{
  "narrative_text": "The full narrative text for this chapter (1000-3000 words)",
  "key_claims": [
    {"claim": "brief claim statement", "source_ids": ["id1", "id2"], "score": 0.0-1.0, "cultures": ["culture1", "culture2"]}
  ],
  "image_prompts": [
    {"description": "detailed visual scene description for image generation", "period": "time period", "mood": "atmosphere/tone", "reference_artifacts": ["artifact name"]}
  ]
}"""


class NarrativeSynthesizer:

    async def _gather_chapter_context(
        self, session: AsyncSession, chapter: CanonicalChapter, prior_narrative: str | None
    ) -> dict:
        """Gather all scored entities, source evidence, and world context for a chapter."""
        epoch = await session.get(CanonicalEpoch, chapter.epoch_id)

        deps_q = select(CanonDependency).where(
            CanonDependency.parent_type == CanonicalType.CHAPTER,
            CanonDependency.parent_id == chapter.id,
        )
        deps = (await session.execute(deps_q)).scalars().all()

        actors, events, places = [], [], []
        entity_scores: dict[str, dict] = {}

        for dep in deps:
            score_q = select(CanonScore).where(
                CanonScore.canonical_type == dep.child_type,
                CanonScore.canonical_id == dep.child_id,
            )
            score = (await session.execute(score_q)).scalar_one_or_none()

            if dep.child_type == CanonicalType.ACTOR:
                a = await session.get(CanonicalActor, dep.child_id)
                if a and a.is_current:
                    actors.append(a)
                    if score:
                        entity_scores[str(a.id)] = {
                            "name": a.canonical_name,
                            "final_score": score.final_score,
                            "tier": "core_canon" if score.final_score > 0.7 else "canon_with_caution" if score.final_score > 0.4 else "branch",
                            "cultures": await self._get_entity_cultures(session, dep.child_type, dep.child_id),
                        }
            elif dep.child_type == CanonicalType.EVENT:
                e = await session.get(CanonicalEvent, dep.child_id)
                if e and e.is_current:
                    events.append(e)
                    if score:
                        entity_scores[str(e.id)] = {
                            "name": e.canonical_name,
                            "final_score": score.final_score,
                            "tier": "core_canon" if score.final_score > 0.7 else "canon_with_caution" if score.final_score > 0.4 else "branch",
                            "cultures": await self._get_entity_cultures(session, dep.child_type, dep.child_id),
                        }
            elif dep.child_type == CanonicalType.PLACE:
                p = await session.get(CanonicalPlace, dep.child_id)
                if p and p.is_current:
                    places.append(p)

        source_excerpts = await self._gather_source_excerpts(session, chapter)

        narration_q = select(NarrationPacket).where(
            NarrationPacket.chapter_id == chapter.id
        ).order_by(NarrationPacket.version.desc()).limit(1)
        narration = (await session.execute(narration_q)).scalar_one_or_none()

        world_q = select(WorldPacket).where(
            WorldPacket.chapter_id == chapter.id
        ).order_by(WorldPacket.packet_version.desc()).limit(1)
        world = (await session.execute(world_q)).scalar_one_or_none()

        equivalences = await self._gather_equivalences(session)

        return {
            "epoch": epoch,
            "chapter": chapter,
            "actors": actors,
            "events": events,
            "places": places,
            "entity_scores": entity_scores,
            "source_excerpts": source_excerpts,
            "narration": narration,
            "world_packet": world,
            "prior_narrative": prior_narrative,
            "equivalences": equivalences,
        }

    async def _get_entity_cultures(
        self, session: AsyncSession, canonical_type: CanonicalType, canonical_id: uuid.UUID
    ) -> list[str]:
        q = (
            select(distinct(SASourceRecord.culture))
            .select_from(CanonSupportLink)
            .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
            .where(
                CanonSupportLink.canonical_type == canonical_type,
                CanonSupportLink.canonical_id == canonical_id,
                SASourceRecord.culture.isnot(None),
                SASourceRecord.culture != "",
            )
        )
        try:
            result = await session.execute(q)
            return [row[0] for row in result.all()]
        except Exception:
            return []

    async def _gather_source_excerpts(
        self, session: AsyncSession, chapter: CanonicalChapter
    ) -> list[dict]:
        """Gather source text excerpts linked to entities in this chapter."""
        deps_q = select(CanonDependency.child_type, CanonDependency.child_id).where(
            CanonDependency.parent_type == CanonicalType.CHAPTER,
            CanonDependency.parent_id == chapter.id,
        )
        deps = (await session.execute(deps_q)).all()

        excerpts = []
        seen_sources = set()

        for child_type, child_id in deps:
            links_q = (
                select(CanonSupportLink, SASourceRecord)
                .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
                .where(
                    CanonSupportLink.canonical_type == child_type,
                    CanonSupportLink.canonical_id == child_id,
                )
                .order_by(CanonSupportLink.weight.desc())
                .limit(5)
            )
            try:
                for link, sr in (await session.execute(links_q)).all():
                    if sr.id in seen_sources:
                        continue
                    seen_sources.add(sr.id)

                    sv_q = select(SASourceVersion.text_extracted).where(
                        SASourceVersion.source_record_id == sr.id
                    ).limit(1)
                    sv_result = await session.execute(sv_q)
                    text_row = sv_result.first()
                    excerpt_text = ""
                    if text_row and text_row[0]:
                        excerpt_text = text_row[0][:800]

                    excerpts.append({
                        "source_id": str(sr.id),
                        "title": sr.canonical_title,
                        "culture": sr.culture or "Unknown",
                        "excerpt": excerpt_text,
                        "weight": link.weight,
                    })
            except Exception:
                continue

        return sorted(excerpts, key=lambda x: x["weight"], reverse=True)[:20]

    async def _gather_equivalences(self, session: AsyncSession) -> list[dict]:
        try:
            result = await session.execute(text("""
                SELECT primary_entity_type, primary_entity_id,
                       equivalent_entity_type, equivalent_entity_id,
                       merge_basis, confidence, evidence_json
                FROM entity_equivalences
                ORDER BY confidence DESC LIMIT 50
            """))
            return [dict(row._mapping) for row in result.all()]
        except Exception:
            return []

    def _build_narrative_prompt(self, ctx: dict) -> str:
        ch = ctx["chapter"]
        parts = [f"# Chapter: {ch.title}"]

        if ctx["epoch"]:
            parts.append(f"Epoch: {ctx['epoch'].title}")
        if ch.time_start is not None or ch.time_end is not None:
            parts.append(f"Time period: {ch.time_start or '?'} to {ch.time_end or '?'}")

        parts.append("\n## ENTITY SCORES AND CLASSIFICATIONS:")
        for eid, info in ctx["entity_scores"].items():
            cultures_str = ", ".join(info["cultures"]) if info["cultures"] else "unattributed"
            parts.append(f"  - {info['name']}: score={info['final_score']:.2f}, tier={info['tier']}, cultures=[{cultures_str}]")

        if ctx["actors"]:
            parts.append("\n## ACTORS:")
            for a in ctx["actors"]:
                parts.append(f"  - {a.canonical_name} ({a.actor_type.value}): {a.summary or 'No summary'}")

        if ctx["events"]:
            parts.append("\n## EVENTS:")
            for e in ctx["events"]:
                parts.append(f"  - {e.canonical_name} ({e.event_type.value}): {e.summary or 'No summary'}")

        if ctx["places"]:
            parts.append("\n## PLACES:")
            for p in ctx["places"]:
                parts.append(f"  - {p.canonical_name} ({p.place_type.value}): {p.summary or 'No summary'}")

        if ctx["source_excerpts"]:
            parts.append("\n## SOURCE EVIDENCE (ranked by weight):")
            for ex in ctx["source_excerpts"][:15]:
                parts.append(f"  [{ex['culture']}] {ex['title']} (weight={ex['weight']:.1f}):")
                parts.append(f"    {ex['excerpt'][:500]}")

        if ctx["world_packet"]:
            wp = ctx["world_packet"]
            if wp.world_summary:
                parts.append(f"\n## WORLD CONTEXT:\n{wp.world_summary}")
            if wp.environment_profile_json:
                parts.append(f"Environment: {json.dumps(wp.environment_profile_json)[:300]}")
            if wp.material_culture_json:
                parts.append(f"Material culture: {json.dumps(wp.material_culture_json)[:300]}")

        if ctx["equivalences"]:
            parts.append("\n## VERIFIED ENTITY EQUIVALENCES:")
            for eq in ctx["equivalences"][:10]:
                parts.append(f"  - {eq.get('primary_entity_type', '')} ↔ {eq.get('equivalent_entity_type', '')} ({eq.get('merge_basis', '')}, confidence={eq.get('confidence', 0):.2f})")

        if ctx["prior_narrative"]:
            last_500 = ctx["prior_narrative"][-1500:]
            parts.append(f"\n## PRIOR CHAPTER (continue from here):\n...{last_500}")

        return "\n".join(parts)

    async def _call_deepseek(self, prompt: str) -> dict:
        if not settings.deepseek_api_key:
            raise RuntimeError(
                "WORLD_DEEPSEEK_API_KEY is not set. Narrative synthesis requires DeepSeek."
            )

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "max_tokens": 8192,
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            raw = data["choices"][0]["message"]["content"]
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON in DeepSeek narrative response")
            return {"narrative_text": raw[:5000], "key_claims": [], "image_prompts": []}
        except RuntimeError:
            raise
        except Exception:
            logger.exception("DeepSeek narrative synthesis call failed")
            return {"narrative_text": "", "key_claims": [], "image_prompts": []}

    async def synthesize_chapter(
        self, session: AsyncSession, chapter: CanonicalChapter, prior_narrative: str | None = None
    ) -> StoryChapter:
        """Generate the narrative for a single chapter."""
        ctx = await self._gather_chapter_context(session, chapter, prior_narrative)
        prompt = self._build_narrative_prompt(ctx)
        result = await self._call_deepseek(prompt)

        narrative = result.get("narrative_text", "")
        claims = result.get("key_claims", [])
        image_prompts = result.get("image_prompts", [])

        existing_q = select(StoryChapter).where(
            StoryChapter.chapter_id == chapter.id
        ).order_by(StoryChapter.synthesis_version.desc()).limit(1)
        existing = (await session.execute(existing_q)).scalar_one_or_none()

        if existing:
            existing.narrative_text = narrative
            existing.claims_json = claims
            existing.image_prompts_json = image_prompts
            existing.word_count = len(narrative.split())
            existing.synthesis_version += 1
            return existing

        story = StoryChapter(
            id=uuid.uuid4(),
            chapter_id=chapter.id,
            epoch_id=chapter.epoch_id,
            narrative_text=narrative,
            claims_json=claims,
            image_prompts_json=image_prompts,
            synthesis_version=1,
            word_count=len(narrative.split()),
        )
        session.add(story)
        return story

    async def run_full_synthesis(
        self,
        session: AsyncSession,
        *,
        epoch_orders: list[int] | None = None,
        max_chapters: int | None = None,
        skip_existing: bool = False,
    ) -> dict:
        """Generate narrative for chapters in epoch/chapter order.

        Args:
            epoch_orders: limit to specific epoch_order values (e.g. [0,1,2,3])
            max_chapters: stop after this many chapters
            skip_existing: if True, skip chapters that already have a StoryChapter
        """
        epochs_q = select(CanonicalEpoch).where(
            CanonicalEpoch.is_current.is_(True)
        ).order_by(CanonicalEpoch.epoch_order)
        if epoch_orders is not None:
            epochs_q = epochs_q.where(CanonicalEpoch.epoch_order.in_(epoch_orders))
        epochs = (await session.execute(epochs_q)).scalars().all()

        total_chapters = 0
        total_words = 0
        prior_narrative: str | None = None

        for epoch in epochs:
            chapters_q = select(CanonicalChapter).where(
                CanonicalChapter.epoch_id == epoch.id,
                CanonicalChapter.is_current.is_(True),
            ).order_by(CanonicalChapter.chapter_order)
            chapters = (await session.execute(chapters_q)).scalars().all()

            for ch in chapters:
                if max_chapters is not None and total_chapters >= max_chapters:
                    break

                if skip_existing:
                    existing = (await session.execute(
                        select(StoryChapter.id).where(StoryChapter.chapter_id == ch.id).limit(1)
                    )).scalar_one_or_none()
                    if existing:
                        sv = (await session.execute(
                            select(StoryChapter.narrative_text).where(StoryChapter.chapter_id == ch.id)
                            .order_by(StoryChapter.synthesis_version.desc()).limit(1)
                        )).scalar_one_or_none()
                        if sv:
                            prior_narrative = sv
                        continue

                logger.info("Synthesizing [%d/%s] %s", total_chapters + 1, max_chapters or "all", ch.title)
                story = await self.synthesize_chapter(session, ch, prior_narrative)
                prior_narrative = story.narrative_text
                total_chapters += 1
                total_words += story.word_count or 0

                await session.commit()
                logger.info("  → committed chapter %d (%d words)", total_chapters, story.word_count or 0)

            if max_chapters is not None and total_chapters >= max_chapters:
                break

        logger.info("Synthesized %d chapters, ~%d words total", total_chapters, total_words)
        return {"chapters_synthesized": total_chapters, "total_words": total_words}
