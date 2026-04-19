"""Narrative Pipeline V2 — deterministic-merge narrative synthesis.

Five stages:
    Stage 1  culture fact sheet  (LLM per culture)
    Stage 2  atomic event distillation  (LLM per culture)
    Stage 3  deterministic clustering  (platform)
    Stage 3B archetype resolution  (platform + one-shot LLM for new archetypes)
    Stage 4  narrative rendering  (LLM per chapter)
    Stage 5  post-processing  (platform)

See `docs/NARRATIVE_PIPELINE_V2.plan.md` for the full design.
"""

from src.canon.services.narrative_v2.pipeline import NarrativePipelineV2

__all__ = ["NarrativePipelineV2"]
