"""Narrative Synthesizer: generates the unified ancient history narrative using DeepSeek.

Two-phase approach:
  Phase 1 — Plan: DeepSeek designs thematic chapters per epoch from ALL cross-cultural data.
  Phase 2 — Write: For each planned chapter, DeepSeek generates a unified narrative that
            weaves all cultures together, governed by the 16 Laws of Synthesis.

Each chapter is committed to the DB immediately so the frontend can show live progress.
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
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.story_outline import StoryOutline
from src.canon.models.system_a import SASourceRecord, SASourceVersion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are the architect of a unified ancient world history — an alternative bible woven from every surviving tradition on Earth.

You are designing the TABLE OF CONTENTS for one epoch of this history. You will receive a summary of ALL entities, themes, and source traditions from this epoch across every culture on the planet.

Your job is to organize this into 5-15 thematic chapters that tell a unified narrative.

## STRUCTURE RULES:

### For EARLY EPOCHS (Creation, Age of Gods, Flood, Dawn of Civilization):
These epochs describe universal events that virtually all cultures share memories of. The chapters must be FULLY UNIFIED — weaving all cultures together around shared themes:
- Creation from void/chaos → multiple cultures merged into one telling
- Gods/sky beings descend → Sumerian, Hebrew, Hindu, etc. merged
- Creation of mankind → clay/earth/breath traditions woven together
- The flood → one chapter weaving ALL flood accounts

### For LATER EPOCHS (Rise of Cities, Age of Empires, Heroes, Iron Age, Classical):
As history progresses, cultures genuinely diverge — the Aztecs migrate to Mesoamerica, the Chinese develop independently, the Greeks follow their own path. For these epochs:
1. START with chapters that cover SHARED patterns across the epoch (e.g., "The Rise of City-States" weaving Sumer, Indus, and Early Maya together)
2. THEN follow with REGIONAL NARRATIVE ARCS that track the diverging stories (e.g., "The Nile Kingdoms", "The Indus Valley", "Across the Western Ocean")
3. Regional chapters should still reference cross-cultural parallels and connections where they exist
4. End the epoch with a chapter that reconnects the threads — common patterns that emerged independently

### For ALL EPOCHS:
1. NEVER make a chapter about just one culture with no connection to others
2. Even regional chapters must note parallels ("While the Egyptians built pyramids, across the ocean the Maya independently raised similar structures")
3. Group by THEME first, REGION second
4. Order chapters in narrative/chronological sequence within the epoch
5. Each chapter should have a compelling, epic title (like a book of the bible)
6. Include a brief summary (2-3 sentences) of what the chapter covers
7. List the key themes/motifs that belong in each chapter
8. Aim for 5-15 chapters depending on the richness of the epoch

OUTPUT FORMAT — return ONLY valid JSON:
{
  "chapters": [
    {
      "chapter_number": 1,
      "title": "Epic chapter title",
      "summary": "2-3 sentence summary of what this chapter covers, naming specific cultures that will be woven together",
      "themes": ["theme1", "theme2", "theme3"],
      "time_hint": "Before time / primordial / ~3000 BCE",
      "scope": "universal" or "regional",
      "regions": ["Mesopotamia", "Egypt"] (only for regional chapters)
    }
  ]
}"""

NARRATIVE_SYSTEM_PROMPT = """You are writing a unified ancient world history — one continuous story reconstructed from every surviving tradition on Earth.

## THE THREE CARDINAL RULES (violating any is total failure):

### RULE 1: ONE STORY, NOT A COMPARISON
You are narrating WHAT HAPPENED — not what each culture says happened. Write ONE event that occurred ONCE, enriched by details from all sources. The reader must NEVER feel they are reading about different cultures' versions.

FORBIDDEN: "In Mesopotamia... Meanwhile in Egypt... The Greeks tell of... Far to the west... In one tradition... In another..."
FORBIDDEN: Any sentence that begins with a culture name, region, or "in one/another" framing.
FORBIDDEN: Walking through cultures one by one, even if wrapped in merged-entity language.

### RULE 2: OLDEST SOURCES FORM THE BACKBONE
The sources are listed below in priority order — oldest and highest-weighted first. The oldest source's account is the SPINE of your narrative. Later sources ADD details to that same story. They do not create parallel stories. If the Sumerian account is older than the Hebrew account, the Sumerian details form the primary narrative and Hebrew details are woven in as additional texture — never the reverse.

### RULE 3: EVERY SENTENCE MUST TRACE TO A SOURCE
Do NOT invent atmosphere, descriptions, or transitions not found in any source. Do NOT add modern analysis or interpretation ("This is not merely a fall but a transformation..."). Do NOT write cinematic scene-setting that no ancient text describes. If you cannot point to a source for a sentence, delete it.

## HOW TO WRITE:
- Direct, authoritative tone — a historian recounting events based on evidence
- Present tense for vividness where appropriate
- State what the sources state. No hedging ("perhaps", "it is believed")
- Include specific names, places, details from the sources
- When sources disagree on a detail, fold ALL versions into ONE rich description as facets of the same act — never present them as alternatives

## CORRECT EXAMPLE:
"[[actor:The Divine Craftsman]] (called Enki in the Sumerian hymns, Khnum in the Egyptian, Prometheus in the Greek) takes the raw earth — clay, dust, silt — and works it with divine hands upon the turning wheel. Into this shaped form, the blood of a slain god is mixed, binding mortal flesh to divine substance. Then comes the animating act: a breath, blown into the nostrils of the still figure, filling it with the vital force. The clay stirs. The eyes open."
Why this works: Details from Sumer (clay + blood), Egypt (potter's wheel), Hebrew (breath in nostrils) are present but woven into ONE continuous act. No culture is credited for individual details.

## ENTITY NAMING:
- Use DESCRIPTIVE ARCHETYPE NAMES for merged entities: "The Creator", "The First Conscious Being", "The Mother Goddess" — never privilege one culture's name
- On FIRST mention, list ALL cultural names parenthetically: "The Creator (known as Enki to the Sumerians, Khnum to the Egyptians, Yahweh to the Hebrews)"
- After first mention, use ONLY the archetype name

## LAWS OF SYNTHESIS:
1. MYTH AS RECORDED MEMORY: Treat all ancient narratives as records of perceived events
2. SOURCE-ONLY INPUT: Only use information from the source data provided. No external theory
3. NO INTERPRETATION: Do not introduce meaning, symbolism, or causation unless in a source
4. AGE-WEIGHTED PRIORITY: Earlier versions get higher priority. Later cannot override earlier
5. CROSS-CULTURAL CONVERGENCE: Independent recurrence across cultures increases weight
6. DISTRIBUTION INDEPENDENCE: Popularity does not increase truth weight
7. PATTERN DOMINANCE: Recurring patterns outweigh isolated claims
8. ENTITY CONVERGENCE: Entities sharing role/actions/context across cultures ARE the same being
9. MINIMAL ASSUMPTION: Fewest unsupported assumptions wins
10. NARRATIVE CONTINUITY: Single continuous timeline, no "this culture says / that culture says"
11. CONTRADICTION HANDLING: Fold contradictions into one richer description, prioritize older source
12. STRUCTURAL CONSISTENCY: Established entities/patterns remain consistent
13. TRACEABILITY: Every narrative element traceable to at least one source
14. ANCIENT TIME ANCHORING: Ancient timelines over modern reconstructions

## CROSS-CULTURAL BALANCE:
- Include at least 6 cultural traditions per chapter
- No single culture may dominate more than ~25% of the narrative
- This is a PLANETARY history, not Near Eastern with footnotes

## SOURCE ERA FILTERING:
- ONLY ancient primary sources (composed BCE or earliest centuries CE)
- REJECT medieval/modern commentary: Zohar, Talmud, Church Fathers, etc.
- Valid: Torah, Vedas, Enuma Elish, Pyramid Texts, Avesta, Popol Vuh, etc.

## ENTITY ANNOTATION:
On FIRST mention of a key entity, wrap with: [[type:Archetype Name]]
Types: actor, event, place. Example: [[actor:The Divine Craftsman]] or [[place:The Sacred Garden]]
Use ARCHETYPE names, not culture-specific: [[actor:The Creator]] not [[actor:Enki]]
Do NOT annotate individual cultural names of a merged entity separately.
Aim for 15-30 annotations per chapter.

## OUTPUT FORMAT:
Return ONLY valid JSON:
{
  "narrative_text": "The full narrative text (1500-3000 words) with [[type:Name]] annotations",
  "key_claims": [
    {"claim": "brief claim", "source_ids": ["id1", "id2"], "score": 0.0-1.0, "cultures": ["culture1", "culture2"]}
  ],
  "image_prompts": [
    {"description": "visual scene based on oldest depictions", "period": "time", "mood": "tone", "reference_artifacts": ["artifact"]}
  ],
  "entity_mentions": [
    {"name": "The Divine Craftsman", "type": "actor", "also_known_as": ["Enki", "Khnum", "Prometheus"], "cultures": ["Sumerian", "Egyptian", "Greek"], "role_in_chapter": "brief role"}
  ]
}"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class NarrativeSynthesizer:

    # -----------------------------------------------------------------------
    # Phase 1: Plan the book — design thematic chapters per epoch
    # -----------------------------------------------------------------------

    async def plan_epoch_outline(
        self, _session: AsyncSession | None, epoch: CanonicalEpoch
    ) -> list[StoryOutline]:
        """Use DeepSeek to design unified thematic chapters for one epoch.

        Uses separate DB sessions for read and write to avoid connection
        timeouts during the long DeepSeek API call (up to 3 minutes).
        """
        from src.canon.database import async_session_factory

        logger.info("Planning outline for epoch: %s", epoch.title)

        # Phase A: Read data in a short-lived session
        epoch_id = epoch.id
        epoch_title = epoch.title
        time_start = epoch.time_start
        time_end = epoch.time_end
        async with async_session_factory() as read_session:
            summary = await self._build_epoch_summary(read_session, epoch)

        prompt = f"""# EPOCH: {epoch_title}
Time range: {time_start or 'Mythological/undated'} to {time_end or 'Mythological/undated'}

{summary}

Design 5-15 thematic chapters that weave ALL these cultures and traditions together into a unified narrative for this epoch."""

        # Phase B: Call DeepSeek (no DB connection held)
        result = await self._call_deepseek(prompt, system=PLANNER_SYSTEM_PROMPT)
        chapters_data = result.get("chapters", [])

        if not chapters_data:
            logger.warning("No chapters planned for epoch %s", epoch_title)
            return []

        # Phase C: Write results using a fresh session
        async with async_session_factory() as write_session:
            await write_session.execute(
                text("DELETE FROM story_chapters WHERE story_outline_id IN (SELECT id FROM story_outlines WHERE epoch_id = :eid)"),
                {"eid": str(epoch_id)},
            )
            await write_session.execute(
                text("DELETE FROM story_outlines WHERE epoch_id = :eid"),
                {"eid": str(epoch_id)},
            )

            outlines = []
            for ch in chapters_data:
                outline = StoryOutline(
                    id=uuid.uuid4(),
                    epoch_id=epoch_id,
                    chapter_number=ch.get("chapter_number", len(outlines) + 1),
                    title=ch.get("title", f"Chapter {len(outlines) + 1}"),
                    summary=ch.get("summary", ""),
                    themes=ch.get("themes", []),
                    time_hint=ch.get("time_hint"),
                    scope=ch.get("scope", "universal"),
                    regions=ch.get("regions"),
                    outline_version=1,
                )
                write_session.add(outline)
                outlines.append(outline)

            await write_session.commit()

        logger.info("Planned %d chapters for epoch: %s", len(outlines), epoch_title)
        return outlines

    async def plan_all_epochs(
        self, session: AsyncSession, *, epoch_orders: list[int] | None = None
    ) -> dict:
        """Plan outlines for all (or selected) epochs."""
        from src.canon.database import async_session_factory

        async with async_session_factory() as read_session:
            q = select(CanonicalEpoch).where(
                CanonicalEpoch.is_current.is_(True)
            ).order_by(CanonicalEpoch.epoch_order)
            if epoch_orders is not None:
                q = q.where(CanonicalEpoch.epoch_order.in_(epoch_orders))
            epochs = list((await read_session.execute(q)).scalars().all())

        total = 0
        for epoch in epochs:
            outlines = await self.plan_epoch_outline(None, epoch)
            total += len(outlines)

        return {"epochs_planned": len(epochs), "total_chapters_planned": total}

    async def _build_epoch_summary(
        self, session: AsyncSession, epoch: CanonicalEpoch
    ) -> str:
        """Build a rich summary of entities and sources in this epoch for the planner.

        Uses efficient SQL queries to avoid loading 100K+ entities into memory.
        Extracts culture names from canonical chapter titles and uses LIMIT
        to keep the summary concise enough for the LLM context window.
        """
        # Extract cultures from canonical chapter titles (fast — just string parsing)
        ch_q = select(CanonicalChapter.title, CanonicalChapter.chapter_summary).where(
            CanonicalChapter.epoch_id == epoch.id,
            CanonicalChapter.is_current.is_(True),
        ).order_by(CanonicalChapter.chapter_order)
        ch_rows = (await session.execute(ch_q)).all()

        if not ch_rows:
            return "No data available for this epoch."

        import re
        culture_pattern = re.compile(r':\s*(.+?)(?:\s+Tradition)?$')
        cultures = set()
        for title, _ in ch_rows:
            m = culture_pattern.search(title)
            if m and m.group(1).strip().lower() != "overview":
                cultures.add(m.group(1).strip())

        # Use efficient single queries with LIMITs for actors/events/places
        actors_q = text("""
            SELECT DISTINCT a.canonical_name, a.actor_type, LEFT(a.summary, 150)
            FROM canonical_actors a
            JOIN canon_dependencies d ON d.child_type = 'actor' AND d.child_id = a.id
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :eid AND c.is_current = true AND a.is_current = true
            ORDER BY a.canonical_name
            LIMIT 100
        """)
        events_q = text("""
            SELECT DISTINCT e.canonical_name, e.event_type, LEFT(e.summary, 150)
            FROM canonical_events e
            JOIN canon_dependencies d ON d.child_type = 'event' AND d.child_id = e.id
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :eid AND c.is_current = true AND e.is_current = true
            ORDER BY e.canonical_name
            LIMIT 100
        """)
        places_q = text("""
            SELECT DISTINCT p.canonical_name, p.place_type, LEFT(p.summary, 150)
            FROM canonical_places p
            JOIN canon_dependencies d ON d.child_type = 'place' AND d.child_id = p.id
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :eid AND c.is_current = true AND p.is_current = true
            ORDER BY p.canonical_name
            LIMIT 50
        """)

        params = {"eid": str(epoch.id)}
        actor_rows = (await session.execute(actors_q, params)).all()
        event_rows = (await session.execute(events_q, params)).all()
        place_rows = (await session.execute(places_q, params)).all()

        parts = [f"## {len(cultures)} distinct cultures contribute to this epoch"]
        if cultures:
            parts.append(f"Cultures: {', '.join(sorted(cultures)[:60])}")

        parts.append(f"\n## KEY ACTORS ({len(actor_rows)} shown):")
        for name, atype, summary in actor_rows:
            parts.append(f"  - {name} ({atype}): {summary or 'No summary'}")

        parts.append(f"\n## KEY EVENTS ({len(event_rows)} shown):")
        for name, etype, summary in event_rows:
            parts.append(f"  - {name} ({etype}): {summary or 'No summary'}")

        parts.append(f"\n## KEY PLACES ({len(place_rows)} shown):")
        for name, ptype, summary in place_rows:
            parts.append(f"  - {name} ({ptype}): {summary or 'No summary'}")

        equivalences = await self._gather_equivalences(session)
        if equivalences:
            parts.append("\n## VERIFIED CROSS-CULTURAL ENTITY EQUIVALENCES:")
            parts.append("These entities are THE SAME being across cultures. DO NOT pick one culture's name as primary.")
            parts.append("Instead, refer to them by a DESCRIPTIVE ARCHETYPE NAME based on their role/function.")
            parts.append("List ALL cultural names parenthetically on first mention.")
            for eq in equivalences:
                all_names = [eq["primary_name"]] + eq["equivalents"][:8]
                names_str = ", ".join(all_names)
                parts.append(f"  - SAME ENTITY: {names_str}")

        return "\n".join(parts)

    # -----------------------------------------------------------------------
    # Phase 2: Write unified narrative per planned chapter
    # -----------------------------------------------------------------------

    async def synthesize_unified_chapter(
        self,
        _session: AsyncSession | None,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        prior_narrative: str | None = None,
    ) -> StoryChapter:
        """Generate unified cross-cultural narrative for one planned chapter.

        Uses separate sessions to avoid DB connection timeouts during
        the long DeepSeek API call.
        """
        from src.canon.database import async_session_factory

        # Phase A: Build prompt (read DB, then release connection)
        async with async_session_factory() as read_session:
            prompt = await self._build_unified_prompt(read_session, outline, epoch, prior_narrative)
        outline_id = outline.id
        epoch_id = epoch.id

        # Phase B: Call DeepSeek (no DB connection held)
        result = await self._call_deepseek(prompt, system=NARRATIVE_SYSTEM_PROMPT)

        narrative = result.get("narrative_text", "")
        claims = result.get("key_claims", [])
        image_prompts = result.get("image_prompts", [])
        entity_mentions = result.get("entity_mentions", [])

        # Phase C: Write results with fresh session
        async with async_session_factory() as write_session:
            resolved_mentions = await self._resolve_entity_mentions(write_session, entity_mentions)

            existing_q = select(StoryChapter).where(
                StoryChapter.story_outline_id == outline_id
            ).order_by(StoryChapter.synthesis_version.desc()).limit(1)
            existing = (await write_session.execute(existing_q)).scalar_one_or_none()

            if existing:
                existing.narrative_text = narrative
                existing.claims_json = claims
                existing.image_prompts_json = image_prompts
                existing.entity_mentions_json = resolved_mentions
                existing.word_count = len(narrative.split())
                existing.synthesis_version += 1
                await write_session.execute(
                    text("DELETE FROM story_chapter_audio WHERE story_chapter_id = :cid"),
                    {"cid": str(existing.id)},
                )
                await write_session.commit()
                return existing

            story = StoryChapter(
                id=uuid.uuid4(),
                story_outline_id=outline_id,
                chapter_id=None,
                epoch_id=epoch_id,
                narrative_text=narrative,
                claims_json=claims,
                image_prompts_json=image_prompts,
                entity_mentions_json=resolved_mentions,
                synthesis_version=1,
                word_count=len(narrative.split()),
            )
            write_session.add(story)
            await write_session.commit()
            return story

    async def _resolve_entity_mentions(
        self, session: AsyncSession, mentions: list[dict]
    ) -> list[dict]:
        """Resolve entity names from DeepSeek output to canonical entity IDs.

        Strategy:
        1. Exact match on canonical_name
        2. If no match, try each name in also_known_as
        3. If still no match, try ILIKE fuzzy match on the primary name
        """
        table_map = {
            "actor": CanonicalActor,
            "event": CanonicalEvent,
            "place": CanonicalPlace,
        }

        resolved = []
        for m in mentions:
            name = m.get("name", "")
            entity_type = m.get("type", "actor")
            if not name or entity_type not in table_map:
                resolved.append(m)
                continue

            tbl = table_map[entity_type]
            canonical_id = None

            # Build list of names to try: primary name + all also_known_as
            names_to_try = [name.strip()]
            for aka in m.get("also_known_as", []):
                if aka and aka.strip():
                    names_to_try.append(aka.strip())

            # 1. Exact match on any name
            for try_name in names_to_try:
                if canonical_id:
                    break
                try:
                    q = select(tbl.id).where(
                        func.lower(tbl.canonical_name) == try_name.lower(),
                        tbl.is_current.is_(True),
                    ).limit(1)
                    row = (await session.execute(q)).scalar_one_or_none()
                    if row:
                        canonical_id = str(row)
                except Exception:
                    pass

            # 2. ILIKE fuzzy match on the primary name (for archetype names)
            if not canonical_id:
                try:
                    # Strip "The " prefix for better matching
                    search_name = name.strip()
                    if search_name.lower().startswith("the "):
                        search_name = search_name[4:]
                    q = select(tbl.id).where(
                        tbl.canonical_name.ilike(f"%{search_name}%"),
                        tbl.is_current.is_(True),
                    ).limit(1)
                    row = (await session.execute(q)).scalar_one_or_none()
                    if row:
                        canonical_id = str(row)
                except Exception:
                    pass

            resolved.append({
                **m,
                "canonical_id": canonical_id,
            })
        return resolved

    async def run_full_synthesis(
        self,
        session: AsyncSession,
        *,
        epoch_orders: list[int] | None = None,
        skip_existing: bool = False,
    ) -> dict:
        """Generate narrative for all planned outline chapters.

        Each chapter gets its own fresh sessions to avoid connection
        timeouts during long DeepSeek calls.
        """
        from src.canon.database import async_session_factory

        # Load all epochs + outlines quickly, then release connection
        async with async_session_factory() as read_session:
            q = select(CanonicalEpoch).where(
                CanonicalEpoch.is_current.is_(True)
            ).order_by(CanonicalEpoch.epoch_order)
            if epoch_orders is not None:
                q = q.where(CanonicalEpoch.epoch_order.in_(epoch_orders))
            epochs = list((await read_session.execute(q)).scalars().all())

            epoch_outlines: list[tuple[CanonicalEpoch, list[StoryOutline]]] = []
            for epoch in epochs:
                outlines_q = select(StoryOutline).where(
                    StoryOutline.epoch_id == epoch.id
                ).order_by(StoryOutline.chapter_number)
                outlines = list((await read_session.execute(outlines_q)).scalars().all())
                epoch_outlines.append((epoch, outlines))

        total_chapters = 0
        total_words = 0
        prior_narrative: str | None = None

        for epoch, outlines in epoch_outlines:
            if not outlines:
                logger.warning("No outlines for epoch %s — run plan_all_epochs first", epoch.title)
                continue

            for outline in outlines:
                if skip_existing:
                    async with async_session_factory() as check_session:
                        ex = (await check_session.execute(
                            select(StoryChapter.id).where(
                                StoryChapter.story_outline_id == outline.id
                            ).limit(1)
                        )).scalar_one_or_none()
                        if ex:
                            sv = (await check_session.execute(
                                select(StoryChapter.narrative_text).where(
                                    StoryChapter.story_outline_id == outline.id
                                ).order_by(StoryChapter.synthesis_version.desc()).limit(1)
                            )).scalar_one_or_none()
                            if sv:
                                prior_narrative = sv
                            continue

                logger.info("Synthesizing [%d] %s / %s", total_chapters + 1, epoch.title, outline.title)
                try:
                    story = await self.synthesize_unified_chapter(None, outline, epoch, prior_narrative)
                    prior_narrative = story.narrative_text
                    total_chapters += 1
                    total_words += story.word_count or 0
                    logger.info("  → committed chapter %d: '%s' (%d words)", total_chapters, outline.title, story.word_count or 0)
                except Exception:
                    logger.exception("Failed to synthesize chapter '%s', skipping", outline.title)

        logger.info("Synthesized %d unified chapters, ~%d words total", total_chapters, total_words)
        return {"chapters_synthesized": total_chapters, "total_words": total_words}

    # -----------------------------------------------------------------------
    # Prompt building for Phase 2
    # -----------------------------------------------------------------------

    async def _build_unified_prompt(
        self,
        session: AsyncSession,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        prior_narrative: str | None,
    ) -> str:
        """Build a cross-cultural evidence prompt for a single planned chapter.

        Uses efficient SQL with theme-based filtering to avoid loading all entities.
        """
        themes = outline.themes or []
        theme_pattern = "%|%".join(t.lower() for t in themes) if themes else "%"

        epoch_id = str(epoch.id)

        # Efficient: find actors matching themes via SQL ILIKE
        actors_q = text("""
            SELECT DISTINCT a.canonical_name, a.actor_type, LEFT(a.summary, 200), a.id::text
            FROM canonical_actors a
            JOIN canon_dependencies d ON d.child_type = 'actor' AND d.child_id = a.id
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :eid AND c.is_current = true AND a.is_current = true
              AND (LOWER(a.canonical_name) LIKE ANY(string_to_array(:pattern, '|'))
                   OR LOWER(a.summary) LIKE ANY(string_to_array(:pattern, '|')))
            ORDER BY a.canonical_name
            LIMIT 50
        """)
        events_q = text("""
            SELECT DISTINCT e.canonical_name, e.event_type, LEFT(e.summary, 200), e.id::text
            FROM canonical_events e
            JOIN canon_dependencies d ON d.child_type = 'event' AND d.child_id = e.id
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :eid AND c.is_current = true AND e.is_current = true
              AND (LOWER(e.canonical_name) LIKE ANY(string_to_array(:pattern, '|'))
                   OR LOWER(e.summary) LIKE ANY(string_to_array(:pattern, '|')))
            ORDER BY e.canonical_name
            LIMIT 50
        """)
        places_q = text("""
            SELECT DISTINCT p.canonical_name, p.place_type, LEFT(p.summary, 200)
            FROM canonical_places p
            JOIN canon_dependencies d ON d.child_type = 'place' AND d.child_id = p.id
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :eid AND c.is_current = true AND p.is_current = true
              AND (LOWER(p.canonical_name) LIKE ANY(string_to_array(:pattern, '|'))
                   OR LOWER(p.summary) LIKE ANY(string_to_array(:pattern, '|')))
            ORDER BY p.canonical_name
            LIMIT 25
        """)

        params = {"eid": epoch_id, "pattern": theme_pattern}
        actor_rows = (await session.execute(actors_q, params)).all()
        event_rows = (await session.execute(events_q, params)).all()
        place_rows = (await session.execute(places_q, params)).all()

        # Get source excerpts efficiently
        entity_ids = [r[3] for r in actor_rows[:20]] + [r[3] for r in event_rows[:20]]
        source_excerpts = await self._gather_cross_cultural_sources_fast(session, entity_ids)

        culture_set = {ex["culture"] for ex in source_excerpts if ex.get("culture")}

        scope = outline.scope or "universal"
        regions = outline.regions or []
        parts = [
            f"# CHAPTER: {outline.title}",
            f"## EPOCH: {epoch.title}",
            f"## CHAPTER THEMES: {', '.join(themes)}",
            f"## CHAPTER SUMMARY: {outline.summary}",
            f"## SCOPE: {scope}" + (f" (regions: {', '.join(regions)})" if regions else ""),
            f"## CROSS-CULTURAL SCOPE: {len(culture_set)} cultures contribute to this chapter",
        ]
        if scope == "regional" and regions:
            parts.append(
                "NOTE: This is a regional chapter. Focus on the specified regions but always note "
                "parallels with other civilizations happening simultaneously."
            )

        if culture_set:
            parts.append(f"Cultures: {', '.join(sorted(culture_set)[:30])}")

        if actor_rows:
            parts.append(f"\n## ACTORS ({len(actor_rows)}):")
            for name, atype, summary, _ in actor_rows:
                parts.append(f"  - {name} ({atype}): {summary or 'No summary'}")

        if event_rows:
            parts.append(f"\n## EVENTS ({len(event_rows)}):")
            for name, etype, summary, _ in event_rows:
                parts.append(f"  - {name} ({etype}): {summary or 'No summary'}")

        if place_rows:
            parts.append(f"\n## PLACES ({len(place_rows)}):")
            for name, ptype, summary in place_rows:
                parts.append(f"  - {name} ({ptype}): {summary or 'No summary'}")

        if source_excerpts:
            parts.append(f"\n## SOURCE EVIDENCE ({len(source_excerpts)} sources, ordered by priority — OLDEST FIRST):")
            parts.append("The sources below are ordered by priority. The FIRST sources listed are the oldest and "
                         "highest-weighted — they form the BACKBONE of your narrative. Later sources ADD details to "
                         "the same story. Do NOT let a later tradition's version become the primary narrative when "
                         "an older tradition's account exists.")
            parts.append("REJECT any medieval/modern commentary (Zohar, Talmud, Church Fathers, etc.).")
            for ex in source_excerpts[:30]:
                parts.append(f"  [{ex['culture']}] {ex['title']} (priority={ex['weight']:.1f}):")
                parts.append(f"    {ex['excerpt'][:400]}")

        equivalences = await self._gather_equivalences(session)
        if equivalences:
            parts.append("\n## VERIFIED CROSS-CULTURAL ENTITY EQUIVALENCES:")
            parts.append("These entities are THE SAME being across cultures. DO NOT pick one culture's name as primary.")
            parts.append("Instead, refer to them by a DESCRIPTIVE ARCHETYPE NAME based on their role/function.")
            parts.append("List ALL cultural names parenthetically on first mention.")
            for eq in equivalences:
                all_names = [eq["primary_name"]] + eq["equivalents"][:8]
                names_str = ", ".join(all_names)
                parts.append(f"  - SAME ENTITY: {names_str}")

        if prior_narrative:
            parts.append(f"\n## PRIOR CHAPTER (continue seamlessly from here):\n...{prior_narrative[-1500:]}")

        return "\n".join(parts)

    # Age-based priority boost: older traditions get higher weight multipliers
    _CULTURE_AGE_BOOST: dict[str, float] = {
        "sumerian": 2.0, "akkadian": 1.8, "ubaid": 2.0,
        "babylonian": 1.6, "assyrian": 1.5, "mesopotami": 1.6,
        "egyptian": 1.7, "kemet": 1.7, "pyramid": 1.8,
        "vedic": 1.5, "sanskrit": 1.4, "hindu": 1.3,
        "chinese": 1.3, "hittite": 1.4, "hurrian": 1.4,
        "canaanite": 1.3, "eblaite": 1.5,
        "hebrew": 1.0, "israelite": 1.0, "greek": 1.0,
        "persian": 1.0, "zoroastrian": 1.0,
        "norse": 0.9, "maya": 1.1, "aztec": 0.9,
    }

    def _boost_weight(self, weight: float, culture: str) -> float:
        """Apply age-based boost to source weight based on culture tradition age."""
        culture_lower = culture.lower()
        for keyword, boost in self._CULTURE_AGE_BOOST.items():
            if keyword in culture_lower:
                return weight * boost
        return weight

    async def _gather_cross_cultural_sources_fast(
        self,
        session: AsyncSession,
        entity_id_strings: list[str],
    ) -> list[dict]:
        """Gather source excerpts with per-culture limits and age-based weighting.

        Ensures no single culture floods the evidence by capping at 5 sources
        per culture, and boosts older traditions' weights so they appear first.
        """
        if not entity_id_strings:
            return []

        ids_list = ",".join(f"'{eid}'" for eid in entity_id_strings[:40])
        q = text(f"""
            SELECT DISTINCT ON (sr.id)
                sr.canonical_title, sr.culture, LEFT(sv.text_extracted, 500), cl.weight
            FROM canon_support_links cl
            JOIN source_records sr ON sr.id = cl.archive_object_id
            LEFT JOIN source_versions sv ON sv.source_record_id = sr.id
            WHERE cl.canonical_id IN ({ids_list})
              AND sr.culture IS NOT NULL AND sr.culture != ''
            ORDER BY sr.id, cl.weight DESC
            LIMIT 120
        """)
        try:
            rows = (await session.execute(q)).all()
            all_sources = [
                {
                    "title": r[0] or "Unknown",
                    "culture": r[1] or "Unknown",
                    "excerpt": r[2] or "",
                    "weight": float(r[3] or 0),
                }
                for r in rows
            ]

            # Apply age-based weight boosting
            for src in all_sources:
                src["weight"] = self._boost_weight(src["weight"], src["culture"])

            # Per-culture cap: max 5 sources per culture to ensure diversity
            culture_counts: dict[str, int] = {}
            max_per_culture = 5
            balanced: list[dict] = []
            # Sort by boosted weight first so we keep the best from each culture
            all_sources.sort(key=lambda x: x["weight"], reverse=True)
            for src in all_sources:
                c = src["culture"]
                culture_counts[c] = culture_counts.get(c, 0) + 1
                if culture_counts[c] <= max_per_culture:
                    balanced.append(src)

            # Return top 40 after balancing, sorted by weight
            return sorted(balanced[:40], key=lambda x: x["weight"], reverse=True)
        except Exception:
            logger.warning("Failed to gather source excerpts", exc_info=True)
            return []

    # -----------------------------------------------------------------------
    # Shared helpers
    # -----------------------------------------------------------------------

    async def _gather_equivalences(self, session: AsyncSession) -> list[dict]:
        """Fetch entity equivalences with human-readable names for the prompt."""
        try:
            result = await session.execute(text("""
                SELECT
                    ee.primary_entity_type,
                    COALESCE(
                        (SELECT canonical_name FROM canonical_actors WHERE id = ee.primary_entity_id),
                        (SELECT canonical_name FROM canonical_events WHERE id = ee.primary_entity_id),
                        (SELECT canonical_name FROM canonical_places WHERE id = ee.primary_entity_id),
                        'Unknown'
                    ) as primary_name,
                    COALESCE(
                        (SELECT canonical_name FROM canonical_actors WHERE id = ee.equivalent_entity_id),
                        (SELECT canonical_name FROM canonical_events WHERE id = ee.equivalent_entity_id),
                        (SELECT canonical_name FROM canonical_places WHERE id = ee.equivalent_entity_id),
                        'Unknown'
                    ) as equivalent_name,
                    ee.confidence,
                    ee.merge_basis
                FROM entity_equivalences ee
                ORDER BY ee.confidence DESC
                LIMIT 80
            """))
            rows = result.all()
            # Group by primary name to show all aliases together
            groups: dict[str, list[str]] = {}
            for row in rows:
                pname = row[1]
                ename = row[2]
                if pname not in groups:
                    groups[pname] = []
                groups[pname].append(ename)
            return [
                {"primary_name": pname, "equivalents": equivs, "type": "cross-cultural"}
                for pname, equivs in groups.items()
            ]
        except Exception:
            logger.warning("Failed to gather equivalences", exc_info=True)
            return []

    async def _call_deepseek(self, prompt: str, *, system: str = NARRATIVE_SYSTEM_PROMPT) -> dict:
        if not settings.deepseek_api_key:
            raise RuntimeError(
                "WORLD_DEEPSEEK_API_KEY is not set. Narrative synthesis requires DeepSeek."
            )

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system},
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
                if resp.status_code != 200:
                    logger.error("DeepSeek HTTP %d: %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
                data = resp.json()

            raw = data["choices"][0]["message"]["content"]
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON in DeepSeek response, trying to salvage")
            return {"narrative_text": raw[:5000], "key_claims": [], "image_prompts": [], "chapters": []}
        except RuntimeError:
            raise
        except Exception:
            logger.exception("DeepSeek call failed")
            return {"narrative_text": "", "key_claims": [], "image_prompts": [], "chapters": []}
