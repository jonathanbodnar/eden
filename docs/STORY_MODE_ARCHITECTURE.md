# Story Mode: Narrative Synthesis Architecture

## Overview

Story Mode transforms raw source material (cuneiform tablets, sacred texts, ancient manuscripts) from the Explorer/database into a unified, alternative-bible-style narrative. The system treats every ancient tradition as a **record of perceived events**, not fiction, and weaves them into a single continuous history using a three-pass pipeline governed by 16 Laws of Synthesis.

---

## Data Flow: Explorer → Story Mode

```
┌──────────────────────────────────────────────────────────────────────┐
│                         EXPLORER / DATABASE                         │
│                                                                     │
│  source_records ─── texts from CDLI, Sacred-Texts, Wikipedia, etc.  │
│  canonical_actors ─ deities, humans, creatures (Enki, Ra, Brahma)   │
│  canonical_events ─ creation, flood, battles                        │
│  canonical_places ─ Eridu, Nippur, Eden                             │
│  canonical_epochs ─ Creation, Age of Gods, Flood, etc.              │
│  canon_support_links ─ which sources support which entities         │
│  entity_equivalences ─ cross-cultural entity merges (Law 8)         │
│  canon_scores ─── trust scores per entity (Laws 4-7)                │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    THREE-PASS SYNTHESIS PIPELINE                     │
│                                                                     │
│  Pass 0 ── Plan chapter outlines (DeepSeek + Planner Prompt)        │
│  Pass 1 ── Generate per-culture narratives (11 cultures × N ch)     │
│  Pass 2 ── Extract structured event skeletons from each narrative   │
│  Pass 3 ── Merge all skeletons into ONE unified chapter narrative   │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         STORY MODE UI                                │
│                                                                     │
│  Left panel ─── chapter list                                        │
│  Center panel ─ unified narrative (or per-culture if selected)      │
│  Right panel ── merged archetype details, source evidence            │
│  Bottom bar ── audio player (TTS)                                   │
│  Culture dropdown ─ shows only cultures that contributed             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## The 16 Laws of Synthesis

Every prompt sent to DeepSeek includes these laws. They govern all generation.

| # | Law | Purpose |
|---|-----|---------|
| 1 | **Myth as Recorded Memory** | Treat all ancient narratives as records of perceived events, not fiction |
| 2 | **Source-Only Input** | Only use information from primary sources, artifacts, or recorded traditions |
| 3 | **No Interpretation Injection** | Never add meaning, motive, symbolism, or explanation unless a source says it |
| 4 | **Age-Weighted Priority** | Older sources get higher weight. Cuneiform tablets (oldest) form the story backbone |
| 5 | **Cross-Cultural Convergence** | Independent recurrence across separated cultures increases structural weight |
| 6 | **Distribution Independence** | Popularity doesn't equal truth. Modern prominence is irrelevant |
| 7 | **Pattern Dominance** | Recurring structural patterns outweigh isolated claims |
| 8 | **Entity Convergence** | Merge entities across cultures only when role, action, context, AND pattern all align |
| 9 | **Minimal Assumption** | Choose the interpretation requiring the fewest unsupported assumptions |
| 10 | **Narrative Continuity** | One continuous timeline. Never "this culture says / that culture says" |
| 11 | **Contradiction Handling** | Prioritize older source, then stronger pattern. If unresolvable, parallelize |
| 12 | **Structural Consistency** | Once established, an entity stays consistent unless stronger evidence revises it |
| 13 | **Image Constraint** | Visual sources inform material context but cannot define narrative meaning |
| 14 | **Traceability** | Every narrative element must trace to at least one source |
| 15 | **Synthesis Constraint** | Combine only where compatible; otherwise layer or parallelize |
| 16 | **Ancient Time Anchoring** | Ancient internal timelines take priority over modern dating |

### Where Laws Are Enforced

- **Laws 4-7**: Implemented mathematically in `scoring_service.py` as a 6-factor formula:
  ```
  final = (age × 0.25) + (corroboration × 0.20) + (independence × 0.20)
        + (citation × 0.15) + (pattern × 0.10) - (ambiguity × 0.10)
  ```
- **Law 8**: Implemented in `merge_service.py` with a 4-criteria LLM check (role, action, context, pattern)
- **All 16 laws**: Embedded directly into every DeepSeek prompt (Planner, Culture Narrator, Event Extractor, Unified Merge)

---

## Pass 0: Chapter Planning

**Prompt**: `PLANNER_SYSTEM_PROMPT` + all 16 laws

**Input**: Summary of all entities, themes, and source traditions for one epoch.

**Output**: 5-15 thematic chapter outlines stored in `story_outlines`.

**Rules**:
- Early epochs (Creation, Gods, Flood) → fully unified chapters, all cultures merged
- Later epochs → shared patterns first, then regional arcs, then reconnection
- Never a chapter about just one culture
- Group by THEME first, REGION second

---

## Pass 1: Per-Culture Narratives

**Prompt**: `CULTURE_NARRATOR_PROMPT` + all 16 laws

For each chapter, the system:

1. **Gathers sources by culture** from the database:
   - Queries `canon_support_links` → `source_records` → `source_versions` for all entities in the epoch
   - Normalizes raw culture strings (e.g., "Neo-Babylonian" → `mesopotamian`) using `CULTURE_NORMALIZE`
   - Scores source relevance with `_score_source_relevance()` to filter out non-mythological content (archaeological papers, philosophical treatises, etc.)
   - Sorts cultures by `CULTURE_AGE_ORDER` (Sumerian=1, Mesopotamian=2, Egyptian=3, ...)

2. **Generates a 1500-2500 word narrative** for each culture using only that culture's own sources
   - Uses the culture's own deity names (Enki, not "The Creator")
   - Preserves direct speech and unique details
   - Extracts actors, events, places, and unique details

3. **Stores** results in `culture_narratives` table

**Result**: ~11 rich culture narratives per chapter (Mesopotamian, Egyptian, Hebrew, Vedic, Chinese, Greek, Norse, Mesoamerican, Zoroastrian, Ainu, Roman)

### Culture Normalization Map

| Canonical Key | Display Label | Example Raw Values |
|---|---|---|
| `sumerian` | Sumerian | "Sumerian", "Ur III" |
| `mesopotamian` | Mesopotamian / Babylonian | "Akkadian", "Babylonian", "Assyrian", "Neo-Babylonian" |
| `egyptian` | Ancient Egyptian | "Ancient Egypt", "New Kingdom" |
| `hebrew` | Hebrew / Israelite | "Hebrew", "Ancient Israelite", "Biblical" |
| `vedic` | Vedic / Hindu | "Vedic", "Hindu", "Sanskrit" |
| `chinese` | Ancient Chinese | "Chinese", "Taoist", "Zhou" |
| `greek` | Ancient Greek | "Greek", "Attic", "Hellenic" |
| `norse` | Norse / Germanic | "Norse", "Viking", "Edda" |
| `zoroastrian` | Zoroastrian / Persian | "Zoroastrian", "Persian", "Avesta" |
| `mesoamerican` | Mesoamerican | "Maya", "Aztec", "Popol Vuh" |
| `ainu` | Ainu / Japanese | "Ainu", "Japanese", "Shinto" |
| `roman` | Roman / Italic | "Roman", "Latin", "Etruscan" |

### Source Relevance Scoring

Sources are scored before inclusion to prevent non-mythological content from leaking in:

- **Mythological keywords** (boost): creation, creator, god, goddess, divine, flood, garden, clay, breath, spirit, genesis, cosmogony, enuma elish, rig veda, etc.
- **Anti-keywords** (penalize): script, inscription, excavation, archaeological, pottery, trade route, ISBN, linguistics, tao te ching, chuang tzu, confucius, etc.
- Sources scoring ≤ 0 are excluded entirely

---

## Pass 2: Event Extraction

**Prompt**: `EVENT_EXTRACTOR_PROMPT` + Laws 1, 3, 14

For each culture narrative from Pass 1:

1. DeepSeek extracts a structured timeline of discrete events
2. Each event includes: actors, action, location, objects, outcome, source_detail
3. Unique details are flagged separately

**Stored in**: `culture_event_skeletons` table (JSONB columns for events, actors, places, unique_details)

**Example event skeleton**:
```json
{
  "seq": 3,
  "event": "Creation of humans from clay",
  "actors": ["Enki", "Ninhursag"],
  "action": "Enki mixes clay from the abyss with the blood of a slain god",
  "location": "The Abzu",
  "objects": ["clay", "divine blood", "rush mat"],
  "outcome": "Seven male and seven female humans are formed",
  "source_detail": "He lays a rush mat upon the face of the waters and mixes earth"
}
```

---

## Pass 3: Unified Narrative Merge

**Prompt**: `UNIFIED_MERGE_PROMPT` + all 16 laws + specific application notes

This is where everything comes together. The system:

### 1. Assigns Events to Thematic Buckets

Events from ALL cultures are assigned to universal narrative themes using keyword matching:

| Theme | Keywords |
|---|---|
| The Primordial Void | void, chaos, primordial, darkness, waters, deep, abyss |
| The First Creator Stirs | creator, emerges, awakens, desire, word, speaks |
| Separation of Sky and Earth | separation, sky, heaven, earth, firmament, vault |
| Creation of Celestial Order | sun, moon, stars, light, seasons, celestial |
| The Birth of Gods and Powers | born, begets, offspring, gods, divine, titans |
| Shaping the World | land, mountain, river, body, flesh, bones |
| Creation of Humanity | human, clay, breath, blood, dust, servant, toil |
| The First Civilization | city, temple, law, king, agriculture, irrigation |

Events that match anti-keywords (garrison, soldier, philosophy, etc.) are filtered out.

### 2. Separates Events by Age Priority

Events are split into three tiers based on `CULTURE_AGE_ORDER`:

- **PRIMARY SOURCE** (age_rank ≤ 2): Sumerian + Mesopotamian cuneiform — forms the story backbone
- **SECONDARY SOURCES** (age_rank 3-5): Egyptian, Hittite, Canaanite — enriches the backbone
- **ENRICHMENT** (age_rank > 5): All other traditions — adds color and detail

### 3. Provides Cross-Chapter Context

The prompt includes:
- **CHAPTER TOPIC**: What this specific chapter must be about
- **ALREADY TOLD**: Summaries of prior chapters (to prevent retelling)
- **ESTABLISHED CAST**: Archetype names from prior chapters with their also_known_as names, ensuring consistency (e.g., "The Divine Craftsman" stays the same across all 7 chapters)
- **KNOWN SAME CHARACTER**: Entity equivalences from the database
- **END OF PRIOR CHAPTER**: Last ~600 characters for narrative continuity

### 4. Archetype Name System

Every character and place uses an archetype name — never a culture-specific name.

| Archetype | Also Known As (stored in entity_mentions) |
|---|---|
| The Divine Craftsman | Enki, Ea, Khnum, Ptah, Prometheus |
| The Mother of Chaos | Tiamat, Omuroca, Thalatth |
| The Sun God | Ra, Atum, Khepera, Shamash, Surya |
| The Primordial Deep | Nun, Apsu, Brahman, Tao |
| The Mother of All Living | Aruru, Ninhursag, Belet-ili |
| The Shining Ones | Anunnaki, Devas, Netjeru, Elohim |

Archetype names are maintained via a **running cast list** that passes from chapter to chapter. When Ch 1 establishes "The Divine Craftsman = Enki, Ea, Marduk", chapters 2-7 receive this list and must reuse the same name.

### 5. Entity Annotation

Characters are annotated on first mention: `[[actor:The Divine Craftsman]]` or `[[place:The Holy City]]`. These annotations make the narrative interactive — clicking an entity in the UI opens the right panel with the full merge breakdown.

### 6. Entity Resolution

After DeepSeek returns the narrative, `_resolve_entity_mentions()`:
- Looks up each archetype name and all its `also_known_as` names against `canonical_actors`, `canonical_events`, `canonical_places`
- Collects ALL matching canonical IDs (not just the first) into `all_canonical_ids`
- Checks `entity_equivalences` for additional cross-cultural matches
- Stores `canonical_id` (primary) and `all_canonical_ids` (all matches) in the chapter's `entity_mentions_json`

---

## The Culture Dropdown

The culture dropdown in the center panel shows **only cultures that actually contributed** to the current chapter (i.e., have a `culture_narratives` record for that `story_outline_id`).

When a culture is selected:
- **Center panel**: Displays that culture's rich per-culture narrative from Pass 1 (the full 1500-2500 word faithful retelling)
- **Right panel**: Shows the actual source texts used to generate that culture's narrative

When "Unified History" is selected:
- **Center panel**: Displays the merged narrative from Pass 3
- **Right panel**: Shows entity merge breakdowns (archetype → all canonical entities across cultures)

---

## Right Panel: Entity Merge Breakdown

When you click an annotated entity in the narrative:

1. Frontend sends `entity_type`, `canonical_id`, `also_known_as[]`, and `all_canonical_ids[]` to the backend
2. Backend fetches the primary entity from the DB
3. Backend queries `entity_equivalences` for DB-established merges
4. Backend resolves ALL `also_known_as` names to find additional canonical entities
5. Backend resolves ALL `all_canonical_ids` to fetch entities matched during synthesis
6. For each matched entity, it fetches the cultures from `canon_support_links` → `source_records`
7. Returns the full breakdown: archetype name, all cultural identities, cultures, merge reasoning, source evidence

**Display**:
- "MERGED ARCHETYPE: The Divine Craftsman"
- "Found in 5 cultures: Mesopotamian, Egyptian, Hebrew, Greek, Vedic"
- Cultural identities: Enki (Sumerian), Ptah (Egyptian), Khnum (Egyptian), etc.
- Why merged: role similarity, action similarity, context alignment
- Source evidence: links to original texts

---

## Database Schema (Story Mode tables)

```
story_outlines
├── id (UUID)
├── epoch_id → canonical_epochs
├── chapter_number
├── title ("The Primordial Void and the First Stirring")
├── summary
├── themes (JSONB: ["creation", "void", "chaos"])
├── time_hint ("Before time / primordial")
├── scope ("universal" | "regional")
└── regions (JSONB)

culture_narratives
├── id (UUID)
├── story_outline_id → story_outlines
├── culture_key ("mesopotamian")
├── culture_label ("Mesopotamian / Babylonian")
├── narrative_text (1500-2500 words)
├── actors_json, events_json, places_json
└── source_ids (JSONB: which source_records were used)

culture_event_skeletons
├── id (UUID)
├── culture_narrative_id → culture_narratives
├── story_outline_id → story_outlines
├── culture_key
├── events_json (JSONB: structured event list)
└── unique_details (JSONB)

story_chapters
├── id (UUID)
├── story_outline_id → story_outlines
├── epoch_id → canonical_epochs
├── narrative_text (the unified narrative)
├── entity_mentions_json (JSONB: archetype → canonical_ids mapping)
├── word_count
└── synthesis_version
```

---

## Prompt Structure Summary

Each prompt sent to DeepSeek follows this structure:

```
SYSTEM PROMPT:
  ├── Role description
  ├── All 16 Laws of Synthesis
  ├── Specific law applications for this pass
  ├── Archetype naming rules
  ├── Banned words list
  ├── Annotation format
  └── Output JSON schema

USER PROMPT (for Pass 3):
  ├── # CHAPTER TOPIC: [title]
  ├── ## WHAT THIS CHAPTER IS SPECIFICALLY ABOUT: [summary]
  ├── ## ALREADY TOLD IN PRIOR CHAPTERS: [list of prior chapter summaries]
  ├── ## ESTABLISHED CAST: [archetype → also_known_as from prior chapters]
  ├── ## PRIMARY SOURCE (cuneiform backbone): [events with age_rank ≤ 2]
  ├── ## SECONDARY SOURCES: [events with age_rank 3-5]
  ├── ## ENRICHMENT: [events from all other traditions]
  ├── ## NEW CHARACTERS: [names not yet in established cast]
  ├── ## KNOWN SAME CHARACTER: [entity_equivalences from DB]
  ├── ## VIVID DETAILS: [unique details from all cultures]
  └── ## END OF PRIOR CHAPTER: [last 600 chars for continuity]
```

---

## LLM Configuration

- **Model**: DeepSeek `deepseek-reasoner`
- **Context window**: 64K tokens
- **Max output tokens**: 8192
- **Temperature**: Controlled by DeepSeek defaults (no override)
- **JSON parsing**: Multi-layer fallback (direct parse → strip markdown fences → fix unescaped newlines → regex extract narrative_text)
