"""Global archetype synthesizer (MiniMax m2.5).

Instead of asking "should this existing archetype be split?" (the previous
proposer's frame, which can only shred clusters without merging across
cultures), this service:

1. Collects EVERY dossier in an epoch (across all current archetypes).
2. Sends ONE compact-signature prompt to MiniMax asking it to produce a
   global clustering using these weighted criteria:
     - shared distinctive actions (Noah + Utnapishtim both survive the
       flood with an ark of specific cubits)
     - overlapping co-occurring actors (if deity A interacts with the
       same relational network as deity B across cultures)
     - earliest-source date alignment (who came first → derivative
       relationship)
     - characteristic essence (explicitly distinguishing generic plurals
       like Elohim/Anunnaki from specific named deities like YHWH)
3. Parses the new clustering and (optionally) auto-applies it at a
   confidence threshold, rewriting archetype_registry and rewiring
   event_clusters.

The output is also persisted as archetype_merge_proposals rows (kind=
"synthesis", source_archetype_ids=ALL current epoch archetypes) so the
UI can display diff/rationale.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.database import async_session_factory
from src.canon.services.narrative_v2.minimax import call_minimax

logger = logging.getLogger(__name__)


_SYNTH_SYSTEM_PROMPT = """You are an expert in comparative mythology,
Ancient Near Eastern / Indo-European religion, and cross-cultural
archetype analysis.

Your task: take a flat list of DEITY DOSSIERS from multiple cultures
and produce a SINGLE unified archetype taxonomy that merges deities
ACROSS cultures when the evidence warrants it.

Use these weighted criteria when deciding whether two deities from
different cultures share a single archetype:

  1. DISTINCTIVE SHARED ACTIONS (highest weight). A unique, specific
     action performed by multiple deities across cultures is strong
     evidence for a shared archetype. Examples:
       - Noah (Hebrew Bible) + Utnapishtim (Gilgamesh) + Atra-Hasis
         (Mesopotamian) all: build an ark of specific dimensions,
         survive the flood, release birds to find land, sacrifice on
         disembarking → THE FLOOD HERO.
       - Marduk (Enuma Elish) + Indra (Ṛgveda) + Zeus (Theogony) all
         champion the young gods against a primordial chaos monster
         → THE CHAOS-SLAYING STORM KING.
       - Ptah (Memphite Theology) + the Hebrew God (Genesis) both
         create the world through thought and word → THE WORD CREATOR.

  2. OVERLAPPING RELATIONAL NETWORK (high weight). If deity A co-occurs
     with deities matching the counterparts of deity B's co-occurrences
     across cultures, they likely share an archetype. Example: Anu
     co-occurs with Anshar, Kishar in Mesopotamian creation; Ouranos
     co-occurs with analogous pairs in Greek — both sit atop a
     multi-generational genealogy of sky, mother-earth, and children.

  3. EARLIEST-SOURCE DATE ALIGNMENT (medium weight). If one deity is
     attested centuries earlier than another that shares its action
     profile, the later one is plausibly derivative — they belong in
     the same archetype with a note about chronology.

  4. CHARACTERISTIC ESSENCE (medium weight). Distinguish generic
     plurals/collectives from specific named deities:
       - "Elohim" = plural of gods (generic); "Anunnaki", "Devas",
         "Aesir" are similar collective groupings. These belong
         together as THE DIVINE COUNCIL / THE GODS (collective),
         NOT merged with specific named patriarchal deities.
       - "YHWH" is a SPECIFIC named deity of the Abrahamic tradition;
         it should NOT be merged with generic-plural collectives.
       - A god's self-description ("I am that I am", "the One")
         suggests the self-existent / monotheistic supreme archetype
         rather than one member of a pantheon.

RULES FOR OUTPUT:

A. Every input deity MUST appear in exactly one cluster. No omissions.
B. Singleton clusters are allowed (a deity that is genuinely unique).
C. Prefer cross-cultural merges. Do NOT create archetypes that contain
   deities from only one culture unless no cross-cultural match exists.
D. Archetype names are short noun phrases: "The Flood Hero", "The
   Storm-Slaying Champion", "The Primordial Sea Mother", "The Divine
   Craftsman". Do NOT use a single deity's name as the archetype name.
E. For each cluster, confidence in [0.0, 1.0]. High confidence only
   when criteria 1 AND (2 or 3) overlap strongly.
F. For each cluster, cite concrete evidence: specific shared actions
   (quote verbs/outcomes from the dossiers), specific earliest dates,
   specific co-occurring actors.
G. Output STRICT JSON, no prose outside the JSON object.

REQUIRED JSON SCHEMA:

{
  "summary": "1–2 sentences on the overall taxonomy produced.",
  "clusters": [
    {
      "archetype_name": "The <Role>",
      "role_description": "one short sentence",
      "confidence": 0.0–1.0,
      "members": ["DeityName1", "DeityName2", ...],
      "rationale": "Why these belong together — cite criteria 1/2/3/4.",
      "evidence": [
        "shared action: <quote a verb+outcome from multiple members>",
        "relational overlap: <who both co-occur with>",
        "temporal alignment: <earliest dates>",
        "essence: <why not a generic plural / why genuinely shared>"
      ]
    }
  ]
}
"""


class GlobalArchetypeSynthesizer:
    """Produce a cross-cultural archetype clustering for an entire epoch."""

    def __init__(
        self,
        *,
        min_confidence: float = 0.70,
        max_tokens_out: int = 32000,
        timeout: float = 900.0,
    ):
        self.min_confidence = min_confidence
        self.max_tokens_out = max_tokens_out
        self.timeout = timeout

    async def synthesize_epoch(
        self,
        epoch_id: str,
        epoch_order: int,
        *,
        apply: bool = True,
    ) -> dict[str, Any]:
        logger.info(
            "GlobalSynthesizer: epoch_order=%d apply=%s min_conf=%.2f",
            epoch_order,
            apply,
            self.min_confidence,
        )

        dossiers = await self._load_dossiers(epoch_id)
        if not dossiers:
            logger.warning("No dossiers for epoch_id=%s", epoch_id)
            return {
                "status": "no_dossiers",
                "clusters": [],
                "applied": False,
                "dossier_count": 0,
            }

        # Sanity log
        cultures = {c for d in dossiers for c in d.get("cultures") or []}
        logger.info(
            "GlobalSynthesizer: %d dossiers across %d cultures",
            len(dossiers),
            len(cultures),
        )

        packet = self._build_packet(dossiers)
        logger.info(
            "GlobalSynthesizer: prompt packet %d chars (~%d tokens)",
            len(packet),
            len(packet) // 4,
        )

        result = await call_minimax(
            user_prompt=packet,
            system_prompt=_SYNTH_SYSTEM_PROMPT,
            temperature=0.15,
            max_tokens=self.max_tokens_out,
            timeout=self.timeout,
            json_mode=True,
        )
        if not result or "clusters" not in result:
            logger.error("Synthesizer LLM returned empty/invalid: %s", str(result)[:400])
            return {
                "status": "llm_failed",
                "clusters": [],
                "applied": False,
                "dossier_count": len(dossiers),
            }

        clusters = self._validate_clusters(result.get("clusters") or [], dossiers)
        summary_text = (result.get("summary") or "").strip()

        # Second pass: any deities that landed in the "Unclustered
        # (review)" bucket get sent back with the cluster catalog for
        # placement. This catches real deities the first pass missed
        # without re-running the entire 36K-token analysis.
        clusters = await self._placement_pass(clusters, dossiers)

        # Persist a "synthesis" proposal row for audit/history
        await self._persist_proposal(
            epoch_id=epoch_id,
            summary=summary_text,
            clusters=clusters,
        )

        applied = False
        apply_stats: dict[str, Any] = {}
        if apply:
            apply_stats = await self._apply_clusters(
                epoch_id=epoch_id,
                clusters=clusters,
                dossiers=dossiers,
            )
            applied = True

        return {
            "status": "ok",
            "summary": summary_text,
            "clusters": clusters,
            "cluster_count": len(clusters),
            "auto_applied_count": sum(
                1 for c in clusters if c.get("confidence", 0) >= self.min_confidence
            ),
            "applied": applied,
            "apply_stats": apply_stats,
            "dossier_count": len(dossiers),
        }

    # ----- data loading -----

    async def _load_dossiers(self, epoch_id: str) -> list[dict[str, Any]]:
        async with async_session_factory() as s:
            rows = (
                await s.execute(
                    text(
                        """
                        SELECT id, actor_name, normalized_name,
                               cultures, event_count, actions,
                               co_occurring_actors,
                               earliest_source_title,
                               earliest_date_start,
                               earliest_date_end,
                               earliest_date_label,
                               characteristics_md,
                               current_archetype_id,
                               current_archetype_name,
                               canonical_actor_id
                        FROM deity_dossiers
                        WHERE epoch_id = :eid
                        ORDER BY event_count DESC, actor_name ASC
                        """
                    ),
                    {"eid": epoch_id},
                )
            ).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": str(r[0]),
                    "actor_name": r[1],
                    "normalized_name": r[2],
                    "cultures": list(r[3] or []),
                    "event_count": int(r[4] or 0),
                    "actions": list(r[5] or []),
                    "co_occurring_actors": dict(r[6] or {}),
                    "earliest_source_title": r[7],
                    "earliest_date_start": r[8],
                    "earliest_date_end": r[9],
                    "earliest_date_label": r[10],
                    "characteristics_md": r[11] or "",
                    "current_archetype_id": str(r[12]) if r[12] else None,
                    "current_archetype_name": r[13],
                    "canonical_actor_id": str(r[14]) if r[14] else None,
                }
            )
        return out

    # ----- packet building -----

    def _build_packet(self, dossiers: list[dict[str, Any]]) -> str:
        lines: list[str] = [
            f"TOTAL DEITIES: {len(dossiers)}",
            "",
            "Each entry below is a compact signature: name, cultures it "
            "appears in this epoch, earliest attested source, top "
            "distinctive actions (verb + outcome), top co-occurring "
            "actors (who it interacts with), and a one-paragraph "
            "essence. Use these signatures to cluster deities into "
            "cross-cultural archetypes per the system instructions.",
            "",
        ]
        for d in dossiers:
            lines.append("---")
            lines.append(f"NAME: {d['actor_name']}")
            if d.get("cultures"):
                lines.append(f"Cultures: {', '.join(d['cultures'])}")
            if d.get("current_archetype_name"):
                lines.append(
                    f"Currently grouped under: {d['current_archetype_name']}"
                )
            era = self._format_era(d)
            if era:
                lines.append(f"Earliest source: {era}")

            actions = d.get("actions") or []
            if actions:
                top_actions = actions[:8]
                action_bits: list[str] = []
                for a in top_actions:
                    verb = (a.get("verb") or "").strip()
                    outcome = (a.get("outcome") or "").strip()
                    objs = ", ".join(a.get("objects") or [])
                    frag = f"{verb}"
                    if outcome:
                        frag += f" → {outcome}"
                    if objs:
                        frag += f" (obj: {objs})"
                    if frag.strip() != "→":
                        action_bits.append(frag)
                if action_bits:
                    lines.append(
                        "Actions: " + "; ".join(action_bits)
                    )

            co = d.get("co_occurring_actors") or {}
            if co:
                top_co = sorted(
                    co.items(), key=lambda kv: -int(kv[1] or 0)
                )[:6]
                lines.append(
                    "Co-occurs with: "
                    + ", ".join(f"{n} ({c})" for n, c in top_co)
                )

            essence = _first_n_chars(d.get("characteristics_md") or "", 500)
            if essence:
                lines.append(f"Essence: {essence}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(
            "Produce the unified clustering now. Every deity above must "
            "appear in exactly one cluster. Prefer cross-cultural merges "
            "supported by distinctive shared actions or relational "
            "overlap. Output JSON only per the required schema."
        )
        return "\n".join(lines)

    def _format_era(self, d: dict[str, Any]) -> str | None:
        title = d.get("earliest_source_title")
        if not title:
            return None
        ds = d.get("earliest_date_start")
        de = d.get("earliest_date_end")
        if ds is not None and de is not None and ds != de:
            era = f"{ds}–{de}"
        elif ds is not None:
            era = str(ds)
        else:
            era = d.get("earliest_date_label") or "?"
        return f"{title} ({era})"

    # ----- validation -----

    def _validate_clusters(
        self,
        raw_clusters: list[dict[str, Any]],
        dossiers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize LLM output and resolve duplicate memberships.

        The LLM sometimes assigns the same deity to multiple clusters
        (e.g., Quetzalcoatl in both "Feathered Serpent" and "Shining
        Ones"). We resolve this by giving each deity to the highest-
        confidence cluster that claims it; on ties, the cluster with
        the most distinctive evidence (more evidence entries) wins;
        on further ties, the cluster listed first.
        """
        all_names = {d["actor_name"] for d in dossiers}

        staged: list[dict[str, Any]] = []
        for idx, c in enumerate(raw_clusters):
            if not isinstance(c, dict):
                continue
            name = (c.get("archetype_name") or "").strip()
            raw_members = [
                m for m in (c.get("members") or []) if m in all_names
            ]
            if not name or not raw_members:
                continue
            staged.append(
                {
                    "order": idx,
                    "archetype_name": name,
                    "role_description": (c.get("role_description") or "").strip(),
                    "confidence": float(c.get("confidence") or 0.0),
                    "members": sorted(set(raw_members)),
                    "rationale": (c.get("rationale") or "").strip(),
                    "evidence": list(c.get("evidence") or []),
                }
            )

        # Rank clusters: higher confidence wins, then more evidence,
        # then original order.
        staged.sort(
            key=lambda x: (
                -x["confidence"],
                -len(x.get("evidence") or []),
                x["order"],
            )
        )

        claimed: set[str] = set()
        for c in staged:
            kept = [m for m in c["members"] if m not in claimed]
            c["members"] = kept
            claimed.update(kept)

        # Drop any cluster that ended up with zero members, restore
        # original cluster ordering.
        cleaned = [c for c in staged if c["members"]]
        cleaned.sort(key=lambda x: x["order"])
        for c in cleaned:
            c.pop("order", None)

        seen = claimed
        missing = sorted(all_names - seen)
        if missing:
            cleaned.append(
                {
                    "archetype_name": "Unclustered (review)",
                    "role_description": "Deities the synthesis did not place.",
                    "confidence": 0.0,
                    "members": missing,
                    "rationale": (
                        "The global synthesis did not assign these members to "
                        "a cluster. Kept separate for manual review."
                    ),
                    "evidence": [],
                }
            )
        return cleaned

    async def _placement_pass(
        self,
        clusters: list[dict[str, Any]],
        dossiers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Try to place any leftover 'Unclustered' members into existing
        clusters with a targeted follow-up LLM call.
        """
        leftover = next(
            (c for c in clusters if c.get("archetype_name") == "Unclustered (review)"),
            None,
        )
        if not leftover or not leftover.get("members"):
            return clusters

        dossier_by_name = {d["actor_name"]: d for d in dossiers}
        missing_dossiers = [
            dossier_by_name[n]
            for n in leftover["members"]
            if n in dossier_by_name
        ]
        if not missing_dossiers:
            return clusters

        catalog_lines = ["EXISTING CLUSTERS:"]
        for c in clusters:
            if c["archetype_name"] == "Unclustered (review)":
                continue
            catalog_lines.append(
                f"- {c['archetype_name']}: {c.get('role_description') or ''} "
                f"[members: {', '.join(c['members'][:10])}]"
            )

        dossier_lines = ["", "DEITIES TO PLACE:"]
        for d in missing_dossiers:
            dossier_lines.append("---")
            dossier_lines.append(f"NAME: {d['actor_name']}")
            if d.get("cultures"):
                dossier_lines.append(f"Cultures: {', '.join(d['cultures'])}")
            era = self._format_era(d)
            if era:
                dossier_lines.append(f"Earliest source: {era}")
            actions = d.get("actions") or []
            if actions:
                bits: list[str] = []
                for a in actions[:6]:
                    verb = (a.get("verb") or "").strip()
                    outcome = (a.get("outcome") or "").strip()
                    if verb or outcome:
                        bits.append(f"{verb} → {outcome}".strip(" →"))
                if bits:
                    dossier_lines.append("Actions: " + "; ".join(bits))
            essence = _first_n_chars(d.get("characteristics_md") or "", 300)
            if essence:
                dossier_lines.append(f"Essence: {essence}")

        system = """You are placing unclustered deities into an existing
archetype taxonomy. For each deity, output either:

  - "cluster_name": an EXACT name from the EXISTING CLUSTERS list
    (to merge this deity into that archetype), OR
  - "cluster_name": "<New Archetype Name>" AND is_new: true if the
    deity genuinely does not fit any existing cluster — only use this
    when confidence that it's a new archetype is >= 0.70.

If you cannot reasonably place a deity (it's a generic noun like
"moon" or "serpent" with no distinctive profile, or it's a non-deity
entity that leaked from extraction), use cluster_name: "SKIP".

Output strict JSON:

{
  "placements": [
    {"name": "DeityName", "cluster_name": "...", "is_new": false,
     "confidence": 0.0-1.0, "rationale": "one sentence"},
    ...
  ]
}
"""
        user = "\n".join(catalog_lines + dossier_lines + [
            "",
            "Output strict JSON per the required schema.",
        ])

        try:
            result = await call_minimax(
                user_prompt=user,
                system_prompt=system,
                temperature=0.15,
                max_tokens=12000,
                timeout=600.0,
                json_mode=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Placement pass failed; keeping unclustered bucket.")
            return clusters

        placements = (result.get("placements") if isinstance(result, dict) else []) or []
        if not placements:
            return clusters

        by_name = {c["archetype_name"]: c for c in clusters}
        placed_names: set[str] = set()
        logger.info(
            "Placement pass: %d placements returned by LLM", len(placements)
        )

        for p in placements:
            if not isinstance(p, dict):
                continue
            deity = (p.get("name") or "").strip()
            target = (p.get("cluster_name") or "").strip()
            if not deity or not target or deity not in leftover["members"]:
                continue
            conf = float(p.get("confidence") or 0.0)
            if target.upper() == "SKIP":
                placed_names.add(deity)
                continue
            rationale = (p.get("rationale") or "").strip()
            if target in by_name and not p.get("is_new"):
                tgt = by_name[target]
                tgt["members"] = sorted(set(tgt["members"] + [deity]))
                if rationale:
                    tgt.setdefault("evidence", []).append(
                        f"placement: {deity} — {rationale}"
                    )
                placed_names.add(deity)
            elif p.get("is_new") and conf >= 0.70:
                new = {
                    "archetype_name": target,
                    "role_description": rationale,
                    "confidence": conf,
                    "members": [deity],
                    "rationale": rationale,
                    "evidence": [f"placement: {rationale}"],
                }
                clusters.insert(-1, new)  # insert before "Unclustered (review)"
                by_name[target] = new
                placed_names.add(deity)

        leftover["members"] = sorted(
            m for m in leftover["members"] if m not in placed_names
        )
        if not leftover["members"]:
            clusters = [c for c in clusters if c is not leftover]
        logger.info(
            "Placement pass: %d/%d deities placed; %d still unclustered",
            len(placed_names),
            len(missing_dossiers),
            len(leftover["members"]),
        )
        return clusters

    async def _persist_proposal(
        self,
        epoch_id: str,
        summary: str,
        clusters: list[dict[str, Any]],
    ) -> None:
        groups_for_proposal = [
            {
                "proposed_archetype_name": c["archetype_name"],
                "role_description": c.get("role_description") or "",
                "members": c["members"],
                "rationale": c.get("rationale") or "",
                "evidence": c.get("evidence") or [],
                "confidence": c.get("confidence", 0.0),
                "auto_apply_eligible": (
                    c.get("confidence", 0.0) >= self.min_confidence
                ),
            }
            for c in clusters
        ]
        async with async_session_factory() as s:
            src_ids = (
                await s.execute(
                    text(
                        """
                        SELECT DISTINCT current_archetype_id::text
                        FROM deity_dossiers
                        WHERE epoch_id = :eid
                          AND current_archetype_id IS NOT NULL
                        """
                    ),
                    {"eid": epoch_id},
                )
            ).all()
            src_ids_list = [r[0] for r in src_ids if r[0]]

            src_names = (
                await s.execute(
                    text(
                        """
                        SELECT archetype_name
                        FROM archetype_registry
                        WHERE id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {"ids": src_ids_list},
                )
            ).all()
            src_names_list = [r[0] for r in src_names]

            overall_conf = (
                sum(c.get("confidence", 0.0) for c in clusters) / len(clusters)
                if clusters
                else 0.0
            )
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
                        'synthesis',
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
                    "source_ids": json.dumps(src_ids_list),
                    "source_names": json.dumps(src_names_list),
                    "groups": json.dumps(groups_for_proposal),
                    "rationale": summary or "(no summary)",
                    "confidence": overall_conf,
                    "model_name": settings.minimax_model,
                },
            )
            await s.commit()

    # ----- auto-apply -----

    async def _apply_clusters(
        self,
        epoch_id: str,
        clusters: list[dict[str, Any]],
        dossiers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Rewrite archetype_registry + rewire event_clusters.

        For each cluster with confidence >= min_confidence:
          - upsert archetype_registry by name (create if missing,
            merge AKA/canonical_ids if present)
          - rewire event_clusters whose contributing actors match

        Lower-confidence clusters are preserved in the `proposed_groups`
        payload but NOT applied; their members stay in whatever
        archetype they were in before.
        """
        # Build normalized-name → canonical_actor_id lookup from dossiers
        # themselves (we already resolved these during dossier build).
        cid_by_norm: dict[str, str] = {}
        ev_by_norm: dict[str, int] = {}
        for d in dossiers:
            if d.get("canonical_actor_id"):
                cid_by_norm[d["normalized_name"]] = d["canonical_actor_id"]
            ev_by_norm[d["normalized_name"]] = d.get("event_count", 0)

        touched_archetype_ids: set[str] = set()
        touched_event_clusters = 0
        applied_clusters = 0

        async with async_session_factory() as s:
            # Collect the set of all member-norm names that WILL be
            # moved into new archetypes, so we can strip them from
            # their old archetypes.
            moved_norms: set[str] = set()
            for c in clusters:
                if c.get("confidence", 0.0) < self.min_confidence:
                    continue
                for m in c.get("members") or []:
                    moved_norms.add(_norm(m))

            for c in clusters:
                if c.get("confidence", 0.0) < self.min_confidence:
                    continue
                name = c["archetype_name"].strip()
                role = (c.get("role_description") or "").strip()
                members = list(c.get("members") or [])
                if not name or not members:
                    continue
                member_norms = {_norm(m) for m in members}
                member_cids = sorted(
                    {
                        cid_by_norm[n]
                        for n in member_norms
                        if n in cid_by_norm
                    }
                )

                # Upsert archetype_registry by name
                tgt_row = (
                    await s.execute(
                        text(
                            """
                            SELECT id, also_known_as, canonical_ids
                            FROM archetype_registry
                            WHERE archetype_name = :nm
                            """
                        ),
                        {"nm": name},
                    )
                ).first()
                if tgt_row:
                    tgt_id = str(tgt_row[0])
                    merged_aka = sorted(set(list(tgt_row[1] or []) + members))
                    merged_cids = sorted(
                        {str(x) for x in (tgt_row[2] or [])} | set(member_cids)
                    )
                    await s.execute(
                        text(
                            """
                            UPDATE archetype_registry
                            SET also_known_as = :aka,
                                canonical_ids = CAST(:cids AS uuid[]),
                                role_description = COALESCE(
                                    NULLIF(:role, ''), role_description
                                ),
                                updated_at = now()
                            WHERE id = :id
                            """
                        ),
                        {
                            "id": tgt_id,
                            "aka": merged_aka,
                            "cids": merged_cids,
                            "role": role,
                        },
                    )
                else:
                    inserted = (
                        await s.execute(
                            text(
                                """
                                INSERT INTO archetype_registry (
                                    archetype_name, role_description,
                                    entity_type, also_known_as,
                                    canonical_ids
                                ) VALUES (
                                    :nm, :role, 'actor',
                                    :aka, CAST(:cids AS uuid[])
                                ) RETURNING id
                                """
                            ),
                            {
                                "nm": name,
                                "role": role or None,
                                "aka": members,
                                "cids": member_cids,
                            },
                        )
                    ).first()
                    tgt_id = str(inserted[0])

                touched_archetype_ids.add(tgt_id)

                # Rewire event_clusters whose contributing actors match
                # at least one of this cluster's members.
                ev_rows = (
                    await s.execute(
                        text(
                            """
                            SELECT id, contributing_cultures
                            FROM event_clusters
                            """
                        )
                    )
                ).all()
                for ev_id, ccultures in ev_rows:
                    names_in_event: set[str] = set()
                    if isinstance(ccultures, dict):
                        for _k, actors in ccultures.items():
                            if isinstance(actors, list):
                                for a in actors:
                                    names_in_event.add(_norm(str(a)))
                            elif isinstance(actors, str):
                                names_in_event.add(_norm(actors))
                    if names_in_event & member_norms:
                        await s.execute(
                            text(
                                """
                                UPDATE event_clusters
                                SET archetype_registry_id = :tid,
                                    primary_archetype_name = :pn
                                WHERE id = :eid
                                """
                            ),
                            {
                                "tid": tgt_id,
                                "pn": name,
                                "eid": str(ev_id),
                            },
                        )
                        touched_event_clusters += 1

                applied_clusters += 1

            # Strip moved members from OLD archetypes (they're no longer
            # in the old cluster since the new target claimed them).
            if moved_norms:
                old_rows = (
                    await s.execute(
                        text(
                            """
                            SELECT id, also_known_as, canonical_ids
                            FROM archetype_registry
                            WHERE id != ALL(CAST(:keep AS uuid[]))
                            """
                        ),
                        {"keep": sorted(touched_archetype_ids)},
                    )
                ).all()
                for oid, aka, cids in old_rows:
                    akal = list(aka or [])
                    cidl = [str(x) for x in (cids or [])]
                    new_aka = [a for a in akal if _norm(a) not in moved_norms]
                    if new_aka == akal:
                        continue
                    # Keep only canonical_ids whose canonical_actors name
                    # normalizes to one still in the new AKA list.
                    keep_cids: list[str] = []
                    for c in cidl:
                        if c in [
                            cid_by_norm.get(_norm(a))
                            for a in new_aka
                        ]:
                            keep_cids.append(c)
                    await s.execute(
                        text(
                            """
                            UPDATE archetype_registry
                            SET also_known_as = :aka,
                                canonical_ids = CAST(:cids AS uuid[]),
                                updated_at = now()
                            WHERE id = :id
                            """
                        ),
                        {
                            "id": str(oid),
                            "aka": new_aka,
                            "cids": sorted(set(keep_cids)),
                        },
                    )

            # Refresh deity_dossiers current_archetype_* denormalization
            await s.execute(
                text(
                    """
                    UPDATE deity_dossiers dd
                    SET current_archetype_id = ar.id,
                        current_archetype_name = ar.archetype_name,
                        updated_at = now()
                    FROM archetype_registry ar
                    WHERE ar.also_known_as && ARRAY[dd.actor_name]
                      AND dd.epoch_id = :eid
                    """
                ),
                {"eid": epoch_id},
            )
            await s.commit()

        return {
            "applied_clusters": applied_clusters,
            "skipped_low_confidence": sum(
                1 for c in clusters if c.get("confidence", 0.0) < self.min_confidence
            ),
            "touched_archetypes": len(touched_archetype_ids),
            "rewired_event_clusters": touched_event_clusters,
        }


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _first_n_chars(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut + "…"
