"""Deity Dossier builder.

For a given epoch:

1. Walk every unique actor name that appears in `culture_atomic_events` for
   that epoch's story outlines.
2. Aggregate the actor's actions (verb/outcome/source_ref) and co-occurring
   actors from those events.
3. Resolve the name to a `canonical_actor` row via fuzzy name matching.
4. If resolved, join `canon_support_links` → `source_records` →
   `source_dates` to find the earliest composition/attestation date.
5. Pull up to 3 representative passage excerpts from `source_versions`.
6. Ask MiniMax m2.5 to write a 2-3 paragraph dossier describing this
   specific deity's character, domain, and origin story — grounded in the
   passages, not invented.

Writes one `deity_dossiers` row per (epoch_id, normalized_name).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import async_session_factory
from src.canon.services.narrative_v2.minimax import call_minimax_text

logger = logging.getLogger(__name__)


_DOSSIER_SYSTEM_PROMPT = """You write compact, evidence-based deity dossiers.

For the given deity name and set of source excerpts + extracted actions,
write 2–3 paragraphs (no more than ~250 words) that describe:

  1. WHO this specific deity is — their domain, role, and distinctive
     attributes as attested in the source texts. Distinguish them from
     similar/related deities where the sources make that clear.
  2. The deity's origin / earliest attestation and the tradition they
     belong to.
  3. The deity's characteristic actions and relationships with other
     named entities in the sources.

CRITICAL RULES:
- STAY GROUNDED. Only state things supported by the supplied excerpts or
  actions. If the sources are thin, write less and say so plainly.
- Do NOT conflate this deity with other deities from other traditions
  unless a source in the packet explicitly equates them.
- Do NOT invent dates, genealogies, or events.
- Prose only. No headings, no bullet lists, no markdown other than an
  optional italicized phrase.
"""


def _normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class DossierBuilder:
    """Builds `deity_dossiers` rows for a given epoch."""

    def __init__(
        self,
        *,
        max_actors: int | None = None,
        llm_concurrency: int = 4,
        skip_llm: bool = False,
    ):
        self.max_actors = max_actors
        self.llm_concurrency = llm_concurrency
        self.skip_llm = skip_llm

    async def build_for_epoch(
        self,
        epoch_id: str,
        epoch_order: int,
        *,
        wipe: bool = False,
    ) -> dict[str, Any]:
        """Build dossiers for every actor in Epoch `epoch_order`.

        Returns a summary dict with counts. Session management is internal:
        this method opens short-lived sessions around each DB operation so
        long LLM calls never hold open connections.
        """
        logger.info(
            "DossierBuilder: building dossiers for epoch_order=%d (wipe=%s)",
            epoch_order,
            wipe,
        )

        # Step 0: optionally wipe previous dossiers for this epoch
        if wipe:
            async with async_session_factory() as s:
                await s.execute(
                    text(
                        "DELETE FROM deity_dossiers WHERE epoch_id = :eid"
                    ),
                    {"eid": epoch_id},
                )
                await s.commit()

        # Step 1: gather every atomic event for this epoch's outlines.
        # We denormalize here so the Python side can group/aggregate by
        # actor name without N+1 queries.
        async with async_session_factory() as s:
            rows = (
                await s.execute(
                    text(
                        """
                        SELECT ae.id,
                               ae.culture_key,
                               ae.actors,
                               ae.verb,
                               ae.verb_family,
                               ae.objects,
                               ae.outcome,
                               ae.outcome_keywords,
                               ae.quoted_phrase,
                               ae.source_ref,
                               so.chapter_number,
                               cn.source_ids AS culture_source_ids
                        FROM culture_atomic_events ae
                        JOIN story_outlines so ON so.id = ae.story_outline_id
                        LEFT JOIN culture_narratives cn
                          ON cn.id = ae.culture_narrative_id
                        WHERE so.epoch_id = :eid
                        """
                    ),
                    {"eid": epoch_id},
                )
            ).all()

        # Group by normalized actor name
        per_actor: dict[str, dict[str, Any]] = {}
        for r in rows:
            (
                ev_id,
                culture_key,
                actors_list,
                verb,
                verb_family,
                objects,
                outcome,
                outcome_keywords,
                quoted,
                source_ref,
                chapter_number,
                culture_source_ids,
            ) = r
            actors_list = list(actors_list or [])
            for a in actors_list:
                nm = str(a).strip()
                if not nm:
                    continue
                norm = _normalize_name(nm)
                if not norm:
                    continue
                bucket = per_actor.setdefault(
                    norm,
                    {
                        "display_names": {},
                        "cultures": set(),
                        "actions": [],
                        "co_occurring": {},
                        "chapters": set(),
                        "culture_source_ids": set(),
                    },
                )
                # Track display name frequency so we pick the most common
                bucket["display_names"][nm] = bucket["display_names"].get(nm, 0) + 1
                if culture_key:
                    bucket["cultures"].add(culture_key)
                bucket["chapters"].add(chapter_number)
                bucket["actions"].append(
                    {
                        "verb": verb,
                        "verb_family": verb_family,
                        "objects": list(objects or []),
                        "outcome": outcome,
                        "outcome_keywords": list(outcome_keywords or []),
                        "source_ref": source_ref,
                        "chapter_number": chapter_number,
                        "quoted_phrase": quoted,
                        "culture_key": culture_key,
                    }
                )
                for other in actors_list:
                    other_norm = _normalize_name(str(other))
                    if other_norm and other_norm != norm:
                        bucket["co_occurring"][str(other)] = (
                            bucket["co_occurring"].get(str(other), 0) + 1
                        )
                for sid in list(culture_source_ids or []):
                    bucket["culture_source_ids"].add(str(sid))

        logger.info(
            "DossierBuilder: %d unique actors across %d events",
            len(per_actor),
            len(rows),
        )

        if self.max_actors is not None:
            # Keep the highest-event-count actors
            ranked = sorted(
                per_actor.items(), key=lambda kv: -len(kv[1]["actions"])
            )[: self.max_actors]
            per_actor = dict(ranked)

        # Preload archetype membership for denormalization
        async with async_session_factory() as s:
            arch_rows = (
                await s.execute(
                    text(
                        "SELECT id, archetype_name, also_known_as "
                        "FROM archetype_registry"
                    )
                )
            ).all()
        name_to_archetype: dict[str, tuple[str, str]] = {}
        for a_id, a_name, aka in arch_rows:
            for alt in list(aka or []) + [a_name]:
                name_to_archetype[_normalize_name(alt)] = (str(a_id), a_name)

        # Step 2: process each actor sequentially for DB work, parallel
        # for LLM enrichment.
        sem = asyncio.Semaphore(self.llm_concurrency)
        write_count = 0
        resolved_count = 0
        dated_count = 0
        llm_count = 0

        async def process(norm: str, bucket: dict[str, Any]) -> None:
            nonlocal write_count, resolved_count, dated_count, llm_count
            # Pick the most common display name as canonical for this row
            dn_items = sorted(
                bucket["display_names"].items(), key=lambda kv: -kv[1]
            )
            display_name = dn_items[0][0] if dn_items else norm

            # Resolve to canonical_actor by name (substring or alias match).
            canonical_actor_id: str | None = None
            canonical_summary: str | None = None
            earliest = None
            passages: list[dict[str, Any]] = []

            async with async_session_factory() as s:
                candidate = await _resolve_canonical_actor(
                    s, display_name, list(bucket["display_names"].keys())
                )
            if candidate is not None:
                canonical_actor_id = candidate["id"]
                canonical_summary = candidate["summary"]
                resolved_count += 1

                async with async_session_factory() as s:
                    earliest = await _earliest_source(s, canonical_actor_id)
                if earliest is not None:
                    dated_count += 1

                async with async_session_factory() as s:
                    passages = await _representative_passages(
                        s, canonical_actor_id, bucket["culture_source_ids"]
                    )
            else:
                # No canonical match — still try passage pulling from
                # the culture's source_ids where the actor name occurs.
                async with async_session_factory() as s:
                    passages = await _passages_from_culture_sources(
                        s, bucket["culture_source_ids"], list(
                            bucket["display_names"].keys()
                        )
                    )

            # Build the characteristics packet for MiniMax
            characteristics_md: str | None = None
            if not self.skip_llm:
                async with sem:
                    characteristics_md = await _llm_characteristics(
                        display_name=display_name,
                        cultures=sorted(bucket["cultures"]),
                        canonical_summary=canonical_summary,
                        earliest=earliest,
                        actions=bucket["actions"][:30],
                        passages=passages[:3],
                        co_occurring=bucket["co_occurring"],
                    )
                    if characteristics_md:
                        llm_count += 1

            # Current archetype membership
            arch_tuple = name_to_archetype.get(norm)
            current_arch_id = arch_tuple[0] if arch_tuple else None
            current_arch_name = arch_tuple[1] if arch_tuple else None

            # Persist
            async with async_session_factory() as s:
                await s.execute(
                    text(
                        """
                        INSERT INTO deity_dossiers (
                            actor_name,
                            normalized_name,
                            epoch_id,
                            canonical_actor_id,
                            cultures,
                            event_count,
                            actions,
                            co_occurring_actors,
                            earliest_source_id,
                            earliest_source_title,
                            earliest_date_start,
                            earliest_date_end,
                            earliest_date_label,
                            dating_confidence,
                            source_passage_ids,
                            source_passage_excerpts,
                            characteristics_md,
                            current_archetype_id,
                            current_archetype_name
                        ) VALUES (
                            :actor_name,
                            :normalized_name,
                            :epoch_id,
                            :canonical_actor_id,
                            CAST(:cultures AS jsonb),
                            :event_count,
                            CAST(:actions AS jsonb),
                            CAST(:co_occurring_actors AS jsonb),
                            :earliest_source_id,
                            :earliest_source_title,
                            :earliest_date_start,
                            :earliest_date_end,
                            :earliest_date_label,
                            :dating_confidence,
                            CAST(:source_passage_ids AS jsonb),
                            CAST(:source_passage_excerpts AS jsonb),
                            :characteristics_md,
                            :current_archetype_id,
                            :current_archetype_name
                        )
                        ON CONFLICT (epoch_id, normalized_name) DO UPDATE SET
                            actor_name = EXCLUDED.actor_name,
                            canonical_actor_id = EXCLUDED.canonical_actor_id,
                            cultures = EXCLUDED.cultures,
                            event_count = EXCLUDED.event_count,
                            actions = EXCLUDED.actions,
                            co_occurring_actors = EXCLUDED.co_occurring_actors,
                            earliest_source_id = EXCLUDED.earliest_source_id,
                            earliest_source_title = EXCLUDED.earliest_source_title,
                            earliest_date_start = EXCLUDED.earliest_date_start,
                            earliest_date_end = EXCLUDED.earliest_date_end,
                            earliest_date_label = EXCLUDED.earliest_date_label,
                            dating_confidence = EXCLUDED.dating_confidence,
                            source_passage_ids = EXCLUDED.source_passage_ids,
                            source_passage_excerpts = EXCLUDED.source_passage_excerpts,
                            characteristics_md = EXCLUDED.characteristics_md,
                            current_archetype_id = EXCLUDED.current_archetype_id,
                            current_archetype_name = EXCLUDED.current_archetype_name,
                            updated_at = now()
                        """
                    ),
                    {
                        "actor_name": display_name,
                        "normalized_name": norm,
                        "epoch_id": epoch_id,
                        "canonical_actor_id": canonical_actor_id,
                        "cultures": _json(sorted(bucket["cultures"])),
                        "event_count": len(bucket["actions"]),
                        "actions": _json(bucket["actions"]),
                        "co_occurring_actors": _json(bucket["co_occurring"]),
                        "earliest_source_id": (
                            earliest["source_id"] if earliest else None
                        ),
                        "earliest_source_title": (
                            earliest["title"] if earliest else None
                        ),
                        "earliest_date_start": (
                            earliest["date_start"] if earliest else None
                        ),
                        "earliest_date_end": (
                            earliest["date_end"] if earliest else None
                        ),
                        "earliest_date_label": (
                            earliest["date_label"] if earliest else None
                        ),
                        "dating_confidence": (
                            earliest["dating_confidence"] if earliest else None
                        ),
                        "source_passage_ids": _json(
                            [p["source_id"] for p in passages]
                        ),
                        "source_passage_excerpts": _json(passages),
                        "characteristics_md": characteristics_md,
                        "current_archetype_id": current_arch_id,
                        "current_archetype_name": current_arch_name,
                    },
                )
                await s.commit()
            write_count += 1

        # Ensure uniqueness index used by ON CONFLICT is present (no-op if
        # migration already ran)
        # --- Run actors with bounded LLM concurrency ---
        tasks = [process(norm, bucket) for norm, bucket in per_actor.items()]
        # Drive with gather but keep one task running at a time for DB
        # writes, while LLM calls are gated by the semaphore.
        await asyncio.gather(*tasks, return_exceptions=False)

        logger.info(
            "DossierBuilder: wrote=%d resolved=%d dated=%d llm=%d",
            write_count,
            resolved_count,
            dated_count,
            llm_count,
        )
        return {
            "actors_processed": write_count,
            "canonical_resolved": resolved_count,
            "dated": dated_count,
            "llm_enriched": llm_count,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(v: Any) -> str:
    import json

    def default(x: Any) -> Any:
        if isinstance(x, set):
            return sorted(x)
        return str(x)

    return json.dumps(v, default=default)


async def _resolve_canonical_actor(
    session: AsyncSession,
    primary_name: str,
    all_names: list[str],
) -> dict[str, Any] | None:
    """Best-effort canonical_actor lookup by name.

    Canonical names in the DB often have formats like "Amar-Utu (Marduk)" or
    "Alhim (Elohim)". We try:
      1. Exact case-insensitive match on primary_name.
      2. Substring match on primary_name (inside parentheses form).
      3. Same two passes for each alternate display name.
    Picks the actor with the most support links as the canonical.
    """
    candidates = [primary_name] + [n for n in all_names if n != primary_name]
    for name in candidates:
        if not name:
            continue
        esc = re.escape(name)
        row = (
            await session.execute(
                text(
                    """
                    SELECT ca.id, ca.canonical_name, ca.summary,
                        COUNT(csl.id) AS support_count
                    FROM canonical_actors ca
                    LEFT JOIN canon_support_links csl
                      ON csl.canonical_id = ca.id
                     AND csl.canonical_type = 'actor'
                    WHERE ca.canonical_name ~* :pat
                      AND ca.is_current = true
                    GROUP BY ca.id
                    ORDER BY support_count DESC
                    LIMIT 1
                    """
                ),
                {
                    "pat": rf"(^|[^a-zA-Z]){esc}([^a-zA-Z]|$)",
                },
            )
        ).first()
        if row:
            return {
                "id": str(row[0]),
                "canonical_name": row[1],
                "summary": row[2],
                "support_count": row[3],
            }
    return None


async def _earliest_source(
    session: AsyncSession, canonical_actor_id: str
) -> dict[str, Any] | None:
    """Earliest attested/composed source for a canonical actor."""
    row = (
        await session.execute(
            text(
                """
                SELECT sr.id,
                       sr.canonical_title,
                       sd.date_start,
                       sd.date_end,
                       sd.date_label,
                       sd.dating_confidence
                FROM canon_support_links csl
                JOIN source_records sr ON sr.id = csl.archive_object_id
                JOIN source_dates sd ON sd.source_record_id = sr.id
                WHERE csl.canonical_id = :cid
                  AND csl.canonical_type = 'actor'
                  AND csl.archive_object_type = 'source_record'
                  AND sd.date_type IN ('composition', 'attestation')
                  AND sd.date_start IS NOT NULL
                ORDER BY sd.date_start ASC
                LIMIT 1
                """
            ),
            {"cid": canonical_actor_id},
        )
    ).first()
    if not row:
        return None
    return {
        "source_id": str(row[0]),
        "title": row[1],
        "date_start": row[2],
        "date_end": row[3],
        "date_label": row[4],
        "dating_confidence": row[5],
    }


async def _representative_passages(
    session: AsyncSession,
    canonical_actor_id: str,
    culture_source_ids: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Top-weight support links → source_versions text excerpts."""
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (sr.id)
                       sr.id,
                       sr.canonical_title,
                       sr.culture,
                       sv.text_extracted,
                       csl.weight
                FROM canon_support_links csl
                JOIN source_records sr ON sr.id = csl.archive_object_id
                LEFT JOIN source_versions sv ON sv.source_record_id = sr.id
                WHERE csl.canonical_id = :cid
                  AND csl.canonical_type = 'actor'
                  AND csl.archive_object_type = 'source_record'
                  AND sv.text_extracted IS NOT NULL
                  AND length(sv.text_extracted) > 40
                ORDER BY sr.id, csl.weight DESC, length(sv.text_extracted) DESC
                """
            ),
            {"cid": canonical_actor_id},
        )
    ).all()
    by_id: list[dict[str, Any]] = []
    for r in rows:
        by_id.append(
            {
                "source_id": str(r[0]),
                "title": r[1],
                "culture": r[2],
                "excerpt": (r[3] or "")[:3000],
                "weight": float(r[4] or 0),
            }
        )
    by_id.sort(key=lambda p: -p["weight"])
    return by_id[:limit]


async def _passages_from_culture_sources(
    session: AsyncSession,
    culture_source_ids: set[str] | None,
    name_variants: list[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Fallback when canonical_actor wasn't resolved.

    Search the culture's own source_versions text for passages that
    mention any variant of the actor name.
    """
    if not culture_source_ids or not name_variants:
        return []
    ids = list(culture_source_ids)
    # Build an ILIKE OR chain (bounded by 10 variants)
    variants = [v for v in name_variants if v and len(v) >= 3][:10]
    if not variants:
        return []
    like_clauses = " OR ".join(
        [f"sv.text_extracted ILIKE :v{i}" for i in range(len(variants))]
    )
    params: dict[str, Any] = {"ids": ids}
    for i, v in enumerate(variants):
        params[f"v{i}"] = f"%{v}%"
    rows = (
        await session.execute(
            text(
                f"""
                SELECT sr.id,
                       sr.canonical_title,
                       sr.culture,
                       sv.text_extracted
                FROM source_versions sv
                JOIN source_records sr ON sr.id = sv.source_record_id
                WHERE sr.id = ANY(:ids::uuid[])
                  AND sv.text_extracted IS NOT NULL
                  AND ({like_clauses})
                ORDER BY length(sv.text_extracted) DESC
                LIMIT :limit
                """
            ),
            {**params, "limit": limit},
        )
    ).all()
    return [
        {
            "source_id": str(r[0]),
            "title": r[1],
            "culture": r[2],
            "excerpt": (r[3] or "")[:3000],
            "weight": None,
        }
        for r in rows
    ]


async def _llm_characteristics(
    *,
    display_name: str,
    cultures: list[str],
    canonical_summary: str | None,
    earliest: dict[str, Any] | None,
    actions: list[dict[str, Any]],
    passages: list[dict[str, Any]],
    co_occurring: dict[str, int],
) -> str | None:
    """Call MiniMax to produce a 2-3 paragraph dossier for this deity."""
    # Build a compact, structured packet for the model.
    earliest_line = ""
    if earliest:
        ds = earliest.get("date_start")
        de = earliest.get("date_end")
        dl = earliest.get("date_label") or ""
        title = earliest.get("title") or ""
        if ds is not None and de is not None and ds != de:
            era = f"{ds}–{de}"
        elif ds is not None:
            era = str(ds)
        else:
            era = dl
        earliest_line = f"Earliest attestation: {title} ({era})"

    top_cooc = sorted(co_occurring.items(), key=lambda kv: -kv[1])[:8]
    cooc_line = ", ".join(f"{n} ({c}x)" for n, c in top_cooc) if top_cooc else ""

    action_lines = []
    for a in actions[:12]:
        obj = ", ".join(a.get("objects") or []) or "—"
        outcome = a.get("outcome") or ""
        src = a.get("source_ref") or ""
        culture = a.get("culture_key") or ""
        action_lines.append(
            f"- [{culture}] verb={a.get('verb')} → outcome=\"{outcome}\" "
            f"(objects: {obj}; source: {src})"
        )

    passage_blocks = []
    for p in passages:
        passage_blocks.append(
            f"--- SOURCE: {p['title']} ({p.get('culture') or '?'}) ---\n"
            f"{p['excerpt']}"
        )

    packet = (
        f"DEITY: {display_name}\n"
        f"Cultures that mention this name in Epoch 0: "
        f"{', '.join(cultures) if cultures else '—'}\n"
        f"{earliest_line}\n"
        f"Canonical summary in our DB: {canonical_summary or '—'}\n\n"
        f"CO-OCCURRING NAMED ACTORS (count of shared events): "
        f"{cooc_line or '—'}\n\n"
        f"EXTRACTED ACTIONS (from culture fact sheets):\n"
        f"{chr(10).join(action_lines) if action_lines else '—'}\n\n"
        f"SOURCE PASSAGES:\n"
        f"{chr(10).join(passage_blocks) if passage_blocks else '(no passage excerpts available)'}\n\n"
        f"Write a 2–3 paragraph evidence-based dossier for this specific "
        f"deity following the system rules."
    )

    try:
        result = await call_minimax_text(
            user_prompt=packet,
            system_prompt=_DOSSIER_SYSTEM_PROMPT,
            temperature=0.25,
            max_tokens=900,
            timeout=180.0,
        )
        return result or None
    except Exception:  # noqa: BLE001
        logger.exception(
            "MiniMax characteristics generation failed for %s", display_name
        )
        return None
