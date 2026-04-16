"""Stage 3 — deterministic event clustering.

No LLM. Pure Python. Takes atomic events from all cultures for one chapter
and produces merged event clusters.

Algorithm:
  1. Hard constraint: events can only cluster within the same verb_family.
  2. Within a family, build candidate clusters via rule matching:
       - shared outcome keyword OR shared material OR actor equivalence
  3. Confirm/split candidates with embedding cosine similarity >= 0.78.
  4. Apply retention rule: keep clusters where
       retention_score = 10 / age_rank_oldest + (culture_count - 1) * 5  >= 5
  5. Order clusters by chapter narrative logic.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.canon.services.narrative_v2.shared import (
    CULTURE_AGE_ORDER,
    EMBEDDING_COSINE_THRESHOLD,
    RETENTION_THRESHOLD,
    retention_score,
)

logger = logging.getLogger(__name__)


@dataclass
class AtomicEventRow:
    """Normalised atomic event — what Stage 3 operates on."""

    id: uuid.UUID
    culture_key: str
    seq: int
    actors: list[str]
    verb: str
    verb_family: str
    objects: list[str]
    materials: list[str]
    place: str | None
    outcome: str
    outcome_keywords: list[str]
    quoted_phrase: str | None
    source_ref: str | None
    action_embedding: list[float] | None


@dataclass
class Cluster:
    cluster_key: str
    verb_family: str
    members: list[AtomicEventRow] = field(default_factory=list)

    @property
    def cultures(self) -> set[str]:
        return {m.culture_key for m in self.members}

    @property
    def age_rank_oldest(self) -> int:
        return min(
            CULTURE_AGE_ORDER.get(m.culture_key, 99) for m in self.members
        )

    @property
    def retention(self) -> float:
        return retention_score(self.age_rank_oldest, len(self.cultures))

    def oldest_member(self) -> AtomicEventRow:
        return min(
            self.members,
            key=lambda m: (CULTURE_AGE_ORDER.get(m.culture_key, 99), m.seq),
        )


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------


def _normalize_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# Stopwords to ignore when building keyword sets from free-text outcomes.
_STOPWORDS: set[str] = {
    "the", "and", "for", "but", "with", "from", "into", "onto", "upon",
    "that", "this", "they", "them", "then", "than", "been", "being",
    "are", "was", "were", "has", "had", "have", "who", "what", "why",
    "gods", "god",  # too generic for matching
    "comes", "came", "come", "gone", "goes", "went", "get", "got",
    "one", "two", "three", "first", "second",
    "not", "out", "over", "under", "all", "any",
    "you", "your", "his", "her", "him", "she", "its",
}


def _keyword_set(items: list[str]) -> set[str]:
    result: set[str] = set()
    for item in items or []:
        for tok in re.findall(r"[a-z]+", item.lower()):
            if len(tok) >= 4 and tok not in _STOPWORDS:
                result.add(tok)
    return result


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _is_usable_embedding(emb: list[float] | None) -> bool:
    """True if the embedding has non-trivial magnitude.

    Zero-vectors come from a missing OpenAI API key or embed failure. Treat
    them as 'no embedding' so rule-based clustering still works.
    """
    if not emb:
        return False
    mag_sq = sum(x * x for x in emb)
    return mag_sq > 1e-6


def _actor_overlap(
    a: list[str], b: list[str], equivalences: dict[str, set[str]]
) -> bool:
    """Do the two actor lists share an actor (via equivalence map)?"""
    a_keys = {_normalize_token(x) for x in a if x}
    b_keys = {_normalize_token(x) for x in b if x}
    if a_keys & b_keys:
        return True
    # Try to resolve through equivalence groups (each actor -> set of equivalent names)
    for a_name in a_keys:
        equiv = equivalences.get(a_name)
        if equiv and equiv & b_keys:
            return True
    return False


# ---------------------------------------------------------------------------
# Rule-based candidate clustering
# ---------------------------------------------------------------------------


def _events_should_cluster(
    e1: AtomicEventRow,
    e2: AtomicEventRow,
    equivalences: dict[str, set[str]],
) -> bool:
    """Rule matcher: should e1 and e2 be in the same cluster?

    Must share verb_family (caller guarantees this), plus at least one of:
      - actor equivalence
      - outcome keyword Jaccard >= 0.5
      - material Jaccard >= 0.3
    """
    if e1.verb_family != e2.verb_family:
        return False

    if _actor_overlap(e1.actors, e2.actors, equivalences):
        return True

    # Strong keyword match — compact outcome_keywords lists from Stage 2.
    # If they share ANY non-trivial keyword, cluster (subject to embedding
    # confirmation later).
    kw_a = _keyword_set(e1.outcome_keywords)
    kw_b = _keyword_set(e2.outcome_keywords)
    if kw_a & kw_b:
        return True

    # Weaker keyword match — free-text outcome. Require higher Jaccard.
    out_a = _keyword_set(e1.outcome_keywords + [e1.outcome])
    out_b = _keyword_set(e2.outcome_keywords + [e2.outcome])
    if _jaccard(out_a, out_b) >= 0.34:
        return True

    # Materials or objects overlap (e.g. both shape humans from clay).
    mat_a = _keyword_set(e1.materials + e1.objects)
    mat_b = _keyword_set(e2.materials + e2.objects)
    if mat_a & mat_b:
        return True

    return False


def _union_find_cluster(
    events: list[AtomicEventRow],
    equivalences: dict[str, set[str]],
) -> list[list[AtomicEventRow]]:
    """Group events using union-find over pairwise rule matches."""

    n = len(events)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if _events_should_cluster(events[i], events[j], equivalences):
                union(i, j)

    buckets: dict[int, list[AtomicEventRow]] = defaultdict(list)
    for i, ev in enumerate(events):
        buckets[find(i)].append(ev)
    return list(buckets.values())


# ---------------------------------------------------------------------------
# Embedding confirmation/split
# ---------------------------------------------------------------------------


def _split_by_embeddings(
    members: list[AtomicEventRow],
    threshold: float = EMBEDDING_COSINE_THRESHOLD,
) -> list[list[AtomicEventRow]]:
    """Split a candidate cluster into sub-clusters if embeddings diverge.

    Iteratively pick the centroid and keep only members above threshold.
    Kicked-out members form new candidate clusters.
    """
    # If nobody has a usable embedding, trust the rule-based grouping.
    if not any(_is_usable_embedding(m.action_embedding) for m in members):
        return [members]

    remaining = list(members)
    groups: list[list[AtomicEventRow]] = []

    while remaining:
        # Pick the oldest-tradition member with a usable embedding as anchor
        with_emb = [m for m in remaining if _is_usable_embedding(m.action_embedding)]
        if not with_emb:
            groups.append(remaining)
            return groups
        anchor = min(
            with_emb,
            key=lambda m: (CULTURE_AGE_ORDER.get(m.culture_key, 99), m.seq),
        )

        group = [anchor]
        rest = []
        for m in remaining:
            if m is anchor:
                continue
            if not _is_usable_embedding(m.action_embedding):
                # Unknown embedding: trust rule match, keep with anchor
                group.append(m)
                continue
            sim = _cosine(anchor.action_embedding, m.action_embedding)
            if sim >= threshold:
                group.append(m)
            else:
                rest.append(m)
        groups.append(group)
        remaining = rest

    return groups


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

# Canonical narrative order for creation-theme clusters. Clusters whose verb
# family falls into one of these buckets are sorted by bucket index.
_THEME_KEYWORD_ORDER: list[tuple[str, list[str]]] = [
    ("void", ["void", "chaos", "darkness", "deep", "abyss", "primordial", "formless"]),
    ("stir", ["stir", "awaken", "emerge", "arise", "begin", "first"]),
    ("separate", ["separate", "split", "divide", "part", "lift", "cleave", "firmament"]),
    ("celestial", ["sun", "moon", "stars", "light", "day", "night", "dawn"]),
    ("birth_gods", ["beget", "born", "offspring", "children", "generate", "god"]),
    ("shape_world", ["land", "mountain", "river", "body", "flesh", "earth shape"]),
    ("humanity", ["human", "man", "woman", "people", "clay", "breath", "dust"]),
    ("civilization", ["city", "temple", "king", "law", "agriculture", "craft"]),
    ("flood", ["flood", "deluge", "drown", "ark", "boat"]),
]


def _theme_index(cluster: Cluster) -> int:
    """Return sort index in canonical creation order; unknown = 100."""
    blob = " ".join(
        [
            cluster.oldest_member().verb,
            cluster.oldest_member().outcome,
            " ".join(cluster.oldest_member().outcome_keywords),
            " ".join(cluster.oldest_member().materials or []),
        ]
    ).lower()
    for i, (_, keys) in enumerate(_THEME_KEYWORD_ORDER):
        if any(k in blob for k in keys):
            return i
    return 100


def _cluster_key_from_oldest(cluster: Cluster) -> str:
    """Stable key derived from the oldest member's verb + first outcome keyword."""
    oldest = cluster.oldest_member()
    verb = _normalize_token(oldest.verb) or "event"
    kw = oldest.outcome_keywords[0] if oldest.outcome_keywords else ""
    kw = _normalize_token(kw) or _normalize_token(oldest.outcome.split()[0] if oldest.outcome else "x")
    return f"{verb}_{kw}"[:80]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cluster_events(
    events: list[AtomicEventRow],
    equivalences: dict[str, set[str]] | None = None,
) -> list[Cluster]:
    """Cluster atomic events and return a list of retained clusters in order.

    `equivalences` maps normalized actor names to sets of equivalent normalized
    names (e.g. {"enki": {"enki", "ea", "khnum"}}). Missing entries are fine.
    """

    equivalences = equivalences or {}

    # Step 1: group by verb_family
    by_family: dict[str, list[AtomicEventRow]] = defaultdict(list)
    for ev in events:
        by_family[ev.verb_family].append(ev)

    # Step 2-3: rule-based candidate cluster, then embedding split
    all_clusters: list[Cluster] = []
    for family, family_events in by_family.items():
        candidates = _union_find_cluster(family_events, equivalences)
        for cand in candidates:
            subs = _split_by_embeddings(cand)
            for sub in subs:
                c = Cluster(cluster_key="", verb_family=family, members=sub)
                c.cluster_key = _cluster_key_from_oldest(c)
                all_clusters.append(c)

    # Step 4: apply retention rule
    retained = [c for c in all_clusters if c.retention >= RETENTION_THRESHOLD]

    dropped = len(all_clusters) - len(retained)
    if dropped:
        logger.info(
            "Stage 3: retained %d / %d clusters (dropped %d under retention threshold)",
            len(retained),
            len(all_clusters),
            dropped,
        )

    # Step 5: order clusters by theme index, then by oldest member's seq
    retained.sort(
        key=lambda c: (
            _theme_index(c),
            CULTURE_AGE_ORDER.get(c.oldest_member().culture_key, 99),
            c.oldest_member().seq,
        )
    )
    return retained


def cluster_to_row(cluster: Cluster, seq: int) -> dict[str, Any]:
    """Serialize a Cluster into a DB-ready dict matching EventCluster columns."""

    oldest = cluster.oldest_member()

    # Aggregate materials across all members (preserve order, unique)
    seen_materials: set[str] = set()
    materials: list[str] = []
    for m in cluster.members:
        for mat in m.materials or []:
            if mat.lower() not in seen_materials:
                seen_materials.add(mat.lower())
                materials.append(mat)

    # Vivid details: outcome-unique phrases per culture
    vivid: list[dict[str, str]] = []
    seen_vivid: set[str] = set()
    for m in sorted(
        cluster.members, key=lambda x: CULTURE_AGE_ORDER.get(x.culture_key, 99)
    ):
        for d in [m.outcome, m.quoted_phrase or ""]:
            if not d:
                continue
            key = d.strip().lower()
            if key in seen_vivid:
                continue
            seen_vivid.add(key)
            vivid.append({"detail": d.strip(), "culture": m.culture_key})

    # Source quotes
    quotes: list[dict[str, str]] = []
    for m in cluster.members:
        if m.quoted_phrase:
            quotes.append(
                {
                    "quote": m.quoted_phrase,
                    "culture": m.culture_key,
                    "source_ref": m.source_ref or "",
                }
            )

    # Contributing cultures -> actor list (preserving original spellings)
    contrib: dict[str, list[str]] = defaultdict(list)
    for m in cluster.members:
        for a in m.actors:
            if a and a not in contrib[m.culture_key]:
                contrib[m.culture_key].append(a)

    return {
        "cluster_key": cluster.cluster_key,
        "seq": seq,
        "primary_archetype_name": "",  # filled in Stage 3B
        "contributing_event_ids": [m.id for m in cluster.members],
        "contributing_cultures": dict(contrib),
        "canonical_verb": oldest.verb,
        "canonical_outcome": oldest.outcome,
        "verb_family": cluster.verb_family,
        "materials": materials,
        "vivid_details": vivid,
        "source_quotes": quotes,
        "age_rank_of_oldest": cluster.age_rank_oldest,
        "retention_score": cluster.retention,
    }
