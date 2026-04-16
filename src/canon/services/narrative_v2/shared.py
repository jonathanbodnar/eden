"""Shared constants for V2 pipeline — verb families, laws, culture ranks."""

from __future__ import annotations


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


# Fixed verb vocabulary. Every atomic event must be classified into one of
# these families. Two events cannot cluster unless they share a family.
VERB_FAMILIES: dict[str, list[str]] = {
    "MAKE": [
        "create", "shape", "mold", "fashion", "form", "sculpt", "carve",
        "weave", "produce", "beget", "build", "construct", "craft",
        "generate", "bring forth", "bear", "father",
    ],
    "DESTROY": [
        "slay", "kill", "rend", "flood", "burn", "shatter", "devour",
        "crush", "drown", "swallow", "consume", "annihilate",
    ],
    "SEPARATE": [
        "split", "divide", "lift", "raise", "cleave", "part", "sever",
        "break apart", "tear apart",
    ],
    "JOIN": [
        "unite", "marry", "combine", "bind", "join", "merge", "couple",
    ],
    "SPEAK": [
        "declare", "utter", "command", "name", "curse", "bless", "proclaim",
        "speak", "say", "call", "decree",
    ],
    "MOVE": [
        "descend", "ascend", "travel", "flee", "return", "enter", "emerge",
        "rise", "depart", "approach", "go",
    ],
    "GIVE": [
        "bestow", "grant", "offer", "sacrifice", "give", "hand over",
    ],
    "TAKE": [
        "seize", "steal", "claim", "receive", "take", "capture",
    ],
    "CONTEND": [
        "battle", "wrestle", "defeat", "imprison", "fight", "challenge",
        "oppose", "bind in chains",
    ],
    "TRANSFORM": [
        "change", "become", "transfigure", "turn into", "transform",
    ],
}

# Reverse lookup: verb -> family (lowercased)
_VERB_TO_FAMILY: dict[str, str] = {}
for _family, _verbs in VERB_FAMILIES.items():
    for _v in _verbs:
        _VERB_TO_FAMILY[_v.lower()] = _family


def classify_verb(verb: str) -> str:
    """Return the family for a verb, falling back to MAKE for unknowns."""
    if not verb:
        return "MAKE"
    v = verb.lower().strip()
    if v in _VERB_TO_FAMILY:
        return _VERB_TO_FAMILY[v]
    # Substring match for inflected forms (shapes, molded, etc.)
    for known, family in _VERB_TO_FAMILY.items():
        if known in v or v in known:
            return family
    return "MAKE"


# Culture age rank. Lower = older = higher narrative weight. Used by Stage 3
# retention formula and canonical-verb selection.
CULTURE_AGE_ORDER: dict[str, int] = {
    "sumerian": 1,
    "mesopotamian": 2,
    "egyptian": 3,
    "hittite": 4,
    "canaanite": 5,
    "vedic": 6,
    "chinese": 7,
    "greek": 8,
    "hebrew": 9,
    "zoroastrian": 10,
    "minoan": 11,
    "roman": 12,
    "mesoamerican": 13,
    "norse": 14,
    "celtic": 15,
    "polynesian": 16,
    "aboriginal": 17,
    "ainu": 18,
    "african": 19,
}

CULTURE_LABELS: dict[str, str] = {
    "sumerian": "Sumerian",
    "mesopotamian": "Mesopotamian / Babylonian",
    "egyptian": "Ancient Egyptian",
    "hittite": "Hittite / Hurrian",
    "canaanite": "Canaanite / Ugaritic",
    "vedic": "Vedic / Hindu",
    "chinese": "Ancient Chinese",
    "greek": "Ancient Greek",
    "hebrew": "Hebrew / Israelite",
    "zoroastrian": "Zoroastrian / Persian",
    "minoan": "Minoan / Aegean",
    "roman": "Roman / Italic",
    "mesoamerican": "Mesoamerican",
    "norse": "Norse / Germanic",
    "celtic": "Celtic",
    "polynesian": "Polynesian / Oceanic",
    "aboriginal": "Australian Aboriginal",
    "ainu": "Ainu / Japanese",
    "african": "African",
}


def retention_score(age_rank_oldest: int, culture_count: int) -> float:
    """Law 4 + 5 + 7 encoded as a scalar.

    retention = 10 / age_rank + (size - 1) * 5

    Singletons from the oldest cultures (Sumerian, Mesopotamian) survive alone.
    Newer singletons are dropped. Convergence across cultures rescues any age.
    """
    if age_rank_oldest <= 0:
        age_rank_oldest = 1
    return (10.0 / age_rank_oldest) + max(culture_count - 1, 0) * 5.0


RETENTION_THRESHOLD: float = 5.0
EMBEDDING_COSINE_THRESHOLD: float = 0.78
