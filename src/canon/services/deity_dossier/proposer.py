"""Archetype merge proposal generator (MiniMax m2.5).

For each existing archetype (with >1 actor or below a cohesion threshold),
build a packet of every member's dossier and ask MiniMax to decide:

  - KEEP:      all these actors really are one archetype (rationale)
  - SPLIT:     these actors should be multiple archetypes (one proposed
               group per true archetype, with rationale per group)
  - REASSIGN:  one or more actors should move to a different existing or
               new archetype (treated as a split too)

The output is persisted as `archetype_merge_proposals` rows. Nothing is
applied to `archetype_registry` until a human approves the proposal.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.database import async_session_factory
from src.canon.services.narrative_v2.minimax import call_minimax

logger = logging.getLogger(__name__)


_PROPOSER_SYSTEM_PROMPT = """You are an expert in comparative mythology and
Ancient Near Eastern / Indo-European religion. You judge whether several
named deities from different cultures truly belong to the same *archetype*
(a single functional role in a unified narrative) or should remain
distinct.

You MUST output a single JSON object with this schema:

{
  "verdict": "keep" | "split" | "reassign",
  "overall_rationale": "...",
  "confidence": 0.0–1.0,
  "groups": [
    {
      "proposed_archetype_name": "The <Role>",
      "role_description": "one short sentence",
      "members": ["DeityName1", "DeityName2", ...],
      "rationale": "Why these belong together — cite at least one shared action from the extracted actions AND at least one earliest-source date or tradition overlap.",
      "evidence": [
        "earliest source: ...",
        "shared action: ...",
        "shared interaction with ...: ..."
      ]
    }
  ]
}

RULES:
1. If all the input deities clearly belong together, output verdict="keep"
   with a single group containing all of them.
2. If they should split, output verdict="split" with one group per true
   archetype. Every input deity MUST appear in exactly one group. Singleton
   groups are allowed (a deity can be its own archetype).
3. Do NOT merge deities just because they share a broad role ("creator",
   "sky god"). Require a shared distinctive function or relationship.
4. Recognize generic plurals vs specific individuals:
   - "Elohim" is a plural ("the gods") — it belongs with generic-divine
     groupings, not with a specific patriarchal deity.
   - "YHWH" is a specific named deity of the Abrahamic tradition — not
     interchangeable with generic "Elohim".
   - Similar care for "Anunnaki", "Igigi", "Aesir", "Devas" vs individual
     named members of those groups.
5. Prefer evidence rooted in the OLDEST attested source date and in
   shared actions (flood survivor, champion vs chaos-serpent, divine
   craftsman, etc.).
6. Proposed archetype names should be short noun phrases ("The Flood
   Hero", "The First Craftsman"). Do NOT use a single deity's name as
   the archetype name.
7. Output JSON only. No prose outside the JSON object.
"""


class ProposalGenerator:
    def __init__(
        self,
        *,
        cohesion_threshold: float = 60.0,
        llm_concurrency: int = 3,
        min_members: int = 2,
    ):
        self.cohesion_threshold = cohesion_threshold
        self.llm_concurrency = llm_concurrency
        self.min_members = min_members

    async def propose_for_epoch(
        self,
        epoch_id: str,
        epoch_order: int,
        *,
        wipe_pending: bool = False,
    ) -> dict[str, Any]:
        logger.info(
            "ProposalGenerator: epoch_order=%d (wipe_pending=%s)",
            epoch_order,
            wipe_pending,
        )

        if wipe_pending:
            async with async_session_factory() as s:
                await s.execute(
                    text(
                        "DELETE FROM archetype_merge_proposals "
                        "WHERE epoch_id = :eid AND status = 'pending'"
                    ),
                    {"eid": epoch_id},
                )
                await s.commit()

        # Step 1: load archetypes + their member dossiers in this epoch
        async with async_session_factory() as s:
            arch_rows = (
                await s.execute(
                    text(
                        """
                        SELECT ar.id,
                               ar.archetype_name,
                               ar.role_description,
                               ar.also_known_as
                        FROM archetype_registry ar
                        ORDER BY ar.archetype_name
                        """
                    )
                )
            ).all()

            dossier_rows = (
                await s.execute(
                    text(
                        """
                        SELECT id,
                               actor_name,
                               normalized_name,
                               canonical_actor_id,
                               cultures,
                               event_count,
                               actions,
                               co_occurring_actors,
                               earliest_source_title,
                               earliest_date_start,
                               earliest_date_end,
                               earliest_date_label,
                               characteristics_md,
                               current_archetype_id,
                               current_archetype_name,
                               source_passage_excerpts
                        FROM deity_dossiers
                        WHERE epoch_id = :eid
                        """
                    ),
                    {"eid": epoch_id},
                )
            ).all()

        # Group dossiers by normalized name for quick lookup
        dossier_by_norm: dict[str, dict[str, Any]] = {}
        for d in dossier_rows:
            (
                did,
                actor_name,
                norm,
                c_actor_id,
                cultures,
                event_count,
                actions,
                co_occurring,
                esrc_title,
                edstart,
                edend,
                edlabel,
                characteristics,
                current_arch_id,
                current_arch_name,
                passages,
            ) = d
            dossier_by_norm[norm] = {
                "id": str(did),
                "actor_name": actor_name,
                "normalized_name": norm,
                "cultures": list(cultures or []),
                "event_count": event_count,
                "actions": list(actions or []),
                "co_occurring_actors": dict(co_occurring or {}),
                "earliest_source_title": esrc_title,
                "earliest_date_start": edstart,
                "earliest_date_end": edend,
                "earliest_date_label": edlabel,
                "characteristics_md": characteristics,
                "current_archetype_id": (
                    str(current_arch_id) if current_arch_id else None
                ),
                "current_archetype_name": current_arch_name,
                "passages": list(passages or []),
            }

        # Step 2: for each archetype with ≥min_members dossiers, build a
        # packet and call MiniMax.
        sem = asyncio.Semaphore(self.llm_concurrency)
        tasks = []
        skipped_small = 0
        for a_id, a_name, a_role, a_aka in arch_rows:
            aka_list = list(a_aka or [])
            members = []
            for aka in aka_list:
                norm = _normalize(aka)
                if norm in dossier_by_norm:
                    members.append(dossier_by_norm[norm])
            if len(members) < self.min_members:
                skipped_small += 1
                continue
            tasks.append(
                _dispatch_proposal(
                    sem=sem,
                    epoch_id=epoch_id,
                    archetype_id=str(a_id),
                    archetype_name=a_name,
                    archetype_role=a_role,
                    members=members,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        failed = sum(1 for r in results if isinstance(r, Exception))

        logger.info(
            "ProposalGenerator: archetypes=%d proposed=%d skipped_small=%d failed=%d",
            len(arch_rows),
            ok,
            skipped_small,
            failed,
        )
        return {
            "archetypes_considered": len(arch_rows),
            "proposals_created": ok,
            "archetypes_skipped_small": skipped_small,
            "failures": failed,
        }


def _normalize(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def _dispatch_proposal(
    *,
    sem: asyncio.Semaphore,
    epoch_id: str,
    archetype_id: str,
    archetype_name: str,
    archetype_role: str | None,
    members: list[dict[str, Any]],
) -> bool:
    async with sem:
        packet = _build_packet(
            archetype_name=archetype_name,
            archetype_role=archetype_role,
            members=members,
        )
        try:
            result = await call_minimax(
                user_prompt=packet,
                system_prompt=_PROPOSER_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=16000,
                timeout=600.0,
                json_mode=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Proposal LLM call failed for archetype %s", archetype_name
            )
            return False

        if not result or "verdict" not in result:
            logger.warning(
                "Proposal LLM returned empty/invalid for %s: %s",
                archetype_name,
                str(result)[:200],
            )
            return False

        verdict = (result.get("verdict") or "keep").lower()
        if verdict not in ("keep", "split", "reassign"):
            verdict = "keep"

        groups_raw = result.get("groups") or []
        # Validate every input member is represented
        all_input_names = {m["actor_name"] for m in members}
        covered: set[str] = set()
        cleaned_groups: list[dict[str, Any]] = []
        for g in groups_raw:
            name = (g.get("proposed_archetype_name") or "").strip()
            role = (g.get("role_description") or "").strip()
            mbrs = [m for m in (g.get("members") or []) if m in all_input_names]
            covered.update(mbrs)
            cleaned_groups.append(
                {
                    "proposed_archetype_name": name,
                    "role_description": role,
                    "members": mbrs,
                    "rationale": g.get("rationale") or "",
                    "evidence": g.get("evidence") or [],
                }
            )

        # Any uncovered members get dropped into an "unassigned" group so
        # the user can see them in the UI
        unassigned = sorted(all_input_names - covered)
        if unassigned:
            cleaned_groups.append(
                {
                    "proposed_archetype_name": f"{archetype_name} (unassigned)",
                    "role_description": "",
                    "members": unassigned,
                    "rationale": "LLM did not place these members in any group.",
                    "evidence": [],
                }
            )

        # If only one non-empty group and it matches all input members →
        # verdict=keep even if the LLM said otherwise.
        non_empty = [g for g in cleaned_groups if g["members"]]
        if len(non_empty) == 1 and set(non_empty[0]["members"]) == all_input_names:
            verdict = "keep"

        async with async_session_factory() as s:
            await s.execute(
                text(
                    """
                    INSERT INTO archetype_merge_proposals (
                        epoch_id,
                        source_archetype_ids,
                        source_archetype_names,
                        proposal_kind,
                        proposed_groups,
                        overall_rationale,
                        confidence,
                        status,
                        model_name
                    ) VALUES (
                        :epoch_id,
                        CAST(:source_ids AS jsonb),
                        CAST(:source_names AS jsonb),
                        :kind,
                        CAST(:groups AS jsonb),
                        :rationale,
                        :confidence,
                        'pending',
                        :model_name
                    )
                    """
                ),
                {
                    "epoch_id": epoch_id,
                    "source_ids": json.dumps([archetype_id]),
                    "source_names": json.dumps([archetype_name]),
                    "kind": verdict,
                    "groups": json.dumps(cleaned_groups),
                    "rationale": result.get("overall_rationale") or "",
                    "confidence": float(result.get("confidence") or 0.0),
                    "model_name": settings.minimax_model,
                },
            )
            await s.commit()
    return True


def _build_packet(
    *,
    archetype_name: str,
    archetype_role: str | None,
    members: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        f"CURRENT ARCHETYPE: {archetype_name}",
        f"Current role description: {archetype_role or '(none)'}",
        f"Members: {len(members)}",
        "",
        "Below is a dossier for each member deity. Decide whether they "
        "really belong to a single archetype or should be split.",
        "",
    ]
    for m in members:
        lines.append("=" * 72)
        lines.append(f"NAME: {m['actor_name']}")
        if m.get("cultures"):
            lines.append(f"Cultures attesting in Epoch 0: {', '.join(m['cultures'])}")
        if m.get("earliest_source_title"):
            ds = m.get("earliest_date_start")
            de = m.get("earliest_date_end")
            if ds is not None and de is not None and ds != de:
                era = f"{ds}–{de}"
            elif ds is not None:
                era = str(ds)
            else:
                era = m.get("earliest_date_label") or "?"
            lines.append(
                f"Earliest attested source: {m['earliest_source_title']} ({era})"
            )
        top_cooc = sorted(
            (m.get("co_occurring_actors") or {}).items(),
            key=lambda kv: -kv[1],
        )[:6]
        if top_cooc:
            lines.append(
                "Co-occurs with: "
                + ", ".join(f"{n} ({c})" for n, c in top_cooc)
            )

        actions = m.get("actions") or []
        if actions:
            lines.append("Key actions (top 10 by order):")
            for a in actions[:10]:
                culture = a.get("culture_key") or ""
                verb = a.get("verb") or ""
                outcome = a.get("outcome") or ""
                objs = ", ".join(a.get("objects") or [])
                lines.append(
                    f"  - [{culture}] {verb} — \"{outcome}\""
                    + (f" (objects: {objs})" if objs else "")
                )

        if m.get("characteristics_md"):
            lines.append("")
            lines.append("Dossier:")
            lines.append(m["characteristics_md"])

        lines.append("")

    lines.append("=" * 72)
    lines.append("")
    lines.append(
        "Output ONE JSON object per the required schema. No prose outside JSON."
    )
    return "\n".join(lines)
