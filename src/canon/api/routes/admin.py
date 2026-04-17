from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_score import CanonScore
from src.canon.models.change_event import ChangeEvent, CanonUpdateTarget
from src.canon.models.extracted_hint import ExtractedHint
from src.canon.models.motif import Motif, MotifAssignment
from src.canon.models.narration_packet import NarrationPacket
from src.canon.models.world_packet import WorldPacket
from src.canon.schemas.canonical import SynthesisRequest, SynthesisResponse
from src.canon.services.canon_synth import CanonSynthService
from src.canon.services.canon_update import CanonUpdateService
from src.canon.services.change_detect import ChangeDetectService
from src.canon.services.chapter_builder import ChapterBuilderService
from src.canon.services.impact_resolver import ImpactResolver
from src.canon.services.knowledge_prep import KnowledgePrepService
from src.canon.services.merge_service import MergeService
from src.canon.services.motif_service import MotifService
from src.canon.services.narration_builder import NarrationBuilderService
from src.canon.services.scoring_service import ScoringService
from src.canon.services.evidence_bundle_builder import EvidenceBundleBuilder
from src.canon.services.narrative_synthesizer import NarrativeSynthesizer
from src.canon.services.narrative_v2 import NarrativePipelineV2
from src.canon.services.source_record_synth import SourceRecordSynthService
from src.canon.services.world_packet_builder import WorldPacketBuilderService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ensure-epochs", response_model=dict)
async def ensure_epochs(session: AsyncSession = Depends(get_session)):
    """Create the default epoch set if not present. Fast, no AI required.
    This is the first step to fix 'No epochs found' in the UI."""
    svc = ChapterBuilderService()
    result = await svc.run_ensure_epochs_only(session)
    await session.commit()
    return result


@router.post("/run-synthesis", response_model=SynthesisResponse)
async def run_synthesis(
    request: SynthesisRequest = SynthesisRequest(),
    session: AsyncSession = Depends(get_session),
):
    """Trigger selected canon synthesis phases. All phases default to False — explicitly
    set each flag you want to run. This prevents accidental full-pipeline triggering."""
    result = SynthesisResponse()

    # Phase 1: Extract hints from segments/statements (bounded batch)
    if request.run_extraction:
        svc = KnowledgePrepService()
        result.extraction = await svc.run_full_extraction(session)
        await session.commit()

    # Phase 2: Synthesize canonical entities from hints
    if request.run_synthesis:
        svc = CanonSynthService()
        result.synthesis = await svc.run_full_synthesis(session)
        await session.commit()

    # Phase 3: Build/refresh epochs and chapters
    if request.run_chapters:
        svc = ChapterBuilderService()
        result.chapters = await svc.run_full_build(session)
        await session.commit()

    if request.run_motifs:
        svc = MotifService()
        result.motifs = await svc.run_full_motif_assignment(session)
        await session.commit()

    if request.run_scoring:
        svc = ScoringService()
        result.scoring = await svc.run_full_scoring(session)
        await session.commit()

    if request.run_narration:
        svc = NarrationBuilderService()
        result.narration = await svc.run_full_build(session)
        await session.commit()

    if request.run_world_packets:
        svc = WorldPacketBuilderService()
        result.world_packets = await svc.run_full_build(session)
        await session.commit()

    if request.run_change_detection:
        svc = ChangeDetectService()
        result.change_detection = await svc.run_full_detection(session)
        await session.commit()

    if request.run_impact_resolution:
        svc = ImpactResolver()
        result.impact_resolution = await svc.resolve_all_pending(session)
        await session.commit()

    if request.run_canon_updates:
        svc = CanonUpdateService()
        result.canon_updates = await svc.process_all_pending(session)
        await session.commit()

    if request.run_evidence_bundles:
        svc = EvidenceBundleBuilder()
        result.evidence_bundles = await svc.build_all(session)
        await session.commit()

    if request.run_entity_resolution:
        svc = MergeService()
        result.entity_resolution = await svc.run_llm_entity_resolution(session)
        await session.commit()

    if request.run_narrative:
        svc = NarrativeSynthesizer()
        await svc.plan_all_epochs(session)
        result.narrative = await svc.run_full_synthesis(session)

    return result


@router.post("/run-source-extraction", response_model=dict)
async def run_source_extraction(
    batch_size: int = 30,
    max_records: int = 300,
    after_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Extract canonical hints from source record metadata (title, culture, dates).
    More efficient than segment-level extraction — one AI call per batch of records.
    Call repeatedly with the returned next_record_id to process all records."""
    import uuid as _uuid
    svc = SourceRecordSynthService()
    after_uuid = _uuid.UUID(after_id) if after_id else None
    result = await svc.run_extraction_batch(
        session,
        batch_size=batch_size,
        max_records=max_records,
        after_id=after_uuid,
    )
    await session.commit()
    return result


@router.post("/run-full-pipeline", response_model=SynthesisResponse)
async def run_full_pipeline(session: AsyncSession = Depends(get_session)):
    """Run extraction → synthesis → chapters in sequence.
    Extraction is bounded (500 segments max per call). Call repeatedly for full coverage."""
    return await run_synthesis(
        SynthesisRequest(
            run_extraction=True,
            run_synthesis=True,
            run_chapters=True,
            run_motifs=False,
            run_scoring=False,
            run_narration=False,
            run_world_packets=False,
        ),
        session,
    )


@router.post("/run-alias-merges")
async def run_alias_merges(session: AsyncSession = Depends(get_session)):
    """Run Level 1 alias merges across all entity types."""
    svc = MergeService()
    result = await svc.run_alias_merges(session)
    await session.commit()
    return result


@router.post("/run-alias-equivalences")
async def run_alias_equivalences(session: AsyncSession = Depends(get_session)):
    """Populate entity_equivalences from the alias dictionary.

    Creates soft equivalence links between entities that are known aliases
    (e.g., Prajapati = Brahma, Enki = Ea). Does NOT require canon scores.
    """
    svc = MergeService()
    result = await svc.run_alias_equivalences(session)
    await session.commit()
    return result


@router.post("/plan-narrative")
async def plan_narrative(
    epoch_orders: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Phase 1: Use DeepSeek to plan unified thematic chapters for each epoch.

    This creates story_outlines — the 'table of contents' for the narrative.
    Run this BEFORE /admin/run-narrative.

    Args:
        epoch_orders: comma-separated epoch_order values (e.g. "0,1,2,3"), omit for all
    """
    orders = [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else None
    svc = NarrativeSynthesizer()
    result = await svc.plan_all_epochs(session, epoch_orders=orders)
    return result


@router.post("/run-narrative")
async def run_narrative(
    epoch_orders: str | None = None,
    skip_existing: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """Legacy endpoint — now runs the full 3-pass pipeline."""
    orders = [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else None
    svc = NarrativeSynthesizer()
    result = await svc.run_full_pipeline(
        session,
        epoch_orders=orders,
        skip_existing=skip_existing,
        passes="1,2,3",
    )
    return result


@router.post("/run-narrative-pipeline")
async def run_narrative_pipeline(
    epoch_orders: str | None = None,
    skip_existing: bool = True,
    passes: str = "1,2,3",
    session: AsyncSession = Depends(get_session),
):
    """Three-pass narrative pipeline — runs in background, returns immediately.

    Args:
        epoch_orders: comma-separated epoch_order values (e.g. "0,1,2,3"), omit for all
        skip_existing: skip cultures/chapters that already have output (default True)
        passes: comma-separated pass numbers to run (e.g. "1", "1,2", "1,2,3")
            Pass 1: Generate per-culture narratives
            Pass 2: Extract event skeletons
            Pass 3: Merge into unified narrative
    """
    import asyncio

    orders = [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else None

    async def _run() -> None:
        try:
            svc = NarrativeSynthesizer()
            result = await svc.run_full_pipeline(
                session,
                epoch_orders=orders,
                skip_existing=skip_existing,
                passes=passes,
            )
            logger.info("Narrative pipeline complete: %s", result)
        except Exception:
            logger.exception("Narrative pipeline failed")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "epoch_orders": orders,
        "passes": passes,
        "message": "Pipeline running in background. Check /admin/narrative-pipeline-status for progress.",
    }


@router.post("/run-narrative-v2")
async def run_narrative_v2(
    epoch_orders: str | None = None,
    chapter_numbers: str | None = None,
    wipe: bool = False,
    max_cultures: int | None = None,
    phase: str = "full",
    session: AsyncSession = Depends(get_session),
):
    """V2 narrative pipeline — deterministic merge architecture.

    Runs in background, returns immediately. See docs/NARRATIVE_PIPELINE_V2.plan.md.

    Args:
        epoch_orders: comma-separated epoch_order values (e.g. "0,1,2"), omit for all
        chapter_numbers: comma-separated chapter numbers to process (e.g. "1" or
            "1,2"); omit for all chapters of each epoch
        wipe: if True, delete culture_narratives / story_chapters / clusters for
            the targeted scope before regenerating (epoch-wide unless
            chapter_numbers is set — in which case only those chapters are wiped).
            Ignored when phase='render_only'.
        max_cultures: cap cultures per chapter (None = all)
        phase: 'full' runs Phase A → B → C. 'render_only' skips A+B and
            re-renders every chapter using the existing event_clusters + the
            current archetype_registry. Use after approving archetype merge
            proposals.
    """
    import asyncio

    orders = (
        [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else None
    )
    chapters = (
        [int(x.strip()) for x in chapter_numbers.split(",")] if chapter_numbers else None
    )

    async def _run() -> None:
        try:
            # Create a fresh session for the background task; get_session() depends
            # on request lifecycle which ends when this handler returns.
            from src.canon.database import async_session_factory

            async with async_session_factory() as bg_session:
                svc = NarrativePipelineV2()
                result = await svc.run(
                    bg_session,
                    epoch_orders=orders,
                    chapter_numbers=chapters,
                    wipe=wipe,
                    max_cultures=max_cultures,
                    phase=phase,
                )
                logger.info("V2 pipeline complete: %s", result)
        except Exception:
            logger.exception("V2 pipeline failed")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "epoch_orders": orders,
        "chapter_numbers": chapters,
        "wipe": wipe,
        "max_cultures": max_cultures,
        "phase": phase,
        "message": "V2 pipeline running in background. Monitor logs for progress.",
    }


# ---------------------------------------------------------------------------
# Deity Dossier + Archetype merge proposal pipeline
# ---------------------------------------------------------------------------


@router.post("/build-deity-dossiers")
async def build_deity_dossiers(
    epoch_orders: str | None = None,
    wipe: bool = False,
    max_actors: int | None = None,
    skip_llm: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Build per-deity evidence dossiers for the given epoch(s).

    Runs in the background. For each unique actor name in
    `culture_atomic_events` within each epoch, aggregates actions +
    co-occurrences, resolves a canonical actor, finds the earliest
    attested source, and calls MiniMax m2.5 to write a 2-3 paragraph
    evidence-grounded dossier.
    """
    import asyncio

    from sqlalchemy import text as sql_text

    from src.canon.database import async_session_factory
    from src.canon.services.deity_dossier import DossierBuilder

    orders = (
        [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else [0]
    )

    # Resolve epoch ids now (cheap) so the background task doesn't depend
    # on the request-scoped session.
    async with async_session_factory() as s:
        rows = (
            await s.execute(
                sql_text(
                    "SELECT id, epoch_order, title FROM canonical_epochs "
                    "WHERE epoch_order = ANY(:orders) AND is_current = true"
                ),
                {"orders": orders},
            )
        ).all()
    epoch_tuples = [(str(r[0]), r[1], r[2]) for r in rows]

    async def _run() -> None:
        try:
            builder = DossierBuilder(
                max_actors=max_actors,
                llm_concurrency=4,
                skip_llm=skip_llm,
            )
            for eid, eorder, etitle in epoch_tuples:
                logger.info(
                    "Deity dossier build: epoch %d — %s", eorder, etitle
                )
                result = await builder.build_for_epoch(
                    eid, eorder, wipe=wipe
                )
                logger.info("Deity dossier build complete: %s", result)
        except Exception:
            logger.exception("Deity dossier build failed")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "epoch_orders": orders,
        "wipe": wipe,
        "max_actors": max_actors,
        "skip_llm": skip_llm,
        "epochs_resolved": len(epoch_tuples),
        "message": "Dossier build running in background. Monitor logs for progress.",
    }


@router.post("/propose-archetype-remerges")
async def propose_archetype_remerges(
    epoch_orders: str | None = None,
    wipe_pending: bool = True,
    min_members: int = 2,
    session: AsyncSession = Depends(get_session),
):
    """Ask MiniMax m2.5 to audit each archetype and propose splits/merges.

    Runs in the background. Uses the dossiers populated by
    `/admin/build-deity-dossiers`, so that endpoint must be run first.
    Proposals land in `archetype_merge_proposals` with status='pending'
    and are NOT applied until a human approves via
    `/admin/archetype-proposals/{id}/approve`.
    """
    import asyncio

    from sqlalchemy import text as sql_text

    from src.canon.database import async_session_factory
    from src.canon.services.deity_dossier import ProposalGenerator

    orders = (
        [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else [0]
    )
    async with async_session_factory() as s:
        rows = (
            await s.execute(
                sql_text(
                    "SELECT id, epoch_order, title FROM canonical_epochs "
                    "WHERE epoch_order = ANY(:orders) AND is_current = true"
                ),
                {"orders": orders},
            )
        ).all()
    epoch_tuples = [(str(r[0]), r[1], r[2]) for r in rows]

    async def _run() -> None:
        try:
            gen = ProposalGenerator(llm_concurrency=3, min_members=min_members)
            for eid, eorder, etitle in epoch_tuples:
                logger.info("Proposer: epoch %d — %s", eorder, etitle)
                result = await gen.propose_for_epoch(
                    eid, eorder, wipe_pending=wipe_pending
                )
                logger.info("Proposer complete: %s", result)
        except Exception:
            logger.exception("Proposer failed")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "epoch_orders": orders,
        "wipe_pending": wipe_pending,
        "min_members": min_members,
        "epochs_resolved": len(epoch_tuples),
        "message": (
            "Proposal generation running in background. Monitor logs."
        ),
    }


@router.post("/synthesize-archetypes")
async def synthesize_archetypes(
    epoch_orders: str | None = None,
    apply: bool = True,
    min_confidence: float = 0.70,
    session: AsyncSession = Depends(get_session),
):
    """Global cross-cultural archetype synthesis.

    Unlike `/propose-archetype-remerges` (which only splits *within*
    existing archetypes), this endpoint sends ALL dossiers for the
    epoch to MiniMax in one shot and asks for a fresh global clustering
    based on distinctive shared actions, overlapping relational
    networks, earliest-source alignment, and characteristic essence.

    With `apply=true` (default), clusters at confidence >= min_confidence
    are written back to `archetype_registry` and `event_clusters` are
    rewired. With `apply=false`, a "synthesis" proposal row is still
    persisted for UI review, but no registry changes happen.

    Requires dossiers to exist (run `/admin/build-deity-dossiers` first).
    """
    import asyncio

    from sqlalchemy import text as sql_text

    from src.canon.database import async_session_factory
    from src.canon.services.deity_dossier import GlobalArchetypeSynthesizer

    orders = (
        [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else [0]
    )
    async with async_session_factory() as s:
        rows = (
            await s.execute(
                sql_text(
                    "SELECT id, epoch_order, title FROM canonical_epochs "
                    "WHERE epoch_order = ANY(:orders) AND is_current = true"
                ),
                {"orders": orders},
            )
        ).all()
    epoch_tuples = [(str(r[0]), r[1], r[2]) for r in rows]

    async def _run() -> None:
        try:
            synth = GlobalArchetypeSynthesizer(min_confidence=min_confidence)
            for eid, eorder, etitle in epoch_tuples:
                logger.info(
                    "Synthesizer: epoch %d — %s (apply=%s, min_conf=%.2f)",
                    eorder,
                    etitle,
                    apply,
                    min_confidence,
                )
                result = await synth.synthesize_epoch(
                    eid, eorder, apply=apply
                )
                logger.info(
                    "Synthesizer complete: clusters=%d, auto_applied=%d, apply_stats=%s",
                    result.get("cluster_count", 0),
                    result.get("auto_applied_count", 0),
                    result.get("apply_stats", {}),
                )
        except Exception:
            logger.exception("Synthesizer failed")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "epoch_orders": orders,
        "apply": apply,
        "min_confidence": min_confidence,
        "epochs_resolved": len(epoch_tuples),
        "message": (
            "Global synthesis running in background. Watch logs or poll "
            "/admin/deity-dossier-status for proposal_counts.synthesis."
        ),
    }


@router.post("/archetype-proposals/{proposal_id}/approve")
async def approve_archetype_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Apply a proposal: rewrite archetype_registry + rewire event_clusters.

    For a KEEP proposal: nothing to change, just mark applied.

    For a SPLIT proposal: for each proposed_group,
      - If group has 1 member with the same name as the source archetype
        → no-op.
      - Else create a new archetype_registry row (or reuse if an archetype
        with that proposed name already exists), set
        also_known_as = group.members, move matching canonical_ids across
        from the source archetype.
      - event_clusters whose contributing actors match the group's member
        names get their archetype_registry_id / primary_archetype_name
        rewired.
      - If the source archetype ends up empty (no AKAs left), clear its
        also_known_as but keep the row (it may still be referenced).
    """
    from sqlalchemy import text as sql_text

    # Load the proposal
    row = (
        await session.execute(
            sql_text(
                """
                SELECT id, epoch_id, source_archetype_ids,
                       source_archetype_names, proposal_kind, proposed_groups,
                       status
                FROM archetype_merge_proposals WHERE id = :pid
                """
            ),
            {"pid": proposal_id},
        )
    ).first()
    if not row:
        raise HTTPException(404, "Proposal not found")
    if row[6] not in ("pending", "rejected"):
        raise HTTPException(
            400, f"Proposal is already {row[6]}; nothing to apply"
        )

    (
        _pid,
        _eid,
        source_ids,
        source_names,
        kind,
        groups,
        _status,
    ) = row
    source_ids = list(source_ids or [])
    source_names = list(source_names or [])
    groups = list(groups or [])

    applied_notes: list[str] = []

    if kind == "keep":
        applied_notes.append("Proposal was KEEP — no structural changes.")
    else:
        # Build a normalize helper
        import re

        def norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", (s or "").lower())

        # For each source archetype, collect its current AKA and
        # canonical_ids; we'll re-distribute them into the proposed groups.
        src_rows = (
            await session.execute(
                sql_text(
                    """
                    SELECT id, archetype_name, also_known_as, canonical_ids
                    FROM archetype_registry
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"ids": source_ids},
            )
        ).all()

        existing_aka: dict[str, list[str]] = {}
        existing_cids: dict[str, list[str]] = {}
        src_by_id: dict[str, str] = {}
        for r in src_rows:
            sid = str(r[0])
            src_by_id[sid] = r[1]
            existing_aka[sid] = list(r[2] or [])
            existing_cids[sid] = [str(x) for x in (r[3] or [])]

        # Flatten: (normalized_name → canonical_id mapping) per source
        # (we need to know which canonical_id belongs to each AKA — but
        # the registry stores them flat, not paired. So for now assume
        # all canonical_ids from a source archetype get distributed by
        # looking up each AKA member against canonical_actors.)
        # Build a lookup (norm_name → canonical_id) via canonical_actors.
        cid_lookup: dict[str, str] = {}
        all_norms = set()
        for sid, akas in existing_aka.items():
            for a in akas:
                all_norms.add(norm(a))
        if all_norms:
            cid_rows = (
                await session.execute(
                    sql_text(
                        """
                        SELECT id, canonical_name
                        FROM canonical_actors
                        WHERE is_current = true
                        """
                    )
                )
            ).all()
            for cid, cname in cid_rows:
                if not cname:
                    continue
                n = norm(cname)
                if n in all_norms and n not in cid_lookup:
                    cid_lookup[n] = str(cid)

        # Now apply each proposed group
        for g in groups:
            members = g.get("members") or []
            if not members:
                continue
            proposed_name = (g.get("proposed_archetype_name") or "").strip()
            role = (g.get("role_description") or "").strip()
            if not proposed_name:
                continue

            # Canonical IDs for this group's members
            member_cids: list[str] = []
            for m in members:
                c = cid_lookup.get(norm(m))
                if c:
                    member_cids.append(c)

            # Upsert the target archetype by name
            tgt_row = (
                await session.execute(
                    sql_text(
                        """
                        SELECT id, also_known_as, canonical_ids
                        FROM archetype_registry WHERE archetype_name = :nm
                        """
                    ),
                    {"nm": proposed_name},
                )
            ).first()
            if tgt_row:
                tgt_id = str(tgt_row[0])
                merged_aka = sorted(set(list(tgt_row[1] or []) + members))
                merged_cids = list(
                    {str(x) for x in (tgt_row[2] or [])} | set(member_cids)
                )
                await session.execute(
                    sql_text(
                        """
                        UPDATE archetype_registry
                        SET also_known_as = :aka,
                            canonical_ids = CAST(:cids AS uuid[]),
                            role_description = COALESCE(:role, role_description),
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": tgt_id,
                        "aka": merged_aka,
                        "cids": merged_cids,
                        "role": role or None,
                    },
                )
            else:
                inserted = (
                    await session.execute(
                        sql_text(
                            """
                            INSERT INTO archetype_registry (
                                archetype_name, role_description,
                                entity_type, also_known_as, canonical_ids
                            ) VALUES (
                                :nm, :role, 'actor',
                                :aka, CAST(:cids AS uuid[])
                            ) RETURNING id
                            """
                        ),
                        {
                            "nm": proposed_name,
                            "role": role or None,
                            "aka": members,
                            "cids": member_cids,
                        },
                    )
                ).first()
                tgt_id = str(inserted[0])

            # Remove these members from ALL source archetypes (to
            # prevent double-assignment) if the target isn't one of the
            # source archetypes (or is a different archetype).
            members_norm = {norm(m) for m in members}
            member_cids_set = set(member_cids)
            for sid, akas in list(existing_aka.items()):
                if sid == tgt_id:
                    continue
                new_aka = [a for a in akas if norm(a) not in members_norm]
                new_cids = [
                    c for c in existing_cids.get(sid, []) if c not in member_cids_set
                ]
                existing_aka[sid] = new_aka
                existing_cids[sid] = new_cids
                await session.execute(
                    sql_text(
                        """
                        UPDATE archetype_registry
                        SET also_known_as = :aka,
                            canonical_ids = CAST(:cids AS uuid[]),
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": sid,
                        "aka": new_aka,
                        "cids": new_cids,
                    },
                )

            # Rewire event_clusters whose primary_archetype_name is one
            # of the source archetypes AND whose contributing_cultures
            # names map into this group's members.
            if source_ids:
                # Build a regex-ish ANY match on contributing cultures
                ev_rows = (
                    await session.execute(
                        sql_text(
                            """
                            SELECT id, contributing_cultures
                            FROM event_clusters
                            WHERE archetype_registry_id = ANY(CAST(:ids AS uuid[]))
                            """
                        ),
                        {"ids": source_ids},
                    )
                ).all()
                for ev_id, ccultures in ev_rows:
                    names_in_event: set[str] = set()
                    if isinstance(ccultures, dict):
                        for culture_key, actors in ccultures.items():
                            if isinstance(actors, list):
                                for a in actors:
                                    names_in_event.add(norm(str(a)))
                            elif isinstance(actors, str):
                                names_in_event.add(norm(actors))
                    if names_in_event & members_norm:
                        await session.execute(
                            sql_text(
                                """
                                UPDATE event_clusters
                                SET archetype_registry_id = :tid,
                                    primary_archetype_name = :pn
                                WHERE id = :eid
                                """
                            ),
                            {
                                "tid": tgt_id,
                                "pn": proposed_name,
                                "eid": str(ev_id),
                            },
                        )

            applied_notes.append(
                f"Group '{proposed_name}' → {len(members)} members"
            )

        # Update deity_dossiers.current_archetype_* denormalization
        await session.execute(
            sql_text(
                """
                UPDATE deity_dossiers dd
                SET current_archetype_id = ar.id,
                    current_archetype_name = ar.archetype_name,
                    updated_at = now()
                FROM archetype_registry ar
                WHERE ar.also_known_as && ARRAY[dd.actor_name]
                """
            )
        )

    # Mark the proposal applied
    await session.execute(
        sql_text(
            """
            UPDATE archetype_merge_proposals
            SET status = 'applied',
                applied_at = now(),
                applied_note = :note,
                updated_at = now()
            WHERE id = :pid
            """
        ),
        {"pid": proposal_id, "note": " | ".join(applied_notes)[:4000]},
    )
    await session.commit()
    return {
        "status": "applied",
        "proposal_id": proposal_id,
        "notes": applied_notes,
    }


@router.post("/archetype-proposals/{proposal_id}/reject")
async def reject_archetype_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Mark a proposal as rejected (no structural changes)."""
    from sqlalchemy import text as sql_text

    result = await session.execute(
        sql_text(
            """
            UPDATE archetype_merge_proposals
            SET status = 'rejected', updated_at = now()
            WHERE id = :pid AND status = 'pending'
            RETURNING id
            """
        ),
        {"pid": proposal_id},
    )
    if not result.first():
        raise HTTPException(
            404, "Proposal not found or not in pending state"
        )
    await session.commit()
    return {"status": "rejected", "proposal_id": proposal_id}


@router.get("/deity-dossier-status")
async def deity_dossier_status(
    epoch_orders: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Check the number of deity_dossiers produced so far."""
    from sqlalchemy import text as sql_text

    params: dict = {}
    where = ""
    if epoch_orders:
        orders = [int(x.strip()) for x in epoch_orders.split(",")]
        where = (
            " AND dd.epoch_id IN (SELECT id FROM canonical_epochs "
            "WHERE epoch_order = ANY(:orders))"
        )
        params["orders"] = orders
    counts = (
        await session.execute(
            sql_text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(canonical_actor_id) AS resolved,
                       COUNT(earliest_source_id) AS dated,
                       COUNT(characteristics_md) AS llm_enriched
                FROM deity_dossiers dd
                WHERE 1=1 {where}
                """
            ),
            params,
        )
    ).first()
    proposal_counts = (
        await session.execute(
            sql_text(
                """
                SELECT status, COUNT(*)
                FROM archetype_merge_proposals
                GROUP BY status
                """
            )
        )
    ).all()
    return {
        "dossiers_total": counts[0] if counts else 0,
        "dossiers_canonical_resolved": counts[1] if counts else 0,
        "dossiers_dated": counts[2] if counts else 0,
        "dossiers_llm_enriched": counts[3] if counts else 0,
        "proposal_counts": {r[0]: r[1] for r in proposal_counts},
    }


@router.get("/narrative-pipeline-status")
async def narrative_pipeline_status(
    epoch_orders: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Check progress of the narrative pipeline."""
    from sqlalchemy import text as sql_text
    from src.canon.models.culture_narrative import CultureNarrative, CultureEventSkeleton
    from src.canon.models.story_outline import StoryOutline
    from src.canon.models.story_chapter import StoryChapter

    epoch_filter = ""
    params: dict = {}
    if epoch_orders:
        orders = [int(x.strip()) for x in epoch_orders.split(",")]
        epoch_filter = " AND so.epoch_id IN (SELECT id FROM canonical_epochs WHERE epoch_order = ANY(:orders))"
        params["orders"] = orders

    narratives = (await session.execute(sql_text(f"""
        SELECT cn.culture_key, cn.culture_label, cn.word_count, cn.source_count,
               so.title as chapter_title
        FROM culture_narratives cn
        JOIN story_outlines so ON so.id = cn.story_outline_id
        WHERE 1=1 {epoch_filter}
        ORDER BY so.chapter_number, cn.culture_key
    """), params)).all()

    skeletons = (await session.execute(sql_text(f"""
        SELECT COUNT(*) FROM culture_event_skeletons ces
        JOIN story_outlines so ON so.id = ces.story_outline_id
        WHERE 1=1 {epoch_filter}
    """), params)).scalar() or 0

    unified = (await session.execute(sql_text(f"""
        SELECT COUNT(*) FROM story_chapters sc
        JOIN story_outlines so ON so.id = sc.story_outline_id
        WHERE sc.narrative_text IS NOT NULL AND sc.narrative_text != '' {epoch_filter}
    """), params)).scalar() or 0

    return {
        "culture_narratives": len(narratives),
        "event_skeletons": skeletons,
        "unified_chapters": unified,
        "details": [
            {
                "chapter": r[4],
                "culture": r[1],
                "words": r[2],
                "sources": r[3],
            }
            for r in narratives
        ],
    }


@router.post("/run-entity-resolution")
async def run_entity_resolution(
    max_pairs: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Run LLM-assisted entity resolution for cross-cultural merges."""
    svc = MergeService()
    result = await svc.run_llm_entity_resolution(session, max_pairs=max_pairs)
    await session.commit()
    return result


@router.post("/run-full-narrative-pipeline")
async def run_full_narrative_pipeline(session: AsyncSession = Depends(get_session)):
    """Run the complete narrative pipeline: score -> merge -> narrate -> prompt -> generate."""
    from src.canon.services.image_prompt_builder import ImagePromptBuilder
    from src.canon.workers.image_gen_worker import ImageGenWorker

    results = {}

    logger.info("Pipeline step 1/6: Scoring")
    svc = ScoringService()
    results["scoring"] = await svc.run_full_scoring(session)
    await session.commit()

    logger.info("Pipeline step 2/6: Alias merges")
    merge_svc = MergeService()
    results["alias_merges"] = await merge_svc.run_alias_merges(session)
    await session.commit()

    logger.info("Pipeline step 3/6: Entity resolution")
    results["entity_resolution"] = await merge_svc.run_llm_entity_resolution(session)
    await session.commit()

    logger.info("Pipeline step 4/7: Narrative planning")
    narr_svc = NarrativeSynthesizer()
    results["narrative_plan"] = await narr_svc.plan_all_epochs(session)

    logger.info("Pipeline step 5/7: Narrative synthesis")
    results["narrative"] = await narr_svc.run_full_synthesis(session)

    logger.info("Pipeline step 6/7: Image prompt building")
    img_builder = ImagePromptBuilder()
    results["image_prompts"] = await img_builder.build_all_pending(session)
    await session.commit()

    logger.info("Pipeline step 7/7: Image generation")
    img_worker = ImageGenWorker()
    results["image_generation"] = await img_worker.process_all_pending(session)
    await session.commit()

    return results


@router.post("/run-image-generation")
async def run_image_generation(
    batch_size: int = 10,
    session: AsyncSession = Depends(get_session),
):
    """Build image prompts and submit to RunPod for generation."""
    from src.canon.services.image_prompt_builder import ImagePromptBuilder
    from src.canon.workers.image_gen_worker import ImageGenWorker

    results = {}

    img_builder = ImagePromptBuilder()
    results["prompts"] = await img_builder.build_all_pending(session)
    await session.commit()

    img_worker = ImageGenWorker()
    results["generation"] = await img_worker.process_all_pending(session, batch_size=batch_size)
    await session.commit()

    return results


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get comprehensive system B stats."""
    hints_count = (await session.execute(select(func.count(ExtractedHint.id)))).scalar() or 0
    epochs_count = (
        await session.execute(
            select(func.count(CanonicalEpoch.id)).where(CanonicalEpoch.is_current.is_(True))
        )
    ).scalar() or 0
    chapters_count = (
        await session.execute(
            select(func.count(CanonicalChapter.id)).where(CanonicalChapter.is_current.is_(True))
        )
    ).scalar() or 0
    actors_count = (
        await session.execute(
            select(func.count(CanonicalActor.id)).where(CanonicalActor.is_current.is_(True))
        )
    ).scalar() or 0
    events_count = (
        await session.execute(
            select(func.count(CanonicalEvent.id)).where(CanonicalEvent.is_current.is_(True))
        )
    ).scalar() or 0
    places_count = (
        await session.execute(
            select(func.count(CanonicalPlace.id)).where(CanonicalPlace.is_current.is_(True))
        )
    ).scalar() or 0
    motifs_count = (await session.execute(select(func.count(Motif.id)))).scalar() or 0
    motif_assignments_count = (
        await session.execute(select(func.count(MotifAssignment.id)))
    ).scalar() or 0
    scores_count = (await session.execute(select(func.count(CanonScore.id)))).scalar() or 0
    narration_count = (await session.execute(select(func.count(NarrationPacket.id)))).scalar() or 0
    world_packets_count = (await session.execute(select(func.count(WorldPacket.id)))).scalar() or 0
    change_events_count = (await session.execute(select(func.count(ChangeEvent.id)))).scalar() or 0
    update_targets_count = (
        await session.execute(select(func.count(CanonUpdateTarget.id)))
    ).scalar() or 0

    return {
        "extracted_hints": hints_count,
        "epochs": epochs_count,
        "chapters": chapters_count,
        "actors": actors_count,
        "events": events_count,
        "places": places_count,
        "motifs": motifs_count,
        "motif_assignments": motif_assignments_count,
        "scores": scores_count,
        "narration_packets": narration_count,
        "world_packets": world_packets_count,
        "change_events": change_events_count,
        "update_targets": update_targets_count,
    }
