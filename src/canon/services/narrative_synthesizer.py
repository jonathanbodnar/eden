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

PLANNER_SYSTEM_PROMPT = """You are the architect of a unified ancient world history — an alternative bible woven from every surviving tradition on Earth.

You are designing the TABLE OF CONTENTS for one epoch of this history. You will receive a summary of ALL entities, themes, and source traditions from this epoch across every culture on the planet.

Your job is to organize this into 5-15 thematic chapters that tell a unified narrative.

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
{
  "chapters": [
    {
      "chapter_number": 1,
      "title": "Epic chapter title",
      "summary": "2-3 sentence summary naming specific traditions that will be woven together",
      "themes": ["theme1", "theme2", "theme3"],
      "time_hint": "Before time / primordial / ~3000 BCE",
      "scope": "universal" or "regional",
      "regions": ["Mesopotamia", "Egypt"]
    }
  ]
}"""


CULTURE_NARRATOR_PROMPT = """You are a scholar writing the definitive account of one culture's ancient tradition.

You will receive source texts from a SINGLE cultural tradition. Your job is to write a rich, faithful narrative retelling of this culture's account — extracting EVERY actor, event, location, and unique detail from the sources.

## RULES:
1. Write 1500-2500 words of flowing narrative prose — a complete retelling of this culture's account
2. Be EXHAUSTIVELY FAITHFUL to the source texts. Every name, every action, every detail matters.
3. Include ALL actors mentioned in the sources — even minor ones
4. Include ALL locations, objects, and specific details (numbers, materials, sequences)
5. Do NOT add information not in the sources. Do NOT interpret or analyze.
6. Use the culture's own names for everything (e.g., "Enki" not "The Creator")
7. Write in present tense for vividness
8. Maintain the narrative sequence as presented in the sources
9. If sources contain direct speech or dialogue, preserve it
10. Note any unique details that are specific to THIS culture's account (details you would not expect to find in other traditions)

## OUTPUT FORMAT — return ONLY valid JSON:
{
  "narrative_text": "The full 1500-2500 word narrative...",
  "actors": [
    {"name": "Enki", "role": "god of wisdom and fresh water", "key_actions": ["creates humans from clay", "defies Enlil"]}
  ],
  "events": [
    {"event": "Creation of humans", "sequence": 1, "description": "Brief description"}
  ],
  "places": [
    {"name": "The Abzu", "description": "Underground freshwater ocean, domain of Enki"}
  ],
  "unique_details": [
    "Seven male and seven female humans are created simultaneously",
    "The womb-goddesses assist in shaping the clay"
  ]
}"""


EVENT_EXTRACTOR_PROMPT = """You are extracting a structured event timeline from a cultural narrative.

Read the narrative and extract every discrete event in chronological order. For each event, identify all components. Be thorough — capture every event, even brief ones.

Also identify details UNIQUE to this culture's account — things you would not expect other traditions to describe.

Return ONLY valid JSON:
{
  "events": [
    {
      "seq": 1,
      "event": "Brief event label",
      "actors": ["Name1", "Name2"],
      "action": "What specifically happens — the concrete action",
      "location": "Where this takes place (or null)",
      "objects": ["Key objects or materials involved"],
      "outcome": "The result or consequence of this event",
      "source_detail": "The most vivid/specific sentence or detail from the source about this event"
    }
  ],
  "unique_details": [
    "A detail specific to this tradition that other cultures would not have"
  ]
}"""


UNIFIED_MERGE_PROMPT = """You are writing a unified ancient world history — one continuous story as if it were an alternative bible.

Below you will receive EVENT CLUSTERS — groups of events from multiple cultures that describe THE SAME MOMENT in this story. Your job is to merge each cluster into ONE rich paragraph that fuses all the details together.

## THE ABSOLUTE RULE — ONE STORY, ONE WORLD

Write as if only ONE ancient civilization existed and these events happened ONCE.

BANNED WORDS AND PHRASES — if ANY of these appear in your output, you have FAILED:
- Any culture/people name: Sumerian, Hebrew, Egyptian, Greek, Norse, Chinese, Vedic, Hindu, Mesoamerican, Zoroastrian, Roman, Ainu, Japanese, African, Babylonian, Persian, Celtic, Polynesian
- Any geographic framing: "In Mesopotamia", "In the east", "In the north"
- Any attribution: "According to", "One tradition says", "In another account"
- Any comparison: "Similarly", "Likewise", "In parallel", "Another version"
- Any hedging: "Perhaps", "It is believed", "Some say"

The ONLY exception: on FIRST mention of a merged entity, parenthetical name variants: "(Enki, Khnum, Ptah)". No culture labels in the parenthetical.

## THE DIAMOND RULE — EVERY EVENT HAPPENED ONCE

Each event cluster below groups together the SAME EVENT as remembered by different peoples. These are NOT alternatives — they are FACETS of ONE event.

WRONG (sequential/separate):
"A god shapes humans from clay. The creator also breathes life into dust. A craftsman molds figures on a wheel."

RIGHT (fused into one moment):
"The divine craftsman (Enki, Khnum, Ptah) kneels at the potter's wheel. He shapes clay mixed with divine blood, seven male forms and seven female. He breathes into the nostrils of each. The womb-goddesses assist, pinching the clay into final form."

ALL details from ALL cultures coexist in ONE description. The paragraph grows RICHER with each culture's contribution — it does not restart or retell.

## STRUCTURE

The event clusters are ALREADY in chronological order. Write ONE or TWO paragraphs per cluster. The narrative should flow naturally from cluster to cluster — this is a continuous story, not a list.

Target: 1500-3000 words total. Every unique detail listed in the clusters MUST appear somewhere.

## WRITING RULES:
- Direct, authoritative tone — a historian recounting events that happened
- Present tense throughout
- Every sentence grounded in source evidence (no invented atmosphere)
- No modern analysis or commentary
- Vivid source details are your best material — USE THEM

## ENTITY ANNOTATION:
On FIRST mention of an important entity, wrap with: [[type:Archetype Name]]
Types: actor, event, place. Use descriptive archetype names, not culture-specific names.
After the annotation, add a SHORT parenthetical with the culture-specific name variants.
Example: [[actor:The Divine Craftsman]] (Enki, Khnum, Ptah) kneels at the wheel...
Aim for 15-30 annotations per chapter.

## OUTPUT FORMAT:
Return ONLY valid JSON:
{
  "narrative_text": "The full unified narrative (1500-3000 words)...",
  "key_claims": [
    {"claim": "brief claim", "source_ids": [], "score": 0.0-1.0, "cultures": ["culture1"]}
  ],
  "image_prompts": [
    {"description": "visual scene", "period": "time", "mood": "tone", "reference_artifacts": ["artifact"]}
  ],
  "entity_mentions": [
    {"name": "The Divine Craftsman", "type": "actor", "also_known_as": ["Enki", "Khnum"], "cultures": ["Sumerian", "Egyptian"], "role_in_chapter": "brief role"}
  ]
}"""


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
    ) -> StoryChapter:
        """Pass 3: Merge all event skeletons into one unified narrative."""
        from src.canon.database import async_session_factory

        logger.info("Pass 3 — merging unified narrative for: %s", outline.title)
        outline_id = outline.id
        epoch_id = epoch.id

        async with async_session_factory() as read_session:
            prompt = await self._build_merge_prompt(read_session, outline, epoch, prior_narrative)

        result = await self._call_deepseek(prompt, system=UNIFIED_MERGE_PROMPT)

        narrative = result.get("narrative_text", "")
        claims = result.get("key_claims", [])
        image_prompts = result.get("image_prompts", [])
        entity_mentions = result.get("entity_mentions", [])

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
                logger.info("  → Updated existing chapter: %d words (v%d)",
                            existing.word_count, existing.synthesis_version)
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
            logger.info("  → Created new chapter: %d words", story.word_count)
            return story

    async def _build_merge_prompt(
        self,
        session: AsyncSession,
        outline: StoryOutline,
        epoch: CanonicalEpoch,
        prior_narrative: str | None,
    ) -> str:
        """Build the merge prompt with events PRE-CLUSTERED by theme across cultures.

        Instead of presenting events grouped by culture (which leads DeepSeek to
        write culture-by-culture), we cluster similar events from different cultures
        together so DeepSeek sees "here are 8 cultures' versions of the same event —
        fuse them into one paragraph."
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

        parts = [
            f"# CHAPTER: {outline.title}",
            f"# EPOCH: {epoch.title}",
            f"# THEMES: {', '.join(outline.themes or [])}",
            f"# SUMMARY: {outline.summary}",
            f"\nThis chapter draws from {len(skeletons)} cultural traditions.",
            "",
        ]

        # Entity merge map
        equivalences = await self._gather_equivalences(session)
        if equivalences:
            parts.append("## ENTITY MERGE MAP")
            parts.append("These entities are THE SAME being. Use a DESCRIPTIVE ARCHETYPE NAME.")
            parts.append("On first mention, add parenthetical name variants.\n")
            for eq in equivalences:
                all_names = [eq["primary_name"]] + eq["equivalents"][:8]
                parts.append(f"  SAME ENTITY: {', '.join(all_names)}")
            parts.append("")

        # Collect ALL events from all cultures, tagged with culture
        all_events: list[dict] = []
        all_unique_details: list[str] = []

        for skel in skeletons:
            label = narr_labels.get(skel.culture_key, skel.culture_key)
            age_rank = CULTURE_AGE_ORDER.get(skel.culture_key, 99)
            events = skel.events_json if isinstance(skel.events_json, list) else []
            unique = skel.unique_details if isinstance(skel.unique_details, list) else []

            for ev in events:
                all_events.append({
                    **ev,
                    "_culture": label,
                    "_age_rank": age_rank,
                })

            for ud in unique:
                all_unique_details.append(ud)

        # Build thematic clusters by grouping events with similar labels
        # Use a simple approach: normalize event labels and group overlapping ones
        clusters = self._cluster_events(all_events)

        parts.append(f"## EVENT CLUSTERS ({len(clusters)} clusters)")
        parts.append("Each cluster groups the SAME EVENT as seen by multiple cultures.")
        parts.append("Write 1-2 paragraphs per cluster, FUSING all details into ONE description.")
        parts.append("Clusters are in chronological order — your narrative should follow this order.\n")

        for i, cluster in enumerate(clusters, 1):
            culture_count = len(set(e["_culture"] for e in cluster["events"]))
            parts.append(f"### CLUSTER {i}: {cluster['label']} ({culture_count} cultures)")

            for ev in cluster["events"]:
                actors_str = ", ".join(ev.get("actors", []))
                parts.append(f"  [{ev['_culture']}] {ev.get('event', '')}")
                parts.append(f"    Actors: {actors_str}")
                parts.append(f"    Action: {ev.get('action', '')}")
                if ev.get("location"):
                    parts.append(f"    Location: {ev['location']}")
                if ev.get("objects"):
                    objs = ev["objects"] if isinstance(ev["objects"], list) else [ev["objects"]]
                    parts.append(f"    Objects: {', '.join(str(o) for o in objs)}")
                parts.append(f"    Outcome: {ev.get('outcome', '')}")
                if ev.get("source_detail"):
                    parts.append(f"    Vivid detail: {str(ev['source_detail'])[:200]}")
            parts.append("")

        if all_unique_details:
            parts.append("## UNIQUE DETAILS — MUST ALL APPEAR IN THE NARRATIVE")
            parts.append("These are precious culture-specific details. Weave EVERY one into the story:\n")
            for ud in all_unique_details:
                parts.append(f"  - {ud}")
            parts.append("")

        if prior_narrative:
            parts.append(f"## PRIOR CHAPTER (continue seamlessly):\n...{prior_narrative[-1500:]}")

        return "\n".join(parts)

    def _cluster_events(self, all_events: list[dict]) -> list[dict]:
        """Group events from different cultures into thematic clusters.

        Uses keyword overlap in event labels to identify events that describe
        the same moment. Events that don't match any cluster get their own.
        """
        # Normalize event labels for matching
        def _normalize(label: str) -> set[str]:
            stop = {"the", "of", "and", "a", "an", "is", "are", "from", "in", "to", "by", "with", "as"}
            words = re.sub(r'[^a-z\s]', '', label.lower()).split()
            return {w for w in words if w not in stop and len(w) > 2}

        clusters: list[dict] = []
        assigned = set()

        # Sort events by sequence within each culture, then interleave
        # First pass: identify cluster seeds from the oldest culture
        for ev in all_events:
            ev_id = id(ev)
            if ev_id in assigned:
                continue

            tokens = _normalize(ev.get("event", ""))
            if not tokens:
                clusters.append({"label": ev.get("event", "Unknown"), "events": [ev]})
                assigned.add(ev_id)
                continue

            cluster_events = [ev]
            assigned.add(ev_id)

            # Find matching events from other cultures
            for other in all_events:
                other_id = id(other)
                if other_id in assigned:
                    continue
                if other["_culture"] == ev["_culture"]:
                    continue

                other_tokens = _normalize(other.get("event", ""))
                overlap = tokens & other_tokens
                # Match if ≥2 meaningful words overlap, or if key action words match
                if len(overlap) >= 2 or (len(tokens) <= 3 and len(overlap) >= 1 and any(
                    w in overlap for w in ("creation", "primordial", "chaos", "void", "waters",
                                           "separation", "light", "humanity", "clay", "flood",
                                           "garden", "serpent", "tree", "fire", "naming",
                                           "death", "birth", "world", "gods", "heaven", "earth")
                )):
                    cluster_events.append(other)
                    assigned.add(other_id)

            # Sort cluster events by age rank (oldest first)
            cluster_events.sort(key=lambda e: e.get("_age_rank", 99))
            clusters.append({
                "label": cluster_events[0].get("event", "Unknown"),
                "events": cluster_events,
            })

        return clusters

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
                        None, outline, epoch, prior_narrative
                    )
                    prior_narrative = story.narrative_text
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

    async def _resolve_entity_mentions(
        self, session: AsyncSession, mentions: list[dict]
    ) -> list[dict]:
        """Resolve entity names from DeepSeek output to canonical entity IDs."""
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

            names_to_try = [name.strip()]
            for aka in m.get("also_known_as", []):
                if aka and aka.strip():
                    names_to_try.append(aka.strip())

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

            if not canonical_id:
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
                        canonical_id = str(row)
                except Exception:
                    pass

            resolved.append({**m, "canonical_id": canonical_id})
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
