"""Merge logic for canonical entities. Implements 4 merge levels:
  Level 1 — Alias: same entity, different spelling (100+ cross-cultural entries)
  Level 2 — Motif cluster: same role, different identity
  Level 3 — Candidate equivalence: LLM-assisted + temporal overlap
  Level 4 — Canon merge: only when final_score threshold met

Implements Law 8 (Entity Convergence Law): entities across cultures may be merged
only when role similarity, action similarity, context alignment, and pattern
repetition all align beyond coincidence.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_score import CanonScore
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.motif import MotifAssignment
from src.canon.models.enums import CanonicalType

logger = logging.getLogger(__name__)

# ── Cross-Cultural Alias Dictionary ──────────────────────────────────────────
# Canonical form -> list of known equivalences across traditions.
# Each key is the primary identity; variants are spelling or cross-cultural names.
ALIAS_VARIANTS = {
    # Mesopotamian deities
    "inanna": ["ishtar", "astarte", "ashtoreth", "anat"],
    "enlil": ["ellil"],
    "enki": ["ea"],
    "utu": ["shamash"],
    "nanna": ["sin", "suen"],
    "dumuzi": ["tammuz"],
    "ereshkigal": ["allatu"],
    "ninhursag": ["ninmah", "nintu", "ki", "belet-ili", "aruru"],
    "marduk": ["bel", "asalluhi"],
    "tiamat": ["tehom", "leviathan"],
    "anu": ["an"],
    "nergal": ["erra"],
    "nabu": ["nebo"],
    "ninurta": ["ningirsu"],
    "ningal": ["nikkal"],
    "adad": ["ishkur", "hadad", "baal hadad"],
    "dagan": ["dagon"],

    # Flood heroes
    "ziusudra": ["utnapishtim", "atrahasis", "xisuthros"],
    "noah": ["nuh"],
    "manu": ["satyavrata"],
    "deucalion": ["pyrrha"],
    "nu wa": ["nuwa"],

    # Creation / Sky beings
    "anunnaki": ["anunna", "elohim"],
    "igigi": ["watchers", "irin"],
    "apkallu": ["seven sages", "abgal"],
    "nephilim": ["giants", "gibborim"],
    "titans": ["titanes"],

    # Egyptian deities
    "ra": ["re", "atum-ra", "amun-ra"],
    "osiris": ["wesir", "usir"],
    "isis": ["aset", "iset"],
    "horus": ["hor", "heru"],
    "set": ["seth", "sutekh"],
    "thoth": ["djehuty", "tehuti"],
    "ptah": ["pteh"],
    "hathor": ["het-heru"],
    "anubis": ["anpu", "inpu"],
    "sekhmet": ["sachmet"],
    "khnum": ["khnemu"],
    "nut": ["nuit"],
    "geb": ["keb", "seb"],
    "shu": ["su"],
    "tefnut": ["tefenet"],
    "maat": ["ma'at"],
    "sobek": ["suchos"],

    # Hebrew / Canaanite
    "yahweh": ["yhwh", "jehovah"],
    "el": ["el elyon", "el shaddai"],
    "baal": ["bel", "hadad"],
    "asherah": ["athirat"],
    "mot": ["maweth"],
    "yam": ["yamm", "nahar"],
    "adam": ["adamu"],
    "eve": ["hawwa", "havah"],
    "enoch": ["metatron"],
    "abraham": ["abram", "ibrahim"],
    "moses": ["musa"],

    # Greek deities
    "zeus": ["jupiter", "jove"],
    "poseidon": ["neptune"],
    "hades": ["pluto", "dis pater"],
    "athena": ["minerva"],
    "apollo": ["apollon", "phoebus"],
    "artemis": ["diana"],
    "ares": ["mars"],
    "aphrodite": ["venus"],
    "hermes": ["mercury", "thoth"],
    "hephaestus": ["vulcan"],
    "demeter": ["ceres"],
    "dionysus": ["bacchus"],
    "persephone": ["proserpina", "kore"],
    "prometheus": ["prometheia"],
    "kronos": ["cronus", "saturn"],
    "uranus": ["ouranos"],
    "gaia": ["ge", "terra"],

    # Hindu / Vedic
    "indra": ["sakra", "vajrapani"],
    "varuna": ["mitra-varuna"],
    "agni": ["agneya"],
    "brahma": ["prajapati"],
    "vishnu": ["narayana", "hari"],
    "shiva": ["rudra", "mahadeva", "nataraja"],
    "saraswati": ["sarasvati", "bharati"],
    "lakshmi": ["shri", "sri"],
    "parvati": ["uma", "durga", "kali"],
    "ganesha": ["ganapati", "vinayaka"],
    "yama": ["dharmaraja"],

    # Chinese / East Asian
    "pangu": ["pan gu"],
    "fuxi": ["fu xi", "fu hsi"],
    "shennong": ["shen nong", "divine farmer"],
    "huangdi": ["huang di", "yellow emperor"],
    "yu the great": ["da yu", "emperor yu"],
    "xiwangmu": ["xi wangmu", "queen mother of the west"],
    "jade emperor": ["yu huang", "yuhuang dadi"],

    # Mesoamerican
    "quetzalcoatl": ["kukulkan", "q'uq'umatz", "ehecatl"],
    "tezcatlipoca": ["smoking mirror"],
    "tlaloc": ["chaac", "chac"],
    "huitzilopochtli": ["hummingbird of the south"],
    "itzamna": ["itzamnaaj"],

    # South American
    "viracocha": ["wiraqocha", "con tici viracocha"],
    "inti": ["inti raymi"],
    "pachamama": ["mama pacha"],

    # Norse
    "odin": ["wodan", "woden", "wotan"],
    "thor": ["donar", "thunor"],
    "freya": ["freyja", "frigg"],
    "loki": ["loptr"],
    "tyr": ["tiwaz"],
    "ymir": ["aurgelmir"],

    # Places
    "ur": ["ur iii"],
    "eridu": ["eridug"],
    "nippur": ["nibru"],
    "uruk": ["unug", "warka"],
    "babylon": ["babilu", "babel", "bab-ilim"],
    "sumer": ["shumer", "ki-en-gir"],
    "eden": ["gan eden", "dilmun", "paradise"],
    "mount meru": ["sumeru", "su-meru"],
    "mount olympus": ["olympos"],
    "mount sinai": ["horeb", "jebel musa"],
    "underworld": ["kur", "irkalla", "sheol", "duat", "hades", "xibalba", "naraka", "helheim"],

    # Heroic figures
    "gilgamesh": ["bilgames"],
    "heracles": ["hercules"],
    "achilles": ["achilleus"],
    "aeneas": ["aineas"],
    "rama": ["ramachandra"],
    "arjuna": ["partha"],

    # ── Cross-Cultural Creator/Sky Deity Equivalences ──
    # These connect entities across different cultural traditions
    # that serve the same archetypal role

    # Creator/wisdom god across cultures
    "enki": ["ea", "ptah", "thoth", "hermes"],
    # Sky father / supreme deity
    "anu": ["an", "el", "el elyon"],
    # Great flood survivor
    "ziusudra": ["utnapishtim", "atrahasis", "xisuthros", "noah", "nuh", "manu", "deucalion"],
    # Sky/storm god
    "enlil": ["ellil", "zeus", "jupiter", "indra"],
    # Mother goddess / earth mother
    "ninhursag": ["ninmah", "nintu", "ki", "belet-ili", "aruru", "gaia", "pachamama"],
    # Love/fertility goddess
    "inanna": ["ishtar", "astarte", "ashtoreth", "anat", "aphrodite", "venus", "hathor", "freya"],
    # Sun deity
    "utu": ["shamash", "ra", "surya", "apollo", "sol"],
    # Death/underworld deity
    "ereshkigal": ["allatu", "hel", "persephone"],
    # War deity
    "nergal": ["erra", "ares", "mars"],
    # Chaos serpent / primordial sea
    "tiamat": ["tehom", "leviathan", "apep", "jormungandr", "vritra"],
    # Celestial watchers / divine council
    "anunnaki": ["anunna", "elohim", "deva", "netjeru"],
    # Fallen/rebel divine beings
    "igigi": ["watchers", "irin", "nephilim", "titans", "asuras"],
    # Trickster/culture hero
    "prometheus": ["prometheia", "loki", "coyote", "maui", "anansi"],
    # Feathered/winged serpent deity
    "quetzalcoatl": ["kukulkan", "q'uq'umatz", "ehecatl", "viracocha"],
}

CANON_MERGE_THRESHOLD = 0.7


def _normalize(name: str) -> str:
    return name.strip().lower()


def _build_alias_map() -> dict[str, str]:
    """Build a reverse map: variant -> canonical form."""
    alias_map = {}
    for canonical, variants in ALIAS_VARIANTS.items():
        alias_map[canonical] = canonical
        for v in variants:
            alias_map[v] = canonical
    return alias_map


class MergeService:
    def __init__(self):
        self._alias_map = _build_alias_map()

    def level1_alias_group(self, names: list[str]) -> dict[str, list[str]]:
        """Group names by alias equivalence. Returns canonical_form -> [original_names]."""
        groups: dict[str, list[str]] = defaultdict(list)
        for name in names:
            norm = _normalize(name)
            canonical_form = self._alias_map.get(norm, norm)
            groups[canonical_form].append(name)
        return dict(groups)

    async def level2_motif_cluster(
        self, session: AsyncSession, entity_type: CanonicalType
    ) -> list[list[uuid.UUID]]:
        """Group entities that share the same motifs (same role, not same entity)."""
        q = select(MotifAssignment).where(MotifAssignment.target_type == entity_type)
        assignments = (await session.execute(q)).scalars().all()

        motif_to_entities: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for a in assignments:
            motif_to_entities[a.motif_id].append(a.target_id)

        clusters = []
        for motif_id, entity_ids in motif_to_entities.items():
            if len(entity_ids) > 1:
                clusters.append(entity_ids)
        return clusters

    def level3_temporal_overlap(
        self,
        candidates: list[dict],
        overlap_threshold: float = 0.5,
    ) -> list[tuple[dict, dict]]:
        """Find candidate equivalences based on temporal overlap.
        Each candidate: {"id": uuid, "name": str, "time_start": int|None, "time_end": int|None}
        """
        pairs = []
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                if a["time_start"] is None or b["time_start"] is None:
                    continue
                if a["time_end"] is None or b["time_end"] is None:
                    continue

                overlap_start = max(a["time_start"], b["time_start"])
                overlap_end = min(a["time_end"], b["time_end"])
                if overlap_start >= overlap_end:
                    continue

                overlap_len = overlap_end - overlap_start
                span_a = a["time_end"] - a["time_start"]
                span_b = b["time_end"] - b["time_start"]
                max_span = max(span_a, span_b, 1)

                if overlap_len / max_span >= overlap_threshold:
                    pairs.append((a, b))
        return pairs

    async def level4_canon_merge(
        self,
        session: AsyncSession,
        entity_type: CanonicalType,
        entity_a_id: uuid.UUID,
        entity_b_id: uuid.UUID,
    ) -> bool:
        """Merge entity_b into entity_a if both meet the score threshold.
        Creates a new version of entity_a, marks entity_b as not current.
        Returns True if merge happened.
        """
        score_a_q = select(CanonScore).where(
            CanonScore.canonical_type == entity_type,
            CanonScore.canonical_id == entity_a_id,
        )
        score_b_q = select(CanonScore).where(
            CanonScore.canonical_type == entity_type,
            CanonScore.canonical_id == entity_b_id,
        )
        score_a = (await session.execute(score_a_q)).scalar_one_or_none()
        score_b = (await session.execute(score_b_q)).scalar_one_or_none()

        if not score_a or not score_b:
            logger.info("Cannot merge: missing scores for %s or %s", entity_a_id, entity_b_id)
            return False

        avg_score = (score_a.final_score + score_b.final_score) / 2
        if avg_score < CANON_MERGE_THRESHOLD:
            logger.info(
                "Score too low for merge: %.2f (threshold %.2f)", avg_score, CANON_MERGE_THRESHOLD
            )
            return False

        await session.execute(
            update(CanonSupportLink)
            .where(
                CanonSupportLink.canonical_type == entity_type,
                CanonSupportLink.canonical_id == entity_b_id,
            )
            .values(canonical_id=entity_a_id)
        )

        await session.execute(
            update(CanonDependency)
            .where(CanonDependency.child_type == entity_type, CanonDependency.child_id == entity_b_id)
            .values(child_id=entity_a_id)
        )

        await session.execute(
            update(MotifAssignment)
            .where(MotifAssignment.target_type == entity_type, MotifAssignment.target_id == entity_b_id)
            .values(target_id=entity_a_id)
        )

        if entity_type == CanonicalType.ACTOR:
            entity_b = await session.get(CanonicalActor, entity_b_id)
            if entity_b:
                entity_b.is_current = False
        elif entity_type == CanonicalType.EVENT:
            entity_b = await session.get(CanonicalEvent, entity_b_id)
            if entity_b:
                entity_b.is_current = False
        elif entity_type == CanonicalType.PLACE:
            entity_b = await session.get(CanonicalPlace, entity_b_id)
            if entity_b:
                entity_b.is_current = False

        await session.flush()
        logger.info("Merged %s %s into %s", entity_type.value, entity_b_id, entity_a_id)
        return True

    async def _llm_entity_resolution(
        self, entity_a_name: str, entity_a_summary: str,
        entity_b_name: str, entity_b_summary: str,
    ) -> dict:
        """Use DeepSeek to evaluate whether two entities should be merged (Law 8).
        Checks role similarity, action similarity, context alignment, pattern repetition."""
        if not settings.deepseek_api_key:
            return {"should_merge": False, "confidence": 0.0, "reasoning": "No API key"}

        prompt = f"""Evaluate whether these two entities from different ancient traditions
are describing the same being, event, or place. Apply strict criteria:

Entity A: {entity_a_name}
Summary: {entity_a_summary or 'No summary'}

Entity B: {entity_b_name}
Summary: {entity_b_summary or 'No summary'}

Check ALL four criteria (ALL must be satisfied for a merge):
1. Role similarity — do they serve the same function (creator, teacher, destroyer, etc.)?
2. Action similarity — do they perform the same types of actions/events?
3. Context alignment — do they appear in the same narrative phase (pre-flood, post-flood, creation, etc.)?
4. Pattern repetition — does this equivalence appear across multiple independent sources?

Return JSON: {{"should_merge": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation",
"role_match": true/false, "action_match": true/false, "context_match": true/false, "pattern_match": true/false}}"""

        try:
            url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": settings.deepseek_model,
                "messages": [
                    {"role": "system", "content": "You evaluate cross-cultural entity equivalences in ancient mythology and history. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 512,
            }
            headers = {
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            raw = data["choices"][0]["message"]["content"]
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            logger.exception("LLM entity resolution failed for %s / %s", entity_a_name, entity_b_name)

        return {"should_merge": False, "confidence": 0.0, "reasoning": "LLM call failed"}

    async def run_alias_merges(self, session: AsyncSession) -> dict:
        """Run Level 1 alias merges across all entity types."""
        merged_count = 0

        for model_cls, entity_type in [
            (CanonicalActor, CanonicalType.ACTOR),
            (CanonicalEvent, CanonicalType.EVENT),
            (CanonicalPlace, CanonicalType.PLACE),
        ]:
            q = select(model_cls).where(model_cls.is_current.is_(True))
            entities = (await session.execute(q)).scalars().all()

            name_to_entities: dict[str, list] = defaultdict(list)
            for e in entities:
                norm = _normalize(e.canonical_name)
                canonical_form = self._alias_map.get(norm, norm)
                name_to_entities[canonical_form].append(e)

            for canonical_form, group in name_to_entities.items():
                if len(group) <= 1:
                    continue

                primary = max(group, key=lambda e: e.merge_confidence or 0)
                for other in group:
                    if other.id == primary.id:
                        continue
                    merged = await self.level4_canon_merge(
                        session, entity_type, primary.id, other.id
                    )
                    if merged:
                        merged_count += 1

        await session.flush()
        return {"alias_merges": merged_count}

    async def run_alias_equivalences(self, session: AsyncSession) -> dict:
        """Populate entity_equivalences from the alias dictionary without requiring
        canon scores. This creates soft links (equivalences) rather than hard merges,
        preserving both entities but marking them as equivalent for the narrative.
        """
        from sqlalchemy import text as sa_text
        equivalences_created = 0

        for model_cls, entity_type in [
            (CanonicalActor, CanonicalType.ACTOR),
            (CanonicalEvent, CanonicalType.EVENT),
            (CanonicalPlace, CanonicalType.PLACE),
        ]:
            q = select(model_cls.id, model_cls.canonical_name).where(
                model_cls.is_current.is_(True)
            )
            entities = (await session.execute(q)).all()

            name_to_entities: dict[str, list[tuple]] = defaultdict(list)
            for eid, name in entities:
                norm = _normalize(name)
                canonical_form = self._alias_map.get(norm, norm)
                name_to_entities[canonical_form].append((eid, name))

            for canonical_form, group in name_to_entities.items():
                if len(group) <= 1:
                    continue

                primary = group[0]
                for other in group[1:]:
                    if other[0] == primary[0]:
                        continue
                    try:
                        await session.execute(sa_text("""
                            INSERT INTO entity_equivalences
                                (id, primary_entity_type, primary_entity_id,
                                 equivalent_entity_type, equivalent_entity_id,
                                 merge_basis, confidence, evidence_json)
                            VALUES (gen_random_uuid(), :pt, :pid, :et, :eid,
                                    'alias_dictionary', 0.9, :evidence)
                            ON CONFLICT DO NOTHING
                        """), {
                            "pt": entity_type.value, "pid": primary[0],
                            "et": entity_type.value, "eid": other[0],
                            "conf": 0.9,
                            "evidence": json.dumps({
                                "should_merge": True,
                                "confidence": 0.9,
                                "reasoning": f"Alias match: '{primary[1]}' and '{other[1]}' map to canonical form '{canonical_form}'",
                                "role_match": True,
                                "action_match": True,
                                "context_match": True,
                                "pattern_match": True,
                            }),
                        })
                        equivalences_created += 1
                    except Exception:
                        logger.warning(
                            "Failed to create equivalence: %s ↔ %s", primary[1], other[1],
                            exc_info=True
                        )

        await session.flush()
        return {"alias_equivalences_created": equivalences_created}

    async def run_llm_entity_resolution(self, session: AsyncSession, max_pairs: int = 50) -> dict:
        """Run LLM-assisted entity resolution for motif-clustered candidates.
        Implements Law 8 with the 4-criteria check."""
        resolved = 0
        merged = 0

        for entity_type, model_cls in [
            (CanonicalType.ACTOR, CanonicalActor),
            (CanonicalType.EVENT, CanonicalEvent),
        ]:
            clusters = await self.level2_motif_cluster(session, entity_type)
            pairs_checked = 0

            for cluster in clusters:
                if pairs_checked >= max_pairs:
                    break

                entities = []
                for eid in cluster:
                    e = await session.get(model_cls, eid)
                    if e and e.is_current:
                        entities.append(e)

                for i, a in enumerate(entities):
                    for b in entities[i + 1:]:
                        if pairs_checked >= max_pairs:
                            break
                        if _normalize(a.canonical_name) == _normalize(b.canonical_name):
                            continue

                        result = await self._llm_entity_resolution(
                            a.canonical_name, a.summary or "",
                            b.canonical_name, b.summary or "",
                        )
                        pairs_checked += 1
                        resolved += 1

                        if result.get("should_merge") and result.get("confidence", 0) >= 0.7:
                            from sqlalchemy import text
                            await session.execute(text("""
                                INSERT INTO entity_equivalences
                                    (id, primary_entity_type, primary_entity_id,
                                     equivalent_entity_type, equivalent_entity_id,
                                     merge_basis, confidence, evidence_json)
                                VALUES (gen_random_uuid(), :pt, :pid, :et, :eid,
                                        'llm_resolution', :conf, :evidence)
                                ON CONFLICT DO NOTHING
                            """), {
                                "pt": entity_type.value, "pid": a.id,
                                "et": entity_type.value, "eid": b.id,
                                "conf": result["confidence"],
                                "evidence": json.dumps(result),
                            })
                            merged += 1
                            logger.info(
                                "LLM resolved equivalence: %s ↔ %s (%.2f)",
                                a.canonical_name, b.canonical_name, result["confidence"]
                            )

        await session.flush()
        return {"pairs_evaluated": resolved, "equivalences_found": merged}
