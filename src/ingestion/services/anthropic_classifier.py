"""Anthropic-based LLM classifier for context extraction using tool_use structured output."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic

from src.ingestion.config import settings
from src.ingestion.models.enums import ContextType, StatementConfidence

logger = logging.getLogger(__name__)

CLASSIFICATION_TOOL = {
    "name": "classify_segment",
    "description": "Classify a text segment from a secondary scholarly source. Determine whether it is contextual (descriptive, comparative, scholarly analysis) or should be skipped (direct evidence, noise).",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["contextual", "evidence", "speculation", "noise"],
                "description": "Whether the passage is contextual (scholarly description/analysis), evidence (direct quotes, inscriptions, primary data), speculation (unsupported claims), or noise (irrelevant content).",
            },
            "context_type": {
                "type": "string",
                "enum": ["descriptive", "comparative", "scholarly_consensus", "scholarly_debate", "functional_hypothesis", "uncertain"],
                "description": "The type of contextual statement. Only meaningful when classification is 'contextual'.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "uncertain"],
                "description": "How confident the classification is.",
            },
            "statement_text": {
                "type": "string",
                "description": "The normalized contextual statement extracted from the passage. Should be a clear, standalone statement.",
            },
            "supporting_quote": {
                "type": "string",
                "description": "The exact text span from the original passage that supports this classification.",
            },
        },
        "required": ["classification", "context_type", "confidence", "statement_text", "supporting_quote"],
    },
}

SYSTEM_PROMPT = """You are an expert classifier for an ancient history and archaeology research platform. Your job is to analyze text segments from secondary scholarly sources and classify them.

CLASSIFICATION TAXONOMY:

1. **contextual** - Scholarly descriptions, analysis, and interpretations:
   - **descriptive**: Physical descriptions, measurements, material descriptions, geographic descriptions
   - **comparative**: Comparisons between artifacts, sites, or texts ("similar to", "comparable to", "unlike")
   - **scholarly_consensus**: Widely accepted scholarly views ("scholars believe", "it is generally accepted", "consensus holds")
   - **scholarly_debate**: Contested or debated topics ("debated", "contested", "alternatively", "some scholars argue")
   - **functional_hypothesis**: Proposed functions or purposes ("may have been used for", "possibly functioned as", "thought to serve")
   - **uncertain**: Contextual but doesn't fit neatly into other categories

2. **evidence** - Direct primary source material that should NOT be classified as context:
   - Direct quotes from ancient texts
   - Inscription transcriptions
   - Raw archaeological data
   - Primary source translations

3. **speculation** - Unsupported claims without scholarly backing

4. **noise** - Bibliographic references, table of contents, headers, irrelevant material

RULES:
- Only classify as "contextual" if the text provides descriptive or analytical information about a subject
- Evidence (direct quotes, inscriptions, primary data) is NOT context
- When in doubt between context types, use "uncertain"
- The statement_text should be a normalized, clear statement — not just the raw text
- The supporting_quote must be the exact original text span"""


@dataclass
class ClassificationResult:
    classification: str
    context_type: ContextType | None
    confidence: StatementConfidence
    statement_text: str
    supporting_quote: str
    is_contextual: bool


class AnthropicClassifier:
    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def classify_segment(self, text: str) -> ClassificationResult:
        """Classify a single text segment."""
        response = self.client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": f"Classify this text segment:\n\n{text}",
            }],
            tools=[CLASSIFICATION_TOOL],
            tool_choice={"type": "tool", "name": "classify_segment"},
        )

        return self._parse_response(response)

    def classify_batch(self, segments: list[tuple[str, str]]) -> list[tuple[str, ClassificationResult]]:
        """Classify multiple segments in a single API call.

        Args:
            segments: List of (segment_id, text) tuples.

        Returns:
            List of (segment_id, ClassificationResult) tuples.
        """
        if not segments:
            return []

        numbered_text = "\n\n".join(
            f"--- SEGMENT {i+1} (ID: {seg_id}) ---\n{text}"
            for i, (seg_id, text) in enumerate(segments)
        )

        response = self.client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT + "\n\nYou will receive multiple segments. Call the classify_segment tool once for EACH segment.",
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": f"Classify each of these segments:\n\n{numbered_text}",
            }],
            tools=[CLASSIFICATION_TOOL],
            tool_choice={"type": "any"},
        )

        results: list[tuple[str, ClassificationResult]] = []
        tool_calls = [block for block in response.content if block.type == "tool_use"]

        for i, tool_call in enumerate(tool_calls):
            seg_id = segments[i][0] if i < len(segments) else f"unknown_{i}"
            try:
                result = self._parse_tool_input(tool_call.input)
                results.append((seg_id, result))
            except Exception as exc:
                logger.warning("Failed to parse LLM result for segment %s: %s", seg_id, exc)
                results.append((seg_id, ClassificationResult(
                    classification="noise",
                    context_type=None,
                    confidence=StatementConfidence.UNCERTAIN,
                    statement_text="",
                    supporting_quote="",
                    is_contextual=False,
                )))

        return results

    def _parse_response(self, response: anthropic.types.Message) -> ClassificationResult:
        for block in response.content:
            if block.type == "tool_use":
                return self._parse_tool_input(block.input)

        raise ValueError("No tool_use block found in Anthropic response")

    @staticmethod
    def _parse_tool_input(tool_input: dict) -> ClassificationResult:
        classification = tool_input["classification"]
        is_contextual = classification == "contextual"

        context_type = None
        if is_contextual:
            raw_type = tool_input.get("context_type", "uncertain")
            try:
                context_type = ContextType(raw_type)
            except ValueError:
                context_type = ContextType.UNCERTAIN

        try:
            confidence = StatementConfidence(tool_input.get("confidence", "medium"))
        except ValueError:
            confidence = StatementConfidence.MEDIUM

        return ClassificationResult(
            classification=classification,
            context_type=context_type,
            confidence=confidence,
            statement_text=tool_input.get("statement_text", ""),
            supporting_quote=tool_input.get("supporting_quote", ""),
            is_contextual=is_contextual,
        )
