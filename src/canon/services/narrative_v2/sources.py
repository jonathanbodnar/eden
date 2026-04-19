"""Source gathering for the V2 pipeline.

Thin adapter around the V1 source gathering helpers. Returns sources grouped
by normalized culture key, already relevance-scored and trimmed.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.services.narrative_synthesizer import NarrativeSynthesizer
from src.canon.services.narrative_v2.stage1_fact_sheet import SourceInput


async def gather_sources_for_epoch(
    session: AsyncSession, epoch_id: uuid.UUID, themes: list[str]
) -> list[tuple[str, str, list[SourceInput]]]:
    """Return [(culture_key, culture_label, [SourceInput])] sorted oldest-first."""

    svc = NarrativeSynthesizer()
    raw_groups = await svc._gather_sources_by_culture(session, epoch_id, themes)

    out: list[tuple[str, str, list[SourceInput]]] = []
    for culture_key, culture_label, sources in raw_groups:
        inputs = [
            SourceInput(
                source_id=str(s.get("source_id") or ""),
                title=str(s.get("title") or ""),
                text=str(s.get("excerpt") or ""),
                weight=float(s.get("weight") or 0.0),
            )
            for s in sources
            if (s.get("excerpt") or "").strip()
        ]
        if inputs:
            out.append((culture_key, culture_label, inputs))
    return out


async def gather_actor_equivalences(
    session: AsyncSession,
) -> dict[str, set[str]]:
    """Return {normalized_name: {equivalent_normalized_names}} from the DB.

    Used by the Stage 3 clusterer to decide whether two actors across cultures
    should count as 'the same actor' for rule-based matching.
    """
    from sqlalchemy import text
    import re as _re

    def _norm(s: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    rows = (
        await session.execute(
            text(
                """
                SELECT
                    COALESCE(
                        (SELECT canonical_name FROM canonical_actors WHERE id = ee.primary_entity_id),
                        'Unknown'
                    ) as primary_name,
                    COALESCE(
                        (SELECT canonical_name FROM canonical_actors WHERE id = ee.equivalent_entity_id),
                        'Unknown'
                    ) as equivalent_name
                FROM entity_equivalences ee
                WHERE ee.primary_entity_type = 'actor'
                """
            )
        )
    ).all()

    groups: dict[str, set[str]] = {}
    for p, e in rows:
        p_k = _norm(p)
        e_k = _norm(e)
        if not p_k or not e_k or p_k == "unknown" or e_k == "unknown":
            continue
        groups.setdefault(p_k, set()).update({p_k, e_k})
        groups.setdefault(e_k, set()).update({p_k, e_k})

    # Transitively close: if A~B and B~C, make A~C
    changed = True
    while changed:
        changed = False
        for k in list(groups.keys()):
            merged = set(groups[k])
            for m in list(groups[k]):
                if m in groups:
                    merged |= groups[m]
            if merged != groups[k]:
                groups[k] = merged
                changed = True

    return groups
