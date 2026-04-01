"""Rules-based pre-classifier for context extraction using lexical pattern matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from src.ingestion.models.enums import ContextType, StatementConfidence


class RulesVerdict(str, Enum):
    CONTEXTUAL = "contextual"
    EVIDENCE = "evidence"
    AMBIGUOUS = "ambiguous"
    NOISE = "noise"


@dataclass
class RulesResult:
    verdict: RulesVerdict
    context_type: ContextType | None
    confidence: StatementConfidence
    matched_pattern: str | None


SCHOLARLY_CONSENSUS_PATTERNS = [
    r"\bscholars?\s+(?:believe|agree|accept|maintain|hold)\b",
    r"\bit\s+is\s+(?:generally|widely|broadly)\s+(?:accepted|believed|thought|recognized)\b",
    r"\bconsensus\s+(?:holds|is|suggests)\b",
    r"\bwidely\s+(?:regarded|considered|acknowledged)\b",
    r"\bmost\s+(?:scholars|researchers|historians|archaeologists)\b",
    r"\bwell[\s-]established\b",
    r"\bgenerally\s+(?:understood|recognized|accepted)\b",
]

SCHOLARLY_DEBATE_PATTERNS = [
    r"\bdebated\b",
    r"\bcontested\b",
    r"\balternatively\b",
    r"\bsome\s+scholars?\s+(?:argue|believe|suggest|propose|contend)\b",
    r"\bdisputed\b",
    r"\bcontroversi(?:al|y)\b",
    r"\bin\s+(?:contrast|opposition)\b",
    r"\bhowever,?\s+(?:other|some)\b",
    r"\bremains?\s+(?:unclear|uncertain|open)\b",
    r"\bcompeting\s+(?:theories|hypotheses|interpretations|views)\b",
]

FUNCTIONAL_HYPOTHESIS_PATTERNS = [
    r"\bmay\s+have\s+been\s+(?:used|intended|designed|built|constructed)\b",
    r"\bpossibly\s+functioned\s+as\b",
    r"\bthought\s+to\s+(?:serve|represent|symbolize|indicate)\b",
    r"\bperhaps\s+(?:used|served|functioned|intended)\b",
    r"\blikely\s+(?:served|used|functioned)\s+as\b",
    r"\bprobably\s+(?:used|served|functioned)\b",
    r"\bsuggested\s+(?:purpose|function|use|role)\b",
    r"\bpurported\s+(?:to|purpose|function)\b",
]

COMPARATIVE_PATTERNS = [
    r"\bsimilar\s+to\b",
    r"\bcomparable\s+to\b",
    r"\bunlike\b",
    r"\bin\s+(?:comparison|contrast)\s+(?:to|with)\b",
    r"\bresembl(?:es?|ing|ance)\b",
    r"\banalogous\s+to\b",
    r"\breminiscent\s+of\b",
    r"\bparallel(?:s|ed)?\s+(?:to|with|in|found)\b",
    r"\bdistinct\s+from\b",
    r"\bdiffers?\s+from\b",
]

DESCRIPTIVE_PATTERNS = [
    r"\bmeasur(?:es?|ing|ement)\b.*\b(?:cm|mm|m|meters?|inches?|feet|ft)\b",
    r"\bmade\s+(?:of|from)\s+(?:stone|clay|bronze|copper|gold|silver|wood|ivory|ceramic)\b",
    r"\bweigh(?:s|ing|ed)\s+(?:approximately|about|roughly|nearly)?\s*\d",
    r"\bdimensions?\b",
    r"\b(?:cylindrical|rectangular|circular|oval|triangular|square)\s+(?:shape|form|base|cross-section)\b",
    r"\bdecorated\s+with\b",
    r"\binscribed\s+(?:with|on)\b",
    r"\bfound\s+(?:at|in|near)\b.*\bsite\b",
    r"\bexcavat(?:ed|ion)\b",
]

EVIDENCE_PATTERNS = [
    r"^[\"'"].+[\"'"]$",
    r"\btranslat(?:ion|ed)\s*:\s*[\"']",
    r"\btransliterat(?:ion|ed)\s*:",
    r"\bcol(?:umn)?\s+[IVXivx]+\s+(?:line|l\.)\s+\d",
    r"\bobverse\b.*\breverse\b",
    r"\brecto\b.*\bverso\b",
    r"\bl(?:ine)?\.?\s*\d+\s*[-:]\s*.{10,}",
]

NOISE_PATTERNS = [
    r"^\s*(?:bibliography|references|works?\s+cited|notes?)\s*$",
    r"^\s*(?:chapter|section|part)\s+\d",
    r"^\s*(?:table|figure|fig\.?|plate|pl\.?)\s+\d",
    r"^\s*(?:ibid|op\.?\s*cit|loc\.?\s*cit)",
    r"^\s*\d+\s*$",
    r"^\s*(?:pp?\.?\s*)?\d+\s*[-–]\s*\d+\s*$",
]


def _match_patterns(text: str, patterns: list[str]) -> str | None:
    """Return the first matching pattern or None."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return pattern
    return None


def classify_with_rules(text: str) -> RulesResult:
    """Run rules-based classification on a text segment.

    Returns a verdict indicating whether the text is clearly contextual,
    clearly evidence/noise, or ambiguous (needs LLM).
    """
    stripped = text.strip()
    if not stripped or len(stripped) < 20:
        return RulesResult(RulesVerdict.NOISE, None, StatementConfidence.HIGH, "too_short")

    if match := _match_patterns(stripped, NOISE_PATTERNS):
        return RulesResult(RulesVerdict.NOISE, None, StatementConfidence.HIGH, match)

    if match := _match_patterns(stripped, EVIDENCE_PATTERNS):
        return RulesResult(RulesVerdict.EVIDENCE, None, StatementConfidence.HIGH, match)

    if match := _match_patterns(stripped, SCHOLARLY_CONSENSUS_PATTERNS):
        return RulesResult(RulesVerdict.CONTEXTUAL, ContextType.SCHOLARLY_CONSENSUS, StatementConfidence.HIGH, match)

    if match := _match_patterns(stripped, SCHOLARLY_DEBATE_PATTERNS):
        return RulesResult(RulesVerdict.CONTEXTUAL, ContextType.SCHOLARLY_DEBATE, StatementConfidence.HIGH, match)

    if match := _match_patterns(stripped, FUNCTIONAL_HYPOTHESIS_PATTERNS):
        return RulesResult(RulesVerdict.CONTEXTUAL, ContextType.FUNCTIONAL_HYPOTHESIS, StatementConfidence.HIGH, match)

    if match := _match_patterns(stripped, COMPARATIVE_PATTERNS):
        return RulesResult(RulesVerdict.CONTEXTUAL, ContextType.COMPARATIVE, StatementConfidence.MEDIUM, match)

    if match := _match_patterns(stripped, DESCRIPTIVE_PATTERNS):
        return RulesResult(RulesVerdict.CONTEXTUAL, ContextType.DESCRIPTIVE, StatementConfidence.MEDIUM, match)

    return RulesResult(RulesVerdict.AMBIGUOUS, None, StatementConfidence.UNCERTAIN, None)
