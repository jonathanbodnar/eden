"""Narrative Synthesizer — three-pass pipeline for unified ancient history.

Pipeline:
  Pass 1 — Culture Narratives: For each culture with source data, generate a rich
           1500-2500 word faithful retelling from that culture's own sources.
  Pass 2 — Event Extraction: Extract structured event skeletons from each culture
           narrative (actors, actions, locations, outcomes, unique details).
  Pass 3 — Unified Merge: Merge all event skeletons + entity equivalences into
           one unified narrative governed by the Laws of Synthesis.

Each pass commits to DB immediately so progress is visible.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict

import httpx
from sqlalchemy import select, func, text, distinct, delete
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
from src.canon.models.culture_narrative import CultureNarrative, CultureEventSkeleton
from src.canon.models.enums import CanonicalType
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.story_outline import StoryOutline
from src.canon.models.system_a import SASourceRecord, SASourceVersion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Culture normalization — maps raw DB culture strings to canonical groups
# ---------------------------------------------------------------------------

CULTURE_NORMALIZE: list[tuple[list[str], str, str]] = [
    # (keywords_to_match, canonical_key, display_label)
    (["sumerian"], "sumerian", "Sumerian"),
    (["akkadian", "babylonian", "assyrian", "mesopotami", "neo-babylonian", "neo-assyrian"],
     "mesopotamian", "Mesopotamian / Babylonian"),
    (["egyptian", "kemet", "pharaoh", "pyramid", "memphis", "thebes", "dynasty"],
     "egyptian", "Ancient Egyptian"),
    (["hebrew", "israel", "judah", "jewish"], "hebrew", "Hebrew / Israelite"),
    (["vedic", "hindu", "sanskrit", "indic", "ancient india", "brahman"],
     "vedic", "Vedic / Hindu"),
    (["greek", "attic", "hellenic", "orphic", "archaic"], "greek", "Ancient Greek"),
    (["norse", "germanic", "edda", "viking"], "norse", "Norse / Germanic"),
    (["chinese", "taoist", "confuc", "zhou", "han period", "shang"],
     "chinese", "Ancient Chinese"),
    (["zoroast", "persian", "avesta", "achaemenid", "iran"],
     "zoroastrian", "Zoroastrian / Persian"),
    (["maya", "aztec", "mesoameric", "popol vuh", "olmec", "andean", "inca"],
     "mesoamerican", "Mesoamerican"),
    (["aboriginal", "dreamtime", "wandjina"], "aboriginal", "Australian Aboriginal"),
    (["polynesi", "maori", "hawaiki", "rapa nui", "oceani"],
     "polynesian", "Polynesian / Oceanic"),
    (["ainu", "kamuy", "japanese", "shinto"], "ainu", "Ainu / Japanese"),
    (["hittite", "hurrian", "anatolian"], "hittite", "Hittite / Hurrian"),
    (["canaanite", "ugarit", "phoenici", "baal"], "canaanite", "Canaanite / Ugaritic"),
    (["roman", "latin", "italic", "etruscan"], "roman", "Roman / Italic"),
    (["minoan", "mycenae", "aegean"], "minoan", "Minoan / Aegean"),
    (["celtic", "gaul", "druid"], "celtic", "Celtic"),
    (["african", "nok", "nubian", "meroitic", "yoruba", "dogon"],
     "african", "African"),
]

# Age-based priority: older traditions get higher weight multipliers in Pass 3
CULTURE_AGE_ORDER: dict[str, int] = {
    "sumerian": 1, "mesopotamian": 2, "egyptian": 3,
    "hittite": 4, "canaanite": 5, "vedic": 6,
    "chinese": 7, "greek": 8, "hebrew": 9,
    "zoroastrian": 10, "minoan": 11, "roman": 12,
    "mesoamerican": 13, "norse": 14, "celtic": 15,
    "polynesian": 16, "aboriginal": 17, "ainu": 18,
    "african": 19,
}


def normalize_culture(raw_culture: str) -> tuple[str, str] | None:
    """Map a raw culture string to (canonical_key, display_label) or None if unmappable."""
    if not raw_culture:
        return None
    lower = raw_culture.lower().strip()
    if lower in ("ancient", "unknown", "other", "unspecified", "general", ""):
        return None
    for keywords, key, label in CULTURE_NORMALIZE:
        for kw in keywords:
            if kw in lower:
                return (key, label)
    return None


def normalize_culture_from_title(title: str) -> tuple[str, str] | None:
    """Extract culture from a CanonicalChapter title like 'Creation: Sumerian Tradition'."""
    m = re.search(r':\s*(.+?)(?:\s+Tradition)?$', title)
    if not m:
        return None
    culture_str = m.group(1).strip()
    if culture_str.lower() in ("overview", "general"):
        return None
    return normalize_culture(culture_str)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

LAWS_OF_SYNTHESIS = """
## THE 16 LAWS OF SYNTHESIS (you MUST follow all of these)

1. MYTH AS RECORDED MEMORY: Treat all ancient narratives as records of perceived events or inherited memory, not fiction. No dismissal, no blind literalization.
2. SOURCE-ONLY INPUT: Use only information from primary sources, artifacts, or recorded traditions. No external theory, no modern explanation.
3. NO INTERPRETATION INJECTION: Do not introduce meaning, purpose, motive, symbolism, or explanation unless explicitly present in a source.
4. AGE-WEIGHTED PRIORITY: Earlier recorded versions get higher weight. Older = higher priority. Later versions support but cannot override older ones without stronger pattern support.
5. CROSS-CULTURAL CONVERGENCE: Independent recurrence of a pattern across geographically separated or culturally independent traditions increases its structural weight.
6. DISTRIBUTION INDEPENDENCE: Frequency or popularity of a narrative does not increase its truth weight. Modern prominence is irrelevant.
7. PATTERN DOMINANCE: Recurring structural patterns across sources outweigh isolated claims. One-off claims = weak. Repeated structure = strong.
8. ENTITY CONVERGENCE: Entities across cultures may be merged into one canonical identity only when role similarity, action similarity, context alignment, AND pattern repetition ALL align. If not all satisfied, keep as parallel entities.
9. MINIMAL ASSUMPTION: When multiple interpretations are possible, select the one requiring the fewest unsupported assumptions. No leaps, no filling gaps with creativity.
10. NARRATIVE CONTINUITY: Construct a single continuous timeline integrating all compatible sources. No "this culture says / that culture says" framing — unified narrative only.
11. CONTRADICTION HANDLING: When sources conflict, prioritize older source, then stronger pattern. If unresolvable, maintain parallel accounts within the same timeline.
12. STRUCTURAL CONSISTENCY: Once an entity or event is established, it must remain consistent across all outputs unless revised by stronger evidence.
13. IMAGE CONSTRAINT: Visual/artistic sources inform material context but cannot define narrative meaning.
14. TRACEABILITY: Every narrative element must be traceable to at least one source or pattern cluster. No freeform generation, no ungrounded details.
15. SYNTHESIS CONSTRAINT: Combine sources into unified narrative only where compatibility exists; otherwise layer or parallelize them.
16. ANCIENT TIME ANCHORING: When ancient sources assign events to a time or sequence, those internal timelines are prioritized over modern chronological reconstructions.
"""


PLANNER_SYSTEM_PROMPT = f"""You are the architect of a unified ancient world history — an alternative bible woven from every surviving tradition on Earth.

You are designing the TABLE OF CONTENTS for one epoch of this history. You will receive a summary of ALL entities, themes, and source traditions from this epoch across every culture on the planet.

Your job is to organize this into 5-15 thematic chapters that tell a unified narrative.

{LAWS_OF_SYNTHESIS}

## STRUCTURE RULES:

### For EARLY EPOCHS (Creation, Age of Gods, Flood, Dawn of Civilization):
These epochs describe universal events that virtually all cultures share memories of. The chapters must be FULLY UNIFIED — weaving all cultures together around shared themes:
- Creation from void/chaos -> multiple cultures merged into one telling
- Gods/sky beings descend -> Sumerian, Hebrew, Hindu, etc. merged
- Creation of mankind -> clay/earth/breath traditions woven together
- The flood -> one chapter weaving ALL flood accounts

### For LATER EPOCHS (Rise of Cities, Age of Empires, Heroes, Iron Age, Classical):
As history progresses, cultures genuinely diverge. For these epochs:
1. START with chapters that cover SHARED patterns across the epoch
2. THEN follow with REGIONAL NARRATIVE ARCS that track the diverging stories
3. End the epoch with a chapter that reconnects the threads

### For ALL EPOCHS:
1. NEVER make a chapter about just one culture with no connection to others
2. Group by THEME first, REGION second
3. Order chapters in narrative/chronological sequence within the epoch
4. Each chapter should have a compelling, epic title (like a book of the bible)
5. Include a brief summary (2-3 sentences) of what the chapter covers
6. List the key themes/motifs that belong in each chapter

OUTPUT FORMAT — return ONLY valid JSON:
{{
  "chapters": [
    {{
      "chapter_number": 1,
      "title": "Epic chapter title",
      "summary": "2-3 sentence summary naming specific traditions that will be woven together",
      "themes": ["theme1", "theme2", "theme3"],
      "time_hint": "Before time / primordial / ~3000 BCE",
      "scope": "universal" or "regional",
      "regions": ["Mesopotamia", "Egypt"]
    }}
  ]
}}"""


CULTURE_NARRATOR_PROMPT = f"""You are a scholar writing the definitive account of one culture's ancient tradition.

You will receive source texts from a SINGLE cultural tradition. Your job is to write a rich, faithful narrative retelling of this culture's account — extracting EVERY actor, event, location, and unique detail from the sources.

{LAWS_OF_SYNTHESIS}

## RULES:
1. Write 1500-2500 words of flowing narrative prose — a complete retelling of this culture's account
2. Be EXHAUSTIVELY FAITHFUL to the source texts. Every name, every action, every detail matters. (Laws 2, 14)
3. Include ALL actors mentioned in the sources — even minor ones
4. Include ALL locations, objects, and specific details (numbers, materials, sequences)
5. Do NOT add information not in the sources. Do NOT interpret or analyze. (Laws 2, 3, 9)
6. Use the culture's own names for everything (e.g., "Enki" not "The Creator")
7. Write in present tense for vividness
8. Maintain the narrative sequence as presented in the sources
9. If sources contain direct speech or dialogue, preserve it
10. Note any unique details that are specific to THIS culture's account (details you would not expect to find in other traditions)

## OUTPUT FORMAT — return ONLY valid JSON:
{{
  "narrative_text": "The full 1500-2500 word narrative...",
  "actors": [
    {{"name": "Enki", "role": "god of wisdom and fresh water", "key_actions": ["creates humans from clay", "defies Enlil"]}}
  ],
  "events": [
    {{"event": "Creation of humans", "sequence": 1, "description": "Brief description"}}
  ],
  "places": [
    {{"name": "The Abzu", "description": "Underground freshwater ocean, domain of Enki"}}
  ],
  "unique_details": [
    "Seven male and seven female humans are created simultaneously",
    "The womb-goddesses assist in shaping the clay"
  ]
}}"""


EVENT_EXTRACTOR_PROMPT = f"""You are extracting a structured event timeline from a cultural narrative.

Read the narrative and extract every discrete event in chronological order. For each event, identify all components. Be thorough — capture every event, even brief ones.

Follow Law 1 (Myth as Recorded Memory): treat all events as records of perceived events.
Follow Law 14 (Traceability): every extracted event must trace to specific content in the narrative.
Follow Law 3 (No Interpretation): extract only what is stated, do not add meaning or motive.

Also identify details UNIQUE to this culture's account — things you would not expect other traditions to describe.

Return ONLY valid JSON:
{{
  "events": [
    {{
      "seq": 1,
      "event": "Brief event label",
      "actors": ["Name1", "Name2"],
      "action": "What specifically happens — the concrete action",
      "location": "Where this takes place (or null)",
      "objects": ["Key objects or materials involved"],
      "outcome": "The result or consequence of this event",
      "source_detail": "The most vivid/specific sentence or detail from the source about this event"
    }}
  ],
  "unique_details": [
    "A detail specific to this tradition that other cultures would not have"
  ]
}}"""


UNIFIED_MERGE_PROMPT = f"""You are writing one chapter of an alternative bible — a unified ancient history told as continuous story across multiple chapters.

{LAWS_OF_SYNTHESIS}

## APPLYING THE LAWS TO THIS NARRATIVE

Law 4 (Age-Weighted Priority): The OLDEST traditions (Sumerian/Babylonian cuneiform tablets) form the BACKBONE of the story. Other traditions ENRICH this backbone. If cuneiform says "man was made to till the ground and serve the gods," that is the primary narrative. Other traditions add color but do not replace the oldest account.

Law 10 (Narrative Continuity): Write ONE unified timeline. Never "this culture says / that culture says."

Law 8 (Entity Convergence): Merge entities from different cultures into ONE archetype ONLY when their role, actions, and context all align. Use an archetype name like "The Divine Craftsman" — never raw culture names.

Law 14 (Traceability): Every sentence must trace to source material. No invented details or atmosphere.

Law 3 (No Interpretation): State what happens according to sources. Do not add motive, symbolism, or meaning unless the source text explicitly states it.

Law 9 (Minimal Assumption): When interpretations are possible, choose the simplest supported by sources.

## ARCHETYPE NAMES — MANDATORY

EVERY character and place MUST use an archetype name in the narrative text. NEVER use culture-specific names.

WRONG: "Enki kneels", "Ra emerges", "Tiamat fashions", "in Nippur", "at Erech"
RIGHT: "The Divine Craftsman kneels", "The Sun God emerges", "The Mother of Chaos fashions", "in The Holy City", "at The First City"
WRONG in speech: "I am Khepera at dawn, Ra at noon" — NO culture names even in quotes
RIGHT: "He declares three forms: the beetle at dawn, the blazing disk at noon, the aged one at dusk"

Put ALL culture-specific names ONLY in entity_mentions.also_known_as.
If ESTABLISHED CAST is provided, reuse those EXACT archetype names.

## ENTITY ANNOTATION — REQUIRED

You MUST annotate characters on first mention: [[actor:ArchetypeName]] or [[place:ArchetypeName]]
After first mention: just the name, no brackets.
Aim for 10-15 annotations. Without these, the story cannot be interactive.

WRONG: [[actor:Tiamat]] or [[place:Erech]]
RIGHT: [[actor:The Mother of Chaos]] or [[place:The First City]]

## STORY RULES

- Each chapter has a SPECIFIC TOPIC. Write ONLY about that topic. Do NOT retell prior chapters.
- Write like scripture: things HAPPEN. Cause leads to effect. Include WHY from sources.
- Do NOT list catalogs of creatures/names. Weave into flowing narrative.
- CRITICAL: When multiple traditions describe the SAME event (e.g. creation of humanity), merge them into ONE telling that weaves the details together. Do NOT tell the event multiple times from different perspectives. ONE creation of man, ONE flood, ONE garden — not five separate versions.
  WRONG: "In one act, the Craftsman molds clay. In another act, a creator gathers dust. Elsewhere, a trickster steals fire."
  RIGHT: "The Craftsman kneels at the riverbed. He scoops clay and mixes it with the blood of a slain god. Into the nostrils of the clay figure, he breathes the breath of life and hides within it a spark of celestial fire."
- Present tense, direct, authoritative. No modern commentary.
- Target: 1500-2500 words.

## BANNED WORDS (instant failure)

Culture labels: Sumerian, Hebrew, Egyptian, Greek, Norse, Chinese, Vedic, Hindu, Babylonian, Persian, Japanese, Ainu, African, Polynesian, Maya, Aztec, Hopi, Roman, Zoroastrian, Mesoamerican, Canaanite, Celtic
Deity names in text: Enki, Marduk, Ra, Khepera, Tum, Tiamat, Apsu, Nu, Shu, Tefnut, Geb, Nut, Isis, Brahma, Vishnu, Odin, Thor, Enlil
Framing: "According to", "One tradition", "In another", "Similarly", "It is believed", "Some say"

## OUTPUT — valid JSON only:
{{
  "narrative_text": "Story using ONLY archetype names with [[actor:Name]] annotations...",
  "entity_mentions": [
    {{"name": "The Divine Craftsman", "type": "actor", "also_known_as": ["Enki", "Ea", "Khnum", "Ptah"], "role_in_chapter": "shapes humanity from clay to serve the gods"}}
  ]
}}"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class NarrativeSynthesizer:

    # -----------------------------------------------------------------------
    # Phase 0: Plan the book — design thematic chapters per epoch
    # -----------------------------------------------------------------------

    async def plan_epoch_outline(
        self, _session: AsyncSession | None, epoch: CanonicalEpoch
    ) -> list[StoryOutline]:
        """Use DeepSeek to design unified thematic chapters for one epoch."""
        from src.canon.database import async_session_factory

        logger.info("Planning outline for epoch: %s", epoch.title)

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

        result = await self._call_deepseek(prompt, system=PLANNER_SYSTEM_PROMPT)
        chapters_data = result.get("chapters", [])

        if not chapters_data:
            logger.warning("No chapters planned for epoch %s", epoch_title)
            return []

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

    # -----------------------------------------------------------------------
    # Pass 1: Generate per-culture narratives
    # -----------------------------------------------------------------------

    async def generate_culture_narratives(
        self,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        *,
        skip_existing: bool = False,
    ) -> list[CultureNarrative]:
        """Pass 1: Generate a rich narrative for each culture that has sources for this chapter."""
        from src.canon.database import async_session_factory

        logger.info("Pass 1 — generating culture narratives for: %s", outline.title)
        outline_id = outline.id
        themes = outline.themes or []

        async with async_session_factory() as session:
            culture_sources = await self._gather_sources_by_culture(
                session, epoch.id, themes
            )

        if not culture_sources:
            logger.warning("No culture sources found for: %s", outline.title)
            return []

        results: list[CultureNarrative] = []

        for culture_key, culture_label, sources in culture_sources:
            if skip_existing:
                async with async_session_factory() as check_session:
                    existing = (await check_session.execute(
                        select(CultureNarrative.id).where(
                            CultureNarrative.story_outline_id == outline_id,
                            CultureNarrative.culture_key == culture_key,
                        ).limit(1)
                    )).scalar_one_or_none()
                    if existing:
                        logger.info("  Skipping existing: %s", culture_label)
                        continue

            logger.info("  Generating narrative for: %s (%d sources)", culture_label, len(sources))

            prompt = self._build_culture_prompt(outline, epoch, culture_label, sources)
            result = await self._call_deepseek(prompt, system=CULTURE_NARRATOR_PROMPT)

            narrative = result.get("narrative_text", "")
            if not narrative:
                logger.warning("  Empty narrative for %s, skipping", culture_label)
                continue

            source_id_list = [s["source_id"] for s in sources if s.get("source_id")]

            async with async_session_factory() as write_session:
                await write_session.execute(
                    text("""
                        INSERT INTO culture_narratives
                            (story_outline_id, culture_key, culture_label, narrative_text,
                             actors_json, events_json, places_json, source_ids,
                             source_count, word_count, generation_version)
                        VALUES (:oid, :ck, :cl, :nt, :aj, :ej, :pj, :si, :sc, :wc, 1)
                        ON CONFLICT (story_outline_id, culture_key) DO UPDATE SET
                            narrative_text = EXCLUDED.narrative_text,
                            actors_json = EXCLUDED.actors_json,
                            events_json = EXCLUDED.events_json,
                            places_json = EXCLUDED.places_json,
                            source_ids = EXCLUDED.source_ids,
                            source_count = EXCLUDED.source_count,
                            word_count = EXCLUDED.word_count,
                            generation_version = culture_narratives.generation_version + 1,
                            updated_at = now()
                    """),
                    {
                        "oid": str(outline_id),
                        "ck": culture_key,
                        "cl": culture_label,
                        "nt": narrative,
                        "aj": json.dumps(result.get("actors", [])),
                        "ej": json.dumps(result.get("events", [])),
                        "pj": json.dumps(result.get("places", [])),
                        "si": json.dumps(source_id_list),
                        "sc": len(sources),
                        "wc": len(narrative.split()),
                    },
                )
                await write_session.commit()

            logger.info("  → %s: %d words from %d sources", culture_label, len(narrative.split()), len(sources))

        async with async_session_factory() as read_session:
            rows = (await read_session.execute(
                select(CultureNarrative).where(
                    CultureNarrative.story_outline_id == outline_id
                )
            )).scalars().all()
            results = list(rows)

        logger.info("Pass 1 complete: %d culture narratives for %s", len(results), outline.title)
        return results

    def _build_culture_prompt(
        self,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        culture_label: str,
        sources: list[dict],
    ) -> str:
        parts = [
            f"# CULTURE: {culture_label}",
            f"# CHAPTER TOPIC: {outline.title}",
            f"# CHAPTER THEMES: {', '.join(outline.themes or [])}",
            f"# CHAPTER SUMMARY: {outline.summary}",
            f"# EPOCH: {epoch.title}",
            f"\nYou have {len(sources)} source texts from the {culture_label} tradition.",
            "Write a complete, faithful narrative retelling of this culture's account.",
            "Extract EVERY actor, event, location, and unique detail.\n",
        ]

        for i, src in enumerate(sources[:20], 1):
            parts.append(f"## SOURCE {i}: {src['title']}")
            if src.get("excerpt"):
                parts.append(src["excerpt"][:3000])
            parts.append("")

        return "\n".join(parts)

    async def _gather_sources_by_culture(
        self,
        session: AsyncSession,
        epoch_id: uuid.UUID,
        themes: list[str],
    ) -> list[tuple[str, str, list[dict]]]:
        """Gather all source texts for an epoch, grouped by normalized culture.

        Returns: [(culture_key, culture_label, [source_dicts])]
        Sorted by CULTURE_AGE_ORDER (oldest first).
        """
        # Grab ALL sources linked to ANY entity in this epoch — no theme filtering
        # because for early epochs like creation, all entities are relevant to all chapters
        q = text("""
            WITH epoch_entity_ids AS (
                SELECT DISTINCT d.child_id as entity_id
                FROM canon_dependencies d
                JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
                WHERE c.epoch_id = :eid AND c.is_current = true
                  AND d.child_type IN ('actor', 'event', 'place')
                LIMIT 500
            )
            SELECT DISTINCT ON (sr.id)
                sr.id::text as source_id,
                sr.canonical_title,
                sr.culture,
                LEFT(sv.text_extracted, 5000) as text_content,
                cl.weight
            FROM epoch_entity_ids eei
            JOIN canon_support_links cl ON cl.canonical_id = eei.entity_id
            JOIN source_records sr ON sr.id = cl.archive_object_id
            JOIN source_versions sv ON sv.source_record_id = sr.id
            WHERE sv.text_extracted IS NOT NULL
              AND LENGTH(sv.text_extracted) > 100
            ORDER BY sr.id, cl.weight DESC
            LIMIT 800
        """)

        rows = (await session.execute(q, {"eid": str(epoch_id)})).all()

        # Also get sources identified via CanonicalChapter titles
        chapter_q = text("""
            SELECT DISTINCT c.title
            FROM canonical_chapters c
            WHERE c.epoch_id = :eid AND c.is_current = true
        """)
        chapter_titles = [r[0] for r in (await session.execute(chapter_q, {"eid": str(epoch_id)})).all()]

        # Group by normalized culture
        culture_groups: dict[str, dict] = {}

        for row in rows:
            source_id, title, raw_culture, text_content, weight = row
            norm = normalize_culture(raw_culture or "")
            if not norm:
                # Try to infer from title
                norm = normalize_culture(title or "")
            if not norm:
                continue

            culture_key, culture_label = norm
            if culture_key not in culture_groups:
                culture_groups[culture_key] = {
                    "label": culture_label,
                    "sources": [],
                    "seen_ids": set(),
                }
            grp = culture_groups[culture_key]
            if source_id not in grp["seen_ids"]:
                grp["seen_ids"].add(source_id)
                grp["sources"].append({
                    "source_id": source_id,
                    "title": title or "Unknown",
                    "excerpt": text_content or "",
                    "weight": float(weight or 0),
                })

        # Also try matching chapter titles to cultures that had no direct source hits
        for title in chapter_titles:
            norm = normalize_culture_from_title(title)
            if norm and norm[0] not in culture_groups:
                culture_groups[norm[0]] = {
                    "label": norm[1],
                    "sources": [],
                    "seen_ids": set(),
                }

        # Filter sources by content relevance to mythological/narrative themes
        # This removes archaeological, linguistic, and purely historical sources
        # that have no creation/mythological content
        result = []
        for culture_key, grp in culture_groups.items():
            scored_sources = []
            for src in grp["sources"]:
                relevance = self._score_source_relevance(src.get("title", ""), src.get("excerpt", ""))
                if relevance > 0:
                    scored_sources.append({**src, "_relevance": relevance})

            # Sort by relevance * weight, keep top 15
            scored_sources.sort(key=lambda s: s["_relevance"] * s["weight"], reverse=True)
            sources = scored_sources[:15]
            if not sources:
                continue
            result.append((culture_key, grp["label"], sources))

        # Sort cultures by age order (oldest first)
        result.sort(key=lambda x: CULTURE_AGE_ORDER.get(x[0], 99))

        logger.info("Gathered sources for %d cultures", len(result))
        for ck, cl, srcs in result:
            logger.info("  %s: %d sources", cl, len(srcs))

        return result

    @staticmethod
    def _score_source_relevance(title: str, excerpt: str) -> float:
        """Score how relevant a source is to mythological/narrative content.

        Returns 0 for purely archaeological/linguistic/historical sources,
        higher scores for sources with creation/mythological content.
        """
        combined = (title + " " + excerpt[:2000]).lower()

        # Strong mythological signals — these are what we want
        myth_keywords = [
            "creation", "creator", "created", "beginning", "origin",
            "god ", "gods", "goddess", "deity", "divine", "heaven",
            "earth", "waters", "void", "chaos", "primordial", "cosmos",
            "flood", "deluge", "garden", "paradise", "serpent", "tree",
            "mankind", "humanity", "human", "mortal", "clay", "breath",
            "spirit", "soul", "sacred", "holy", "temple", "ritual",
            "myth", "legend", "epic", "hymn", "prayer", "psalm",
            "genesis", "cosmogon", "theogon",
            "first man", "first woman", "ancestor",
            "sky father", "earth mother", "sun god", "moon god",
            "underworld", "afterlife", "death", "rebirth",
            "sacrifice", "offering", "worship",
            "prophet", "revelation", "scripture", "testament",
            "thou", "thee", "hath", "saith", "begat", "begot",
            "enuma elish", "gilgamesh", "rig veda", "popol vuh",
            "edda", "theogony", "avesta", "torah", "bible",
            "book of the dead", "pyramid text", "coffin text",
        ]

        # Negative signals — archaeological, linguistic, historical analysis
        anti_keywords = [
            "script", "inscription", "deciphered", "alphabet", "glyph",
            "excavation", "archaeological", "pottery", "ceramic",
            "stratigraphy", "radiocarbon", "dating", "carbon-14",
            "museum", "collection", "artifact number", "catalogue",
            "linguistics", "phonology", "syntax", "grammar",
            "trade route", "commerce", "economy", "currency",
            "isbn", "doi:", "journal", "university press",
            "bibliography", "footnote", "endnote",
            # Philosophical treatises (not narrative mythology)
            "tao te ching", "chuang tz", "lao tz", "wu wei",
            "non-action", "non-being", "ten thousand things",
            "the sage", "the wise man", "the master said",
            "confucius", "analects", "mencius",
        ]

        score = 0.0
        for kw in myth_keywords:
            if kw in combined:
                score += 1.0
        for kw in anti_keywords:
            if kw in combined:
                score -= 2.0

        return max(score, 0.0)

    # -----------------------------------------------------------------------
    # Pass 2: Extract event skeletons from culture narratives
    # -----------------------------------------------------------------------

    async def extract_event_skeletons(
        self,
        outline: StoryOutline,
        *,
        skip_existing: bool = False,
    ) -> list[CultureEventSkeleton]:
        """Pass 2: Extract structured events from each culture narrative."""
        from src.canon.database import async_session_factory

        logger.info("Pass 2 — extracting event skeletons for: %s", outline.title)
        outline_id = outline.id

        async with async_session_factory() as session:
            narratives = list((await session.execute(
                select(CultureNarrative).where(
                    CultureNarrative.story_outline_id == outline_id
                )
            )).scalars().all())

        if not narratives:
            logger.warning("No culture narratives found for: %s", outline.title)
            return []

        # Detach needed data before closing session
        narr_data = [
            (n.id, n.culture_key, n.culture_label, n.narrative_text)
            for n in narratives
        ]

        for narr_id, culture_key, culture_label, narrative_text in narr_data:
            if skip_existing:
                async with async_session_factory() as check_session:
                    existing = (await check_session.execute(
                        select(CultureEventSkeleton.id).where(
                            CultureEventSkeleton.culture_narrative_id == narr_id,
                        ).limit(1)
                    )).scalar_one_or_none()
                    if existing:
                        logger.info("  Skipping existing skeleton: %s", culture_label)
                        continue

            logger.info("  Extracting events from: %s", culture_label)

            prompt = f"""# CULTURE: {culture_label}
# CHAPTER: {outline.title}

Here is the complete {culture_label} narrative for this chapter:

{narrative_text}

Extract ALL events in chronological order, with actors, actions, locations, objects, outcomes, and source details. Also identify details unique to this culture's account."""

            result = await self._call_deepseek(prompt, system=EVENT_EXTRACTOR_PROMPT)
            events = result.get("events", [])
            unique_details = result.get("unique_details", [])

            async with async_session_factory() as write_session:
                # Delete existing skeleton for this narrative
                await write_session.execute(
                    text("DELETE FROM culture_event_skeletons WHERE culture_narrative_id = :nid"),
                    {"nid": str(narr_id)},
                )
                skel = CultureEventSkeleton(
                    id=uuid.uuid4(),
                    culture_narrative_id=narr_id,
                    story_outline_id=outline_id,
                    culture_key=culture_key,
                    events_json=events,
                    unique_details=unique_details,
                )
                write_session.add(skel)
                await write_session.commit()

            logger.info("  → %s: %d events, %d unique details",
                        culture_label, len(events), len(unique_details))

        async with async_session_factory() as read_session:
            results = list((await read_session.execute(
                select(CultureEventSkeleton).where(
                    CultureEventSkeleton.story_outline_id == outline_id
                )
            )).scalars().all())

        logger.info("Pass 2 complete: %d event skeletons for %s", len(results), outline.title)
        return results

    # -----------------------------------------------------------------------
    # Pass 3: Unified merge narrative
    # -----------------------------------------------------------------------

    async def synthesize_unified_chapter(
        self,
        _session: AsyncSession | None,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        prior_narrative: str | None = None,
        prior_summaries: list[str] | None = None,
        established_cast: dict[str, list[str]] | None = None,
    ) -> StoryChapter:
        """Pass 3: Merge all event skeletons into one unified narrative."""
        from src.canon.database import async_session_factory

        logger.info("Pass 3 — merging unified narrative for: %s", outline.title)
        outline_id = outline.id
        epoch_id = epoch.id

        async with async_session_factory() as read_session:
            prompt = await self._build_merge_prompt(
                read_session, outline, epoch, prior_narrative,
                prior_summaries, established_cast,
            )

        result = await self._call_deepseek(prompt, system=UNIFIED_MERGE_PROMPT)

        narrative = result.get("narrative_text", "")
        entity_mentions = result.get("entity_mentions", [])
        logger.info("  DeepSeek returned %d entity_mentions in JSON, narrative=%d chars",
                     len(entity_mentions), len(narrative))

        annotation_mentions = self._extract_annotations(narrative)
        logger.info("  Extracted %d annotations from [[type:Name]] in narrative text", len(annotation_mentions))

        all_mentions = entity_mentions + annotation_mentions
        # Deduplicate by name+type
        seen_keys = set()
        deduped: list[dict] = []
        for m in all_mentions:
            key = (m.get("name", "").lower(), m.get("type", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(m)
        all_mentions = deduped
        logger.info("  Total unique mentions to resolve: %d", len(all_mentions))

        async with async_session_factory() as write_session:
            resolved_mentions = await self._resolve_entity_mentions(write_session, all_mentions)
            linked = sum(1 for m in resolved_mentions if m.get("canonical_id"))
            logger.info("  Resolved: %d/%d linked to canonical IDs", linked, len(resolved_mentions))

            existing_q = select(StoryChapter).where(
                StoryChapter.story_outline_id == outline_id
            ).order_by(StoryChapter.synthesis_version.desc()).limit(1)
            existing = (await write_session.execute(existing_q)).scalar_one_or_none()

            if existing:
                existing.narrative_text = narrative
                existing.claims_json = result.get("key_claims", [])
                existing.image_prompts_json = result.get("image_prompts", [])
                existing.entity_mentions_json = resolved_mentions
                existing.word_count = len(narrative.split())
                existing.synthesis_version += 1
                await write_session.execute(
                    text("DELETE FROM story_chapter_audio WHERE story_chapter_id = :cid"),
                    {"cid": str(existing.id)},
                )
                await write_session.commit()
                logger.info("  → Updated existing chapter: %d words (v%d)",
                            existing.word_count, existing.synthesis_version)
                return existing

            story = StoryChapter(
                id=uuid.uuid4(),
                story_outline_id=outline_id,
                chapter_id=None,
                epoch_id=epoch_id,
                narrative_text=narrative,
                claims_json=result.get("key_claims", []),
                image_prompts_json=result.get("image_prompts", []),
                entity_mentions_json=resolved_mentions,
                synthesis_version=1,
                word_count=len(narrative.split()),
            )
            write_session.add(story)
            await write_session.commit()
            logger.info("  → Created new chapter: %d words", story.word_count)
            return story

    async def _build_merge_prompt(
        self,
        session: AsyncSession,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        prior_narrative: str | None,
        prior_summaries: list[str] | None = None,
        established_cast: dict[str, list[str]] | None = None,
    ) -> str:
        """Build merge prompt with events PRE-SORTED into thematic sections.

        The key insight: if you show data grouped by culture, the model writes
        culture-by-culture. Instead, we assign every event to a thematic bucket
        and show: "Section 1: The Void — here's what 8 cultures say about it."
        """
        outline_id = outline.id

        skeletons = list((await session.execute(
            select(CultureEventSkeleton).where(
                CultureEventSkeleton.story_outline_id == outline_id
            )
        )).scalars().all())

        narr_labels: dict[str, str] = {}
        narr_rows = (await session.execute(
            select(CultureNarrative.culture_key, CultureNarrative.culture_label).where(
                CultureNarrative.story_outline_id == outline_id
            )
        )).all()
        for ck, cl in narr_rows:
            narr_labels[ck] = cl

        skeletons.sort(key=lambda s: CULTURE_AGE_ORDER.get(s.culture_key, 99))

        actor_names = await self._get_epoch_actor_names(session, epoch.id)

        equivalences = await self._gather_equivalences(session)

        # Assign every event to a thematic bucket
        buckets = self._assign_events_to_themes(skeletons, narr_labels)
        all_unique: list[str] = []
        for skel in skeletons:
            unique = skel.unique_details if isinstance(skel.unique_details, list) else []
            all_unique.extend(unique)

        chapter_summary = outline.summary or outline.title
        parts = [
            f"# CHAPTER TOPIC: {outline.title}",
            f"# EPOCH: {epoch.title}",
            f"\n## WHAT THIS CHAPTER IS SPECIFICALLY ABOUT:",
            f"{chapter_summary}",
            f"\nWrite ONLY about this topic. Do NOT retell earlier events.",
            "",
        ]

        if prior_summaries:
            parts.append("## ALREADY TOLD IN PRIOR CHAPTERS (do NOT repeat):")
            for ps in prior_summaries:
                parts.append(f"  - {ps}")
            parts.append("")
            parts.append("Start where the story left off. Characters already introduced")
            parts.append("can be referenced without re-introducing them.")
            parts.append("")

        if established_cast:
            parts.append("## ESTABLISHED CAST (reuse these EXACT names — do NOT rename):")
            for arch_name, aka_list in established_cast.items():
                parts.append(f"  • {arch_name} = {', '.join(aka_list[:8])}")
            parts.append("")
            parts.append("If any source name in the plot beats matches an established character,")
            parts.append("use that character's established archetype name. Only create a NEW")
            parts.append("archetype for characters who have genuinely never appeared before.")
            parts.append("")

        # Separate events by priority: oldest traditions form backbone
        primary_beats: list[str] = []   # Sumerian/Mesopotamian (age_rank <= 2)
        secondary_beats: list[str] = [] # Egyptian, Hittite, Canaanite (age_rank 3-5)
        enrichment_beats: list[str] = [] # All other traditions
        global_actors: list[str] = []
        seen_global: set[str] = set()
        all_vivid: list[str] = []

        for theme_name, theme_events in buckets:
            if not theme_events:
                continue

            for ev in theme_events:
                for a in ev.get("actors", []):
                    a_clean = a.strip()
                    if a_clean and a_clean.lower() not in seen_global:
                        global_actors.append(a_clean)
                        seen_global.add(a_clean.lower())

                action = str(ev.get("action", "")).strip()[:250]
                detail = str(ev.get("source_detail", "")).strip()[:200]
                if not action:
                    continue
                beat_line = f"[{theme_name}] {action}"
                if detail and detail != "None":
                    beat_line += f" — {detail}"

                age_rank = ev.get("_age_rank", 99)
                if age_rank <= 2:
                    primary_beats.append(beat_line)
                elif age_rank <= 5:
                    secondary_beats.append(beat_line)
                else:
                    enrichment_beats.append(beat_line)

        for skel in skeletons:
            unique = skel.unique_details if isinstance(skel.unique_details, list) else []
            all_vivid.extend(unique)

        # PRIMARY SOURCE: cuneiform tablets (backbone of the story)
        parts.append("## PRIMARY SOURCE — OLDEST TRADITIONS (this is the backbone of the story):\n")
        for i, beat in enumerate(primary_beats[:12], 1):
            parts.append(f"  {i}. {beat}")
        parts.append("")

        # SECONDARY: ancient traditions that enrich
        if secondary_beats:
            parts.append("## SECONDARY SOURCES (enrich the backbone with these details):\n")
            for beat in secondary_beats[:8]:
                parts.append(f"  • {beat}")
            parts.append("")

        # ENRICHMENT: other traditions adding color
        if enrichment_beats:
            parts.append("## ENRICHMENT (weave these details into the story):\n")
            for beat in enrichment_beats[:8]:
                parts.append(f"  • {beat}")
            parts.append("")

        # CHARACTER LIST — separate established from new
        # Filter out actors already in established cast
        established_names_lower: set[str] = set()
        if established_cast:
            for aka_list in established_cast.values():
                for aka in aka_list:
                    established_names_lower.add(aka.lower())

        new_actors = [a for a in global_actors if a.lower() not in established_names_lower]
        if new_actors:
            parts.append("## NEW CHARACTERS (not yet in established cast — create archetype names):")
            parts.append(f"  {', '.join(new_actors[:20])}")
            parts.append("  Group names that play the same ROLE into ONE archetype.")
            parts.append("")
        if not established_cast:
            parts.append("## ALL CHARACTERS (create archetype names, put individual names in entity_mentions):")
            parts.append(f"  {', '.join(global_actors[:30])}")
            parts.append("  Group names that play the same ROLE into ONE archetype.")
            parts.append("")

        # Known equivalences
        if equivalences:
            parts.append("## KNOWN SAME CHARACTER:")
            for eq in equivalences:
                all_names = [eq["primary_name"]] + eq["equivalents"][:8]
                parts.append(f"  → {', '.join(all_names)}")
            parts.append("")

        if all_vivid:
            parts.append("## VIVID DETAILS (weave into the story):")
            for ud in all_vivid[:20]:
                parts.append(f"  • {ud}")
            parts.append("")

        if prior_narrative:
            parts.append(f"## END OF PRIOR CHAPTER (continue from this point):")
            parts.append(f"...{prior_narrative[-600:]}")
            parts.append("")

        return "\n".join(parts)


    @staticmethod
    def _assign_events_to_themes(
        skeletons: list, narr_labels: dict[str, str]
    ) -> list[tuple[str, list[dict]]]:
        """Assign events from all cultures into universal thematic buckets.

        Returns: [(theme_name, [tagged_events])] in narrative order.
        """
        # Universal creation narrative themes — these work across virtually all traditions
        THEME_KEYWORDS: list[tuple[str, list[str]]] = [
            ("The Primordial Void", [
                "void", "chaos", "nothing", "primordial", "before", "beginning",
                "darkness", "silence", "waters", "deep", "abyss", "ocean", "sea",
                "formless", "emptiness", "swamp", "egg", "unformed",
            ]),
            ("The First Creator Stirs", [
                "creator", "first being", "self-existent", "emerges", "stirs",
                "awakens", "omniscient", "contemplat", "desire", "will",
                "thought", "word", "speaks", "utters", "declares",
            ]),
            ("Separation of Sky and Earth", [
                "separation", "sky", "heaven", "earth", "lifts", "raises",
                "vault", "firmament", "above", "below", "dome", "canopy",
                "pillar", "uplifter", "splits", "divides",
            ]),
            ("Creation of Celestial Order", [
                "sun", "moon", "stars", "light", "day", "night", "time",
                "seasons", "years", "dawn", "dusk", "celestial", "planets",
                "constellation", "measure", "calendar",
            ]),
            ("The Birth of Gods and Powers", [
                "born", "begets", "generates", "offspring", "children",
                "gods", "divine", "titans", "giants", "powers",
                "archangel", "spirits", "sacred beings", "deities",
            ]),
            ("Shaping the World", [
                "land", "mountain", "river", "island", "world tree",
                "continent", "shape", "form", "fashion", "build",
                "body", "flesh", "bones", "blood", "skull",
                "spear", "stir", "churn",
            ]),
            ("Creation of Humanity", [
                "human", "man", "woman", "people", "clay", "mud",
                "breath", "blood", "rib", "dust", "maize", "corn",
                "wood", "tree trunk", "labor", "toil", "servant",
            ]),
            ("The Cosmic Struggle", [
                "battle", "fight", "slay", "kill", "castrat", "sickle",
                "serpent", "monster", "dragon", "rebel", "overthrow",
                "vengeance", "punishment", "flood", "destroy",
            ]),
            ("Prophecy and Fate", [
                "prophecy", "fate", "doom", "end", "ragnar", "eschat",
                "rebirth", "renewal", "cycle", "return", "survivors",
                "future", "destiny",
            ]),
        ]

        # Build buckets
        theme_buckets: list[tuple[str, list[dict]]] = [(name, []) for name, _ in THEME_KEYWORDS]
        overflow: list[dict] = []

        for skel in skeletons:
            label = narr_labels.get(skel.culture_key, skel.culture_key)
            age_rank = CULTURE_AGE_ORDER.get(skel.culture_key, 99)
            events = skel.events_json if isinstance(skel.events_json, list) else []

            ANTI_KEYWORDS = [
                # Historical/political
                "garrison", "soldier", "army", "revolt", "military", "kingdom",
                "dynasty", "emperor", "pharaoh", "inscription", "archaeolog",
                "excavat", "museum", "script", "decipher", "merchant", "trade",
                "tax", "census", "governor", "province", "colony", "treaty",
                "ambassador", "alliance", "psammetichos", "meroitic", "ethiopi",
                "privy member", "deserter", "6th century", "5th century",
                "mid-sixth", "ninth century", "foreign stories", "foreign hero",
                "legitimacy", "prestige", "rival groups",
                # Taoist/philosophical (not creation narrative)
                "penumbra", "umbra", "chuang", "hui tz", "lao tz",
                "tao te", "non-being", "non-action", "wu wei",
                "being and non-being", "difficult and easy",
                "passions", "philosopher", "philosophy", "instability of purpose",
                "qualification", "infinitesimal", "inseparable",
                "how can it be known", "resinous rain",
                "inward standard", "improper treatment",
                "adaptation outwardly", "clay is fired to make a vessel",
                "vessel's use depends", "hub's hole",
                "fall, be obliterated", "lie prostrate",
                # Non-mythological trades/animals
                "cook", "bullock", "butcher", "praying mantis",
                "outpost", "standing watch", "relieved", "rotated",
                "tiger", "horses, lest",
            ]

            for ev in events[:15]:
                ev_text = (
                    str(ev.get("event", "")) + " " +
                    str(ev.get("action", "")) + " " +
                    str(ev.get("outcome", "")) + " " +
                    str(ev.get("source_detail", "")) + " " +
                    " ".join(str(a) for a in ev.get("actors", []))
                ).lower()

                # Skip obviously non-mythological events
                if any(ak in ev_text for ak in ANTI_KEYWORDS):
                    continue

                tagged = {**ev, "_culture": label, "_age_rank": age_rank}

                best_score = 0
                best_idx = -1
                for idx, (_, keywords) in enumerate(THEME_KEYWORDS):
                    score = sum(1 for kw in keywords if kw in ev_text)
                    if score > best_score:
                        best_score = score
                        best_idx = idx

                if best_score >= 2 and best_idx >= 0:
                    theme_buckets[best_idx][1].append(tagged)
                elif best_score == 1 and best_idx >= 0:
                    theme_buckets[best_idx][1].append(tagged)
                # Events with score 0 are dropped — they don't match
                # any creation/cosmogonic theme and are likely irrelevant

        # Sort events within each bucket by age rank (oldest first)
        for _, events in theme_buckets:
            events.sort(key=lambda e: e.get("_age_rank", 99))

        # Drop overflow entirely — unmatched events are noise
        return [(name, evs) for name, evs in theme_buckets if evs]

    async def _get_epoch_actor_names(
        self, session: AsyncSession, epoch_id: uuid.UUID
    ) -> list[tuple[str, str]]:
        """Get canonical actor names + aliases for this epoch for entity annotation."""
        try:
            rows = (await session.execute(text("""
                SELECT DISTINCT a.canonical_name,
                    COALESCE(
                        (SELECT string_agg(DISTINCT eq_name, ', ')
                         FROM (
                             SELECT COALESCE(
                                 (SELECT canonical_name FROM canonical_actors WHERE id = ee.equivalent_entity_id),
                                 ''
                             ) as eq_name
                             FROM entity_equivalences ee
                             WHERE ee.primary_entity_id = a.id
                             LIMIT 5
                         ) sub
                         WHERE eq_name != ''
                        ), ''
                    ) as also_known_as
                FROM canonical_actors a
                JOIN canon_dependencies d ON d.child_type = 'actor' AND d.child_id = a.id
                JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
                WHERE c.epoch_id = :eid AND c.is_current = true AND a.is_current = true
                ORDER BY a.canonical_name
                LIMIT 50
            """), {"eid": str(epoch_id)})).all()
            return [(r[0], r[1]) for r in rows]
        except Exception:
            logger.warning("Failed to get epoch actor names", exc_info=True)
            return []

    # -----------------------------------------------------------------------
    # Full pipeline orchestrator
    # -----------------------------------------------------------------------

    async def run_full_pipeline(
        self,
        session: AsyncSession,
        *,
        epoch_orders: list[int] | None = None,
        skip_existing: bool = False,
        passes: str = "1,2,3",
    ) -> dict:
        """Run the complete three-pass pipeline for all chapters."""
        from src.canon.database import async_session_factory

        pass_set = {int(p.strip()) for p in passes.split(",")}

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

        stats = {
            "culture_narratives": 0,
            "event_skeletons": 0,
            "unified_chapters": 0,
            "total_words": 0,
        }
        prior_narrative: str | None = None
        prior_summaries: list[str] = []
        # Running cast: archetype_name -> list of also_known_as names
        established_cast: dict[str, list[str]] = {}

        for epoch, outlines in epoch_outlines:
            if not outlines:
                logger.warning("No outlines for epoch %s — run plan_all_epochs first", epoch.title)
                continue

            for outline in outlines:
                logger.info("=== Pipeline: %s / %s ===", epoch.title, outline.title)

                if 1 in pass_set:
                    culture_narrs = await self.generate_culture_narratives(
                        outline, epoch, skip_existing=skip_existing
                    )
                    stats["culture_narratives"] += len(culture_narrs)

                if 2 in pass_set:
                    skeletons = await self.extract_event_skeletons(
                        outline, skip_existing=skip_existing
                    )
                    stats["event_skeletons"] += len(skeletons)

                if 3 in pass_set:
                    story = await self.synthesize_unified_chapter(
                        None, outline, epoch, prior_narrative,
                        prior_summaries=prior_summaries,
                        established_cast=established_cast,
                    )
                    prior_narrative = story.narrative_text
                    prior_summaries.append(
                        f"Ch {outline.chapter_number} '{outline.title}': {outline.summary or outline.title}"
                    )
                    # Update established cast from this chapter's entity mentions
                    mentions = story.entity_mentions_json or []
                    if isinstance(mentions, list):
                        for m in mentions:
                            name = m.get("name", "")
                            aka = m.get("also_known_as", [])
                            if name and aka:
                                if name in established_cast:
                                    existing = set(established_cast[name])
                                    existing.update(aka)
                                    established_cast[name] = list(existing)
                                else:
                                    established_cast[name] = list(aka)
                    logger.info("Established cast now has %d archetypes", len(established_cast))
                    stats["unified_chapters"] += 1
                    stats["total_words"] += story.word_count or 0

        logger.info("Pipeline complete: %s", stats)
        return stats

    # Also keep backward-compatible run_full_synthesis
    async def run_full_synthesis(
        self,
        session: AsyncSession,
        *,
        epoch_orders: list[int] | None = None,
        skip_existing: bool = False,
    ) -> dict:
        """Backward-compatible entry point that runs the full 3-pass pipeline."""
        return await self.run_full_pipeline(
            session,
            epoch_orders=epoch_orders,
            skip_existing=skip_existing,
            passes="1,2,3",
        )

    # -----------------------------------------------------------------------
    # Epoch summary for planner (Phase 0)
    # -----------------------------------------------------------------------

    async def _build_epoch_summary(
        self, session: AsyncSession, epoch: CanonicalEpoch
    ) -> str:
        ch_q = select(CanonicalChapter.title, CanonicalChapter.chapter_summary).where(
            CanonicalChapter.epoch_id == epoch.id,
            CanonicalChapter.is_current.is_(True),
        ).order_by(CanonicalChapter.chapter_order)
        ch_rows = (await session.execute(ch_q)).all()

        if not ch_rows:
            return "No data available for this epoch."

        cultures = set()
        for title, _ in ch_rows:
            norm = normalize_culture_from_title(title)
            if norm:
                cultures.add(norm[1])

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
            for eq in equivalences:
                all_names = [eq["primary_name"]] + eq["equivalents"][:8]
                parts.append(f"  - SAME ENTITY: {', '.join(all_names)}")

        return "\n".join(parts)

    # -----------------------------------------------------------------------
    # Shared helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_annotations(narrative: str) -> list[dict]:
        """Extract entity mentions from [[type:Name]] annotations in narrative text."""
        mentions = []
        seen = set()
        for match in re.finditer(r'\[\[(actor|event|place):([^\]]+)\]\]', narrative):
            etype, name = match.group(1), match.group(2).strip()
            if name.lower() in seen:
                continue
            seen.add(name.lower())

            # Check for parenthetical aliases right after: [[actor:Enki]] (Ea, Nudimmud)
            after = narrative[match.end():match.end() + 100]
            aka_match = re.match(r'\s*\(([^)]+)\)', after)
            also_known_as = []
            if aka_match:
                also_known_as = [a.strip() for a in aka_match.group(1).split(",") if a.strip()]

            mentions.append({
                "name": name,
                "type": etype,
                "also_known_as": also_known_as,
            })
        return mentions

    async def _resolve_entity_mentions(
        self, session: AsyncSession, mentions: list[dict]
    ) -> list[dict]:
        """Resolve entity names from DeepSeek output to ALL matching canonical entity IDs.

        For merged archetypes (e.g. "The Great Father" with also_known_as ["Nu", "Apsu", "Brahman"]),
        we find ALL matching canonical entities so the frontend can display the full merge.
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
            all_canonical_ids: list[str] = []
            primary_id: str | None = None

            names_to_try = [name.strip()]
            for aka in m.get("also_known_as", []):
                if aka and aka.strip():
                    names_to_try.append(aka.strip())

            # Find ALL matching canonical entities across all also_known_as names
            seen_ids: set[str] = set()
            for try_name in names_to_try:
                try:
                    q = select(tbl.id).where(
                        func.lower(tbl.canonical_name) == try_name.lower(),
                        tbl.is_current.is_(True),
                    ).limit(1)
                    row = (await session.execute(q)).scalar_one_or_none()
                    if row and str(row) not in seen_ids:
                        seen_ids.add(str(row))
                        all_canonical_ids.append(str(row))
                        if not primary_id:
                            primary_id = str(row)
                except Exception:
                    pass

            # Also check entity_equivalences for actor types
            if entity_type == "actor":
                for try_name in names_to_try:
                    try:
                        eq_rows = (await session.execute(text("""
                            SELECT ee.primary_entity_id, ee.equivalent_entity_id
                            FROM entity_equivalences ee
                            JOIN canonical_actors ca ON ca.id = ee.equivalent_entity_id
                            WHERE LOWER(ca.canonical_name) = :n
                              AND ee.primary_entity_type = 'actor'
                        """), {"n": try_name.lower()})).all()
                        for eq_row in eq_rows:
                            for eid in [str(eq_row[0]), str(eq_row[1])]:
                                if eid not in seen_ids:
                                    seen_ids.add(eid)
                                    all_canonical_ids.append(eid)
                                    if not primary_id:
                                        primary_id = eid
                    except Exception:
                        pass

            # Fuzzy match as last resort (only for primary_id if still missing)
            if not primary_id:
                try:
                    search_name = name.strip()
                    if search_name.lower().startswith("the "):
                        search_name = search_name[4:]
                    q = select(tbl.id).where(
                        tbl.canonical_name.ilike(f"%{search_name}%"),
                        tbl.is_current.is_(True),
                    ).limit(1)
                    row = (await session.execute(q)).scalar_one_or_none()
                    if row:
                        primary_id = str(row)
                        if primary_id not in seen_ids:
                            all_canonical_ids.append(primary_id)
                except Exception:
                    pass

            entry = {**m, "canonical_id": primary_id}
            if len(all_canonical_ids) > 1:
                entry["all_canonical_ids"] = all_canonical_ids
            resolved.append(entry)
        return resolved

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

    async def _call_deepseek(self, prompt: str, *, system: str = UNIFIED_MERGE_PROMPT) -> dict:
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

        empty = {"narrative_text": "", "key_claims": [], "image_prompts": [], "chapters": [], "events": [], "actors": [], "places": [], "unique_details": []}

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.error("DeepSeek HTTP %d: %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
                data = resp.json()

            raw = data["choices"][0]["message"]["content"]
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)

            # Try parsing the full response as JSON
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

                # JSON parse failed — try fixing common issues
                json_str = json_match.group()
                # Fix unescaped newlines inside string values
                fixed = re.sub(r'(?<=": ")(.*?)(?="[,\}])', lambda m: m.group().replace('\n', '\\n'), json_str, flags=re.DOTALL)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

                # Last resort: extract narrative_text field directly with regex
                narr_match = re.search(r'"narrative_text"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', json_str, re.DOTALL)
                if narr_match:
                    narr_text = narr_match.group(1)
                    narr_text = narr_text.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
                    logger.warning("Extracted narrative_text via regex fallback (%d chars)", len(narr_text))
                    return {**empty, "narrative_text": narr_text}

            logger.warning("No valid JSON found in DeepSeek response (%d chars raw)", len(raw))
            # If the raw text doesn't look like JSON, it might be a plain narrative
            if not raw.startswith("{"):
                return {**empty, "narrative_text": raw}
            return empty
        except RuntimeError:
            raise
        except Exception:
            logger.exception("DeepSeek call failed")
            return empty
