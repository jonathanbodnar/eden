# Narrative Pipeline V2 — Deterministic Merge Architecture

**Status**: Planned, decisions locked, ready to build  
**Supersedes**: Current 3-pass pipeline in `narrative_synthesizer.py`  
**Migration**: Full rebuild — all chapters regenerated from scratch

---

## 1. Why V1 Fails

The current pipeline asks DeepSeek to do two things it's bad at inside the same prompt:

1. **Matching semantically-equivalent events across 11 cultures** (a clustering problem)
2. **Stripping culture names and swapping archetypes** (a string-replacement problem)

Because both are creative-model tasks in V1, DeepSeek hedges with "elsewhere, from another tradition..." and leaks raw culture names like "Enki" or "Tiamat". The prose is good; the merge is not.

**V2 principle**: take the deterministic tasks away from the LLM. Let the LLM do what it's good at — writing prose from structured input.

---

## 2. The V2 Pipeline

```
                   ┌─────────────────────────────────────┐
                   │  PLANNING (unchanged from V1)       │
                   │  DeepSeek generates chapter outline │
                   └──────────────┬──────────────────────┘
                                  │
     ┌────────────────────────────┴────────────────────────────┐
     ▼                                                         ▼
┌─────────────────────────────┐       ┌─────────────────────────────┐
│ STAGE 1 — CULTURE FACT      │       │ STAGE 1 — CULTURE FACT      │
│ SHEET (LLM, per culture)    │  ...  │ SHEET (LLM, per culture)    │
│                             │       │                             │
│ Input: all sources for      │       │ Input: all sources for      │
│ culture C in chapter N      │       │ culture C in chapter N      │
│                             │       │                             │
│ Output:                     │       │ Output:                     │
│  • prose history (1500-2500 │       │  • prose history            │
│    words, for culture       │       │  • structured fact data     │
│    dropdown)                │       │    (actors, events,         │
│  • structured fact data     │       │    places, materials,       │
│    (actors, events, places) │       │    quotes, source_refs)    │
└──────────────┬──────────────┘       └──────────────┬──────────────┘
               │                                     │
               └──────────────────┬──────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────────┐
                   │ STAGE 2 — ATOMIC EVENT DISTILLATION │
                   │ (LLM, per culture)                  │
                   │                                     │
                   │ Cold, line-by-line events:          │
                   │ { seq, actors, verb, verb_family,   │
                   │   object, materials, place,         │
                   │   outcome, quoted_phrase,           │
                   │   source_ref }                      │
                   │                                     │
                   │ Plus: action_embedding (1536-dim)   │
                   └──────────────┬──────────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────────┐
                   │ STAGE 3 — DETERMINISTIC CLUSTERING  │
                   │ (PLATFORM — no LLM)                 │
                   │                                     │
                   │ Hybrid matcher:                     │
                   │ 1. Rule-based candidate clusters    │
                   │    (verb family + material + out-   │
                   │    come keyword + actor equivalence)│
                   │ 2. Embedding cosine confirms/splits │
                   │    (threshold 0.78)                 │
                   │                                     │
                   │ Retention rule (Laws 4, 5, 7):      │
                   │   retention = (10 / age_rank_old)   │
                   │             + (size - 1) * 5        │
                   │   keep if retention >= 5            │
                   │                                     │
                   │ Output: event_clusters sorted by    │
                   │ chapter narrative order             │
                   └──────────────┬──────────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────────┐
                   │ STAGE 3B — ARCHETYPE RESOLUTION     │
                   │ (PLATFORM + one-shot LLM for new)   │
                   │                                     │
                   │ For each cluster:                   │
                   │   1. Look up in archetype_registry  │
                   │      by actor also_known_as match   │
                   │   2. If no match: one-shot LLM      │
                   │      names the archetype from role/ │
                   │      actions, write to registry     │
                   │                                     │
                   │ Registry grows across chapters —    │
                   │ guarantees Ch 7 uses the same       │
                   │ "Divine Craftsman" as Ch 1          │
                   └──────────────┬──────────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────────┐
                   │ STAGE 4 — NARRATIVE RENDERING       │
                   │ (LLM, one call per chapter)         │
                   │                                     │
                   │ Input: pre-merged event_clusters    │
                   │ with resolved archetype names,      │
                   │ plus prior chapter summaries        │
                   │                                     │
                   │ Prompt asks ONLY for prose. No      │
                   │ merging, no archetype choice, no    │
                   │ cluster selection. Just render.     │
                   │                                     │
                   │ Style: literary historical. Sensory │
                   │ detail from sources, no thematic    │
                   │ drama. Historian's account, not     │
                   │ scripture.                          │
                   └──────────────┬──────────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────────┐
                   │ STAGE 5 — POST-PROCESSING           │
                   │ (PLATFORM — no LLM)                 │
                   │                                     │
                   │ 1. Scrub leaked culture names using │
                   │    ARCHETYPE_MAP word-boundary regex│
                   │ 2. Insert [[actor:Archetype]] on    │
                   │    first mention of each archetype  │
                   │ 3. Populate entity_mentions_json    │
                   │    with all_canonical_ids from      │
                   │    cluster contributing_actors      │
                   │ 4. Validate: fail if any banned     │
                   │    culture name remains in prose    │
                   └─────────────────────────────────────┘
```

---

## 3. Locked Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Event matching algorithm | **Hybrid**: rules first, embeddings break ties (threshold 0.78) |
| 2 | Singleton cluster retention | **Weighted**: `retention = 10/age_rank_oldest + (size-1)*5`, keep if ≥ 5 |
| 3 | Archetype naming for new clusters | **LLM one-shot**, write to `archetype_registry`, reuse globally |
| 4 | Stage 1 output | **Both** prose history (for dropdown) AND structured fact data |
| 5 | Migration approach | **Full rebuild** — wipe `story_chapters`, regenerate all |
| 6 | Stage 4 prose style | **Literary historical** — sensory detail, no thematic drama |

### Singleton retention examples

| Scenario | Cultures | Oldest age_rank | retention | Kept? |
|---|---|---|---|---|
| Sumerian-only event | 1 | 1 (Sumerian) | 10.0 | ✅ Keep |
| Mesopotamian-only | 1 | 2 | 5.0 | ✅ Keep |
| Egyptian-only | 1 | 3 | 3.33 | ❌ Drop |
| Hebrew-only | 1 | 4 | 2.5 | ❌ Drop |
| Hopi-only | 1 | 11 | 0.9 | ❌ Drop |
| Sumerian + Hebrew | 2 | 1 | 15.0 | ✅ Keep |
| Greek + Norse + Vedic (3-way) | 3 | 5 | 12.0 | ✅ Keep |
| Hebrew + Greek (both late) | 2 | 4 | 7.5 | ✅ Keep |

Result: oldest traditions always included even solo; later traditions need convergence support.

---

## 4. Data Model Changes

### New Tables

```sql
-- Replaces culture_event_skeletons; stricter schema
CREATE TABLE culture_atomic_events (
    id UUID PRIMARY KEY,
    culture_narrative_id UUID REFERENCES culture_narratives(id) ON DELETE CASCADE,
    story_outline_id UUID REFERENCES story_outlines(id) ON DELETE CASCADE,
    culture_key TEXT NOT NULL,
    seq INT NOT NULL,
    actors JSONB NOT NULL,                -- ["Enki", "Ninhursag"]
    verb TEXT NOT NULL,                   -- "molds"
    verb_family TEXT NOT NULL,            -- "make" | "destroy" | "separate" | ...
    objects JSONB,                        -- ["clay", "blood"]
    materials JSONB,                      -- normalized material tags
    place TEXT,
    outcome TEXT NOT NULL,
    outcome_keywords JSONB,               -- ["humanity", "first"]
    quoted_phrase TEXT,
    source_ref TEXT,                      -- for traceability
    action_embedding VECTOR(1536),        -- for cosine matching
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON culture_atomic_events (story_outline_id, culture_key);
CREATE INDEX ON culture_atomic_events (verb_family);
CREATE INDEX ON culture_atomic_events USING ivfflat (action_embedding vector_cosine_ops);

-- The merge layer — platform-generated, not LLM-generated
CREATE TABLE event_clusters (
    id UUID PRIMARY KEY,
    story_outline_id UUID REFERENCES story_outlines(id) ON DELETE CASCADE,
    cluster_key TEXT NOT NULL,            -- "humanity_shaped_from_earth"
    seq INT NOT NULL,                     -- chapter narrative order
    primary_archetype_name TEXT NOT NULL, -- "The Divine Craftsman"
    archetype_registry_id UUID REFERENCES archetype_registry(id),
    contributing_event_ids UUID[] NOT NULL,
    contributing_cultures JSONB NOT NULL, -- {"sumerian": ["enki"], "hebrew": ["yhwh"]}
    canonical_verb TEXT NOT NULL,         -- taken from oldest contributor
    canonical_outcome TEXT NOT NULL,
    materials JSONB,                      -- union across contributors
    vivid_details JSONB,                  -- from all sources, ranked by age
    source_quotes JSONB,                  -- direct quotes with culture tags
    age_rank_of_oldest INT NOT NULL,
    retention_score REAL NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON event_clusters (story_outline_id, seq);

-- Global archetype registry — single source of truth for merged names
CREATE TABLE archetype_registry (
    id UUID PRIMARY KEY,
    archetype_name TEXT UNIQUE NOT NULL,  -- "The Divine Craftsman"
    role_description TEXT,                -- "shapes matter into beings"
    also_known_as TEXT[] NOT NULL,        -- ["Enki", "Ea", "Khnum", "Ptah", "Prometheus"]
    canonical_ids UUID[] NOT NULL,        -- matched canonical_actors/events/places
    role_signature JSONB,                 -- {creator: 0.9, warrior: 0.2}
    first_seen_chapter_id UUID,
    first_seen_epoch_id UUID,
    usage_count INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON archetype_registry USING gin (also_known_as);
```

### Modified Tables

```sql
-- culture_narratives now holds BOTH prose history and fact data
ALTER TABLE culture_narratives
    ADD COLUMN prose_history TEXT,           -- readable 1500-2500 word history
    ADD COLUMN fact_sheet JSONB;             -- structured: actors, events, places, materials

-- story_chapters stores new metadata
ALTER TABLE story_chapters
    ADD COLUMN cluster_count INT,
    ADD COLUMN archetypes_used TEXT[],
    ADD COLUMN pipeline_version TEXT DEFAULT 'v2';
```

### Deprecated

- `culture_event_skeletons` — replaced by `culture_atomic_events`. Migration: drop after V2 cutover.

---

## 5. Stage 1 — Culture Fact Sheet (LLM)

**Prompt**: Produces two outputs in one JSON call.

**Rules**:
- 1500-2500 words of prose history (for culture dropdown display)
- Exhaustively structured fact data: every actor, epithet, action, place, object, material, number, quote
- Preserve source language names and phrases verbatim
- Cite source_ref for each event

**Output schema**:
```json
{
  "prose_history": "In the beginning, Enki of the Abzu...",
  "fact_sheet": {
    "actors": [
      {"name": "Enki", "epithets": ["god of wisdom", "lord of the Abzu"], "role": "creator"}
    ],
    "events": [
      {
        "seq": 1,
        "actors": ["Enki"],
        "action": "descends to the Abzu",
        "place": "Abzu",
        "objects": [],
        "outcome": "takes his dwelling in the waters",
        "quote": "Enki, the lord of wisdom, descended into the Abzu",
        "source_ref": "Enuma Elish Tablet I, line 60"
      }
    ],
    "places": [...],
    "materials": [...]
  }
}
```

---

## 6. Stage 2 — Atomic Event Distillation (LLM)

**Prompt**: Given the Stage 1 fact_sheet, produce atomic events in strict schema.

**Rules**:
- Every event is one verb, one primary actor set, one outcome
- No narration, no color, no "then" or "after"
- Verb must be categorized into `verb_family` from fixed vocabulary
- quoted_phrase must be verbatim from source when available

**Verb families (fixed vocabulary)**:
```
MAKE:      create, shape, mold, fashion, form, sculpt, carve, weave, produce, beget
DESTROY:   slay, rend, flood, burn, shatter, devour
SEPARATE:  split, divide, lift, raise, cleave, part
JOIN:      unite, marry, combine, bind
SPEAK:     declare, utter, command, name, curse, bless
MOVE:      descend, ascend, travel, flee, return, enter, emerge
GIVE:      bestow, grant, offer, sacrifice
TAKE:      seize, steal, claim, receive
CONTEND:   battle, wrestle, defeat, bind, imprison
TRANSFORM: change, become, transfigure
```

**Action embedding**: computed on `f"{verb} {objects} {outcome}"` for cosine matching.

**Output example**:
```json
{
  "seq": 3,
  "actors": ["Enki"],
  "verb": "molds",
  "verb_family": "MAKE",
  "objects": ["first humans"],
  "materials": ["clay", "divine blood"],
  "place": "Abzu",
  "outcome": "humanity comes into being to serve the gods",
  "outcome_keywords": ["humanity", "serve"],
  "quoted_phrase": "Let man be created out of the blood of a slain god",
  "source_ref": "Enuma Elish Tablet VI"
}
```

---

## 7. Stage 3 — Deterministic Clustering (Platform)

No LLM. Pure Python.

### Algorithm

```python
def cluster_events(events: list[AtomicEvent]) -> list[EventCluster]:
    # Step 1: Hard constraints — events can only cluster if verb_family matches
    by_family = group_by(events, "verb_family")
    
    candidate_clusters = []
    for family, family_events in by_family.items():
        # Step 2: Within family, build candidate clusters via rule matching
        clusters = build_rule_clusters(family_events)
        candidate_clusters.extend(clusters)
    
    # Step 3: For each candidate cluster, validate with embedding cosine
    confirmed = []
    for cluster in candidate_clusters:
        centroid = mean_embedding(cluster.events)
        keep = [e for e in cluster.events if cosine(e.embedding, centroid) >= 0.78]
        rejected = [e for e in cluster.events if e not in keep]
        confirmed.append(cluster.with_events(keep))
        # Rejected events become singletons that try to rejoin or stay solo
        for r in rejected:
            confirmed.append(singleton_cluster(r))
    
    # Step 4: Apply retention rule
    retained = [c for c in confirmed if retention_score(c) >= 5.0]
    
    # Step 5: Order clusters by chapter narrative logic
    return order_clusters(retained)
```

### Rule matcher (Step 2 detail)

Two events cluster if **all** of:
- Same `verb_family`
- Actor overlap via `entity_equivalences` OR both actors map to same existing archetype
- Material/object overlap (Jaccard ≥ 0.3) OR outcome keyword overlap (Jaccard ≥ 0.5)

### Retention score

```
retention = (10 / age_rank_of_oldest_contributor) + (len(contributing_cultures) - 1) * 5
keep if retention >= 5.0
```

### Cluster ordering within chapter

Based on canonical narrative sequence for each chapter theme (chapter already has `themes` from Stage 0):
- Creation chapters: void → stir → separation → celestial → gods → world → humans → civilization
- Later chapters: use seq order from primary source (oldest)

---

## 8. Stage 3B — Archetype Resolution (Platform + One-Shot LLM)

For each cluster, determine `primary_archetype_name`.

### Resolution order

1. **Direct hit**: Does any contributing actor's name appear in `archetype_registry.also_known_as`?
   - Yes → use that archetype, append new actor names to `also_known_as`, increment `usage_count`

2. **Equivalence hit**: Does `entity_equivalences` link any contributing actor to an archetype's `canonical_ids`?
   - Yes → use that archetype

3. **Role-signature hit**: Does the cluster's role signature (derived from verb_family + outcome_keywords) match an existing archetype's `role_signature` above 0.8 cosine?
   - Yes → use that archetype, expand `also_known_as`

4. **New archetype — LLM one-shot**:
   - Send DeepSeek: list of contributing actors + their actions + outcome
   - Ask for: `{archetype_name, role_description}` as a single-line JSON response
   - Constraints in prompt: title-case English phrase, no culture references, never a raw deity name
   - Write to `archetype_registry`, link cluster

The registry is **write-once-reuse-forever**. Chapter 1 establishes "The Divine Craftsman" and every subsequent chapter that needs it finds it in step 1.

---

## 9. Stage 4 — Narrative Rendering (LLM)

**Input to DeepSeek**: ordered `event_clusters` with resolved archetype names, prior chapter summaries, chapter topic, chapter title.

**DeepSeek's scope is radically reduced**:
- No merging decisions (already done)
- No archetype decisions (already done)
- No selection decisions (retention already done)
- Only: render each cluster as 3-6 sentences of prose and transition between them

**Prompt skeleton**:
```
You are a historian writing chapter N of a unified ancient world history.

CHAPTER: {title}
TOPIC: {summary}

PRIOR CHAPTERS (do not retell these):
{prior_summaries}

Render the following event clusters into continuous literary prose.

Each cluster is pre-merged — all cultural parallels have been unified.
Use the exact archetype names provided. Do NOT introduce culture-specific deity names.
Do NOT add "according to" or "one tradition holds" framing.
Do NOT tell the same event multiple ways. One cluster = one telling.

Style: literary historical. Rich sensory detail drawn from the provided
vivid_details. Historian's confident voice, not scripture, not drama.

CLUSTERS IN ORDER:

[1] {archetype_name} — {canonical_verb} {canonical_outcome}
    Materials: {materials}
    Vivid details (weave in naturally):
      - {detail_1 with culture tag}
      - {detail_2}
    Source quotes (use selectively):
      - "{quote_1}"
    Also known as in sources: {contributing_deities}  [DO NOT USE IN PROSE]

[2] ...

Output JSON:
{
  "narrative_text": "..."
}
```

Target length: 1500-2500 words. Cluster count × 5 sentences is the rough budget.

---

## 10. Stage 5 — Post-Processing (Platform)

No LLM. Pure Python.

### Steps

1. **Load archetype map**: `{archetype_name: also_known_as[]}` for all archetypes used in this chapter's clusters.

2. **Scrub leaked names**: for each `name` in each archetype's `also_known_as`, do word-boundary regex replace in the narrative with the archetype name.
   - `\bEnki\b` → `The Divine Craftsman`
   - `\bMarduk\b` → `The Divine Craftsman`
   - Handles possessives: `Enki's` → `The Divine Craftsman's`

3. **Insert annotations**: find the first occurrence of each archetype name, wrap as `[[actor:Archetype Name]]` (or `[[place:...]]`).

4. **Populate entity_mentions_json**:
   ```json
   [
     {
       "name": "The Divine Craftsman",
       "type": "actor",
       "also_known_as": ["Enki", "Ea", "Khnum", "Ptah"],
       "canonical_id": "...",
       "all_canonical_ids": ["...", "...", "..."],
       "archetype_registry_id": "..."
     }
   ]
   ```

5. **Validation**: scan final prose for any banned culture word (Sumerian, Hebrew, Egyptian…) or known deity name not in the current archetype_map. Fail the chapter if found — log which cluster introduced it.

---

## 11. Where the 16 Laws Are Enforced

| Law | Stage | Mechanism |
|---|---|---|
| 1 Memory | 1 | Prompt rule |
| 2 Source-only | 1 | Prompt rule + source_ref requirement |
| 3 No interpretation | 1, 2 | Prompt rule, strict schema |
| **4 Age priority** | 3 (code) | `canonical_verb` taken from oldest contributor; retention formula rewards age |
| **5 Cross-cultural convergence** | 3 (code) | Cluster size is the convergence signal, factors into retention |
| 6 Distribution independence | 3 (code) | No frequency weighting — raw count only |
| **7 Pattern dominance** | 3 (code) | Retention drops singletons from young sources |
| **8 Entity convergence** | 3B (code + registry) | Archetype map is deterministic, 4-criteria match |
| 9 Minimal assumption | 2 | Strict schema rejects interpretation |
| **10 Narrative continuity** | 4 (prompt) | LLM only sees merged clusters — can't frame by culture |
| 11 Contradiction handling | 3 (code) | Embedding cosine flags disagreement; parallel clusters possible |
| **12 Structural consistency** | 3B (registry) | archetype_registry is global and write-once |
| 13 Image constraint | 1 | Source filter excludes image-only sources from text fields |
| **14 Traceability** | all | source_ref threaded through every row |
| 15 Synthesis constraint | 3 (code) | Retention drops incompatible singletons |
| 16 Ancient time anchoring | 3 (code) | Cluster ordering uses oldest source's sequence |

**Bold = now enforced in code rather than LLM prompt.** That's 8 of the 16.

---

## 12. Migration Plan

### Phase 0 — Schema
1. Alembic migration: create `culture_atomic_events`, `event_clusters`, `archetype_registry`
2. Alter `culture_narratives` to add `prose_history`, `fact_sheet`
3. Alter `story_chapters` to add new metadata columns

### Phase 1 — Code
1. Create `src/canon/services/narrative_v2/` package:
   - `stage1_fact_sheet.py`
   - `stage2_atomic_events.py`
   - `stage3_cluster.py` + `stage3b_archetype.py`
   - `stage4_render.py`
   - `stage5_post_process.py`
   - `pipeline.py` — orchestrator
2. Keep V1 `narrative_synthesizer.py` in place temporarily for rollback
3. Add pipeline version flag to routes

### Phase 2 — Seed archetype_registry
Bootstrap from existing `entity_equivalences` + hand-curated core archetypes:
- The Primordial Void, The Primordial Waters, The First Creator, The Sun God, The Divine Craftsman, The Mother of All Living, The Mother of Chaos, The Shining Ones, The Flood Bringer, The First Man, The First Woman, The Trickster, The Sky Father, The Earth Mother, The Champion.

### Phase 3 — Rebuild
1. Wipe `story_chapters`, `culture_event_skeletons`, `culture_narratives` for target epoch
2. Run V2 pipeline epoch-by-epoch starting Creation
3. Verify Chapter 1 manually before proceeding
4. Rebuild all chapters

### Phase 4 — Cutover
1. Switch frontend to read only V2 data
2. Drop deprecated tables after 1 week stable

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Rule matcher too strict → events don't cluster | Embedding cosine as second-chance pass; logs every decision for tuning |
| Rule matcher too loose → wrong events merge | Hard constraint on `verb_family`; retention requires age or convergence |
| Name substitution false positives ("Isis" the name vs. modern company) | Only substitute names in `also_known_as` of chapters actually used |
| Possessive / plural edge cases ("Enki's" "Eddas") | Word-boundary regex with `'s` affix handling; test suite |
| Stage 4 ignores provided archetype and invents names | Stage 5 validator rejects + Stage 4 retries; ban list in prompt |
| LLM picks a different archetype for the same concept in Chapter 7 | Archetype registry lookup is deterministic; LLM doesn't choose in V2 |
| Embedding model drift | Pin model version in `action_embedding` column; migration-aware |
| Over-aggressive retention drops important cultural details | Vivid details from dropped singletons still attach to nearest kept cluster as "variant_detail" |

---

## 14. Success Criteria

A chapter is considered V2-successful when:

1. ✅ Zero "according to / in one tradition / elsewhere" framing
2. ✅ Zero raw culture-specific deity names in prose (validator passes)
3. ✅ Every archetype used in Ch 4 that also appeared in Ch 1 has the same name
4. ✅ Every event told exactly once (no parallel versions within chapter)
5. ✅ Sumerian/Mesopotamian details form narrative backbone (check canonical_verb source)
6. ✅ Clicking annotated entity shows all merged deities across cultures
7. ✅ Chapter does not retell prior chapter events
8. ✅ Culture dropdown shows rich prose history per culture
9. ✅ Word count within 1500-2500
10. ✅ 10-15 archetype annotations per chapter

---

## 15. Build Order

1. Schema migration (Alembic)
2. `archetype_registry` seed script with core archetypes
3. Stage 1 culture fact sheet (adapt existing prompt to add `fact_sheet` output)
4. Stage 2 atomic event extractor with embeddings
5. Stage 3 clusterer (pure code, unit-testable)
6. Stage 3B archetype resolver
7. Stage 4 renderer with new prompt
8. Stage 5 post-processor + validator
9. Pipeline orchestrator
10. Route updates
11. Frontend adjustments (none expected — same response shape)
12. Full rebuild of existing chapters
13. Manual verification of Ch 1 and Ch 4
