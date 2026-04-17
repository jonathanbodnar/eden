"""V2 narrative pipeline orchestrator.

Runs the five stages end-to-end for one or more epochs. Writes each stage to
the DB immediately so progress is visible and pipeline is resumable.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import async_session_factory
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.culture_narrative import (
    CultureEventSkeleton,
    CultureNarrative,
)
from src.canon.models.narrative_v2 import (
    ArchetypeRegistry,
    CultureAtomicEvent,
    EventCluster,
)
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.story_outline import StoryOutline
from src.canon.services.narrative_v2.shared import CULTURE_LABELS
from src.canon.services.narrative_v2.sources import (
    gather_actor_equivalences,
    gather_sources_for_epoch,
)
from src.canon.services.narrative_v2.stage1_fact_sheet import generate_fact_sheet
from src.canon.services.narrative_v2.stage2_atomic_events import (
    compute_embeddings,
    distil_atomic_events,
)
from src.canon.services.narrative_v2.stage3_cluster import (
    AtomicEventRow,
    Cluster,
    cluster_events,
    cluster_to_row,
)
from src.canon.services.narrative_v2.stage3b_archetype import resolve_archetype
from src.canon.services.narrative_v2.stage4_render import (
    ClusterForRendering,
    render_chapter,
)
from src.canon.services.narrative_v2.stage5_post_process import post_process

logger = logging.getLogger(__name__)

# How many cultures to process concurrently per chapter.
# Each culture fires 2 DeepSeek calls (Stage 1 + Stage 2) + 1 OpenAI embeddings call.
# DeepSeek-reasoner handles ~10-20 concurrent requests comfortably.
CULTURE_CONCURRENCY = 8


class NarrativePipelineV2:
    """Orchestrates the five-stage V2 pipeline."""

    async def run(
        self,
        session: AsyncSession,
        *,
        epoch_orders: list[int] | None = None,
        chapter_numbers: list[int] | None = None,
        wipe: bool = False,
        max_cultures: int | None = None,
        phase: str = "full",
    ) -> dict[str, Any]:
        """Run V2 for the given epochs (and optionally specific chapters).

        Args:
            epoch_orders: list of epoch_order ints; None = all
            chapter_numbers: list of chapter numbers to process within each
                epoch (e.g. [1] to only run chapter 1). None = all chapters.
            wipe: if True, delete artifacts before regenerating. If
                chapter_numbers is set, only those chapters' artifacts are
                wiped; otherwise all artifacts for the targeted epochs.
            max_cultures: cap number of cultures per chapter (None = all)
            phase: "full" (default) runs Phase A → B → C end to end.
                "render_only" skips Phase A (atomic event extraction) and
                Phase B (clustering + archetype minting) and re-renders
                every chapter using the existing `event_clusters` rows and
                the current `archetype_registry`. Use this after approving
                archetype merge proposals to regenerate chapters without
                paying the extraction cost again.
        """

        phase = (phase or "full").lower()
        if phase not in ("full", "render_only"):
            raise ValueError(f"Unknown phase: {phase!r}")

        q = select(CanonicalEpoch).where(CanonicalEpoch.is_current.is_(True))
        if epoch_orders is not None:
            q = q.where(CanonicalEpoch.epoch_order.in_(epoch_orders))
        q = q.order_by(CanonicalEpoch.epoch_order)
        epochs = (await session.execute(q)).scalars().all()

        if wipe and phase != "render_only":
            await self._wipe_epochs(
                session,
                [e.id for e in epochs],
                chapter_numbers=chapter_numbers,
            )

        total_chapters = 0
        total_clusters = 0

        # Capture epoch IDs; we'll re-open sessions per-chapter to avoid stale conns.
        epoch_records = [
            (e.id, e.epoch_order, e.title) for e in epochs
        ]

        # Pre-close the passed session — chapters open their own to stay fresh.
        try:
            await session.close()
        except Exception:
            pass

        for epoch_id, epoch_order, epoch_title in epoch_records:
            logger.info(
                "V2 pipeline: processing epoch %d — %s (global-archetype mode)",
                epoch_order,
                epoch_title,
            )

            async with async_session_factory() as s_init:
                outlines_q = (
                    select(StoryOutline)
                    .where(StoryOutline.epoch_id == epoch_id)
                    .order_by(StoryOutline.chapter_number)
                )
                if chapter_numbers:
                    outlines_q = outlines_q.where(
                        StoryOutline.chapter_number.in_(chapter_numbers)
                    )
                outlines = (await s_init.execute(outlines_q)).scalars().all()

                if not outlines:
                    logger.warning(
                        "Epoch %s has no story_outlines — run planner first",
                        epoch_title,
                    )
                    continue

                source_groups = await gather_sources_for_epoch(
                    s_init, epoch_id, themes=[]
                )
                if max_cultures is not None:
                    source_groups = source_groups[:max_cultures]

                equivalences = await gather_actor_equivalences(s_init)

                outline_records = [
                    (o.id, o.chapter_number, o.title, o.summary or "")
                    for o in outlines
                ]

            if phase == "render_only":
                logger.info(
                    "  PHASE A+B skipped (render_only). Loading existing "
                    "event_clusters from DB…"
                )
                global_cluster_map = await self._load_existing_cluster_rows(
                    outline_records=outline_records
                )
            else:
                # ---------------------------------------------------------
                # PHASE A — Extract atomic events for every chapter × culture.
                # This produces per-chapter atomic events but no clusters yet.
                # ---------------------------------------------------------
                logger.info(
                    "  PHASE A: extracting atomic events for %d chapters × %d cultures",
                    len(outline_records),
                    len(source_groups),
                )
                for outline_id, chapter_number, outline_title, outline_summary in outline_records:
                    logger.info(
                        "    Chapter %d: %s — stage 1+2",
                        chapter_number,
                        outline_title,
                    )
                    # Phase A's _process_culture opens its own sessions, so we
                    # don't hold any outer session open across the long gather.
                    await self._run_phase_a(
                        outline_id=outline_id,
                        outline_title=outline_title,
                        outline_summary=outline_summary,
                        source_groups=source_groups,
                    )

                # ---------------------------------------------------------
                # PHASE B — Cluster globally across all chapters and mint
                # archetypes ONCE for the whole epoch. Consistent archetypes
                # across chapters = consistent narrative.
                # ---------------------------------------------------------
                logger.info(
                    "  PHASE B: global clustering + archetype minting across "
                    "%d chapters",
                    len(outline_records),
                )
                global_cluster_map = await self._run_phase_b_global(
                    epoch_id=epoch_id,
                    outline_records=outline_records,
                    equivalences=equivalences,
                )

            # -------------------------------------------------------------
            # PHASE C — Render each chapter using the globally-consistent
            # archetypes. Post-process. Persist StoryChapter.
            # -------------------------------------------------------------
            logger.info(
                "  PHASE C: rendering %d chapters with consistent archetypes",
                len(outline_records),
            )
            prior_summaries: list[str] = []
            for outline_id, chapter_number, outline_title, outline_summary in outline_records:
                logger.info(
                    "    Chapter %d: %s — rendering",
                    chapter_number,
                    outline_title,
                )
                chapter_cluster_rows = global_cluster_map.get(outline_id, [])
                if not chapter_cluster_rows:
                    logger.warning(
                        "      Chapter %d has no clusters — skipping render",
                        chapter_number,
                    )
                    continue

                # _run_phase_c_render opens its own short-lived sessions around
                # DB lookups and DB writes, so nothing is held during the LLM
                # call.
                result = await self._run_phase_c_render(
                    epoch_id=epoch_id,
                    outline_id=outline_id,
                    outline_title=outline_title,
                    outline_summary=outline_summary,
                    cluster_rows=chapter_cluster_rows,
                    prior_summaries=prior_summaries,
                )
                total_chapters += 1
                total_clusters += result.get("cluster_count", 0)
                prior_summaries.append(
                    f"Chapter {chapter_number}: {outline_title} — {outline_summary}"
                )

        return {
            "epochs_processed": len(epochs),
            "chapters_generated": total_chapters,
            "clusters_created": total_clusters,
        }

    # ------------------------------------------------------------------
    # PHASE A: per-chapter Stage 1 + 2 (fact sheet + atomic events)
    # ------------------------------------------------------------------

    async def _run_phase_a(
        self,
        *,
        outline_id: uuid.UUID,
        outline_title: str,
        outline_summary: str,
        source_groups: list,
    ) -> None:
        """Run Stage 1 + Stage 2 for a single chapter, for each culture, in
        parallel. Persists culture narratives and atomic events."""

        sem = asyncio.Semaphore(CULTURE_CONCURRENCY)

        async def _process_culture(culture_key, culture_label, sources):
            """Run Stage 1 + Stage 2 + embeddings for one culture, then persist.

            Each task uses its own short-lived DB session so the parent session
            isn't held idle during long LLM calls (which would kill the conn).
            Returns True on success, False on failure.
            """
            async with sem:
                try:
                    stage1 = await generate_fact_sheet(
                        culture_label=culture_label
                        or CULTURE_LABELS.get(culture_key, culture_key),
                        chapter_title=outline_title,
                        chapter_summary=outline_summary,
                        sources=sources,
                    )
                except Exception:
                    logger.exception("Stage 1 failed for %s", culture_key)
                    return False

                if not stage1 or not stage1.get("prose_history"):
                    logger.warning("Stage 1 empty for %s — skipping", culture_key)
                    return False

                prose = stage1["prose_history"]
                fact_sheet = stage1.get("fact_sheet") or {}

                try:
                    events = await distil_atomic_events(fact_sheet)
                except Exception:
                    logger.exception("Stage 2 failed for %s", culture_key)
                    events = []

                if events:
                    try:
                        embeddings = await compute_embeddings(events)
                    except Exception:
                        logger.exception("Embeddings failed for %s", culture_key)
                        embeddings = [None] * len(events)
                else:
                    embeddings = []

                # Persist with a fresh, short-lived session
                try:
                    async with async_session_factory() as s:
                        existing_cn = (
                            await s.execute(
                                select(CultureNarrative).where(
                                    CultureNarrative.story_outline_id == outline_id,
                                    CultureNarrative.culture_key == culture_key,
                                )
                            )
                        ).scalar_one_or_none()

                        if existing_cn is None:
                            cn = CultureNarrative(
                                story_outline_id=outline_id,
                                culture_key=culture_key,
                                culture_label=culture_label,
                                narrative_text=prose,
                                prose_history=prose,
                                fact_sheet=fact_sheet,
                                actors_json=fact_sheet.get("actors"),
                                events_json=fact_sheet.get("events"),
                                places_json=fact_sheet.get("places"),
                                source_ids=[s.source_id for s in sources],
                                source_count=len(sources),
                                word_count=len(prose.split()),
                                generation_version=2,
                            )
                            s.add(cn)
                            await s.flush()
                        else:
                            existing_cn.narrative_text = prose
                            existing_cn.prose_history = prose
                            existing_cn.fact_sheet = fact_sheet
                            existing_cn.actors_json = fact_sheet.get("actors")
                            existing_cn.events_json = fact_sheet.get("events")
                            existing_cn.places_json = fact_sheet.get("places")
                            existing_cn.source_ids = [s.source_id for s in sources]
                            existing_cn.source_count = len(sources)
                            existing_cn.word_count = len(prose.split())
                            existing_cn.generation_version = 2
                            cn = existing_cn

                        if events:
                            await s.execute(
                                delete(CultureAtomicEvent).where(
                                    CultureAtomicEvent.culture_narrative_id == cn.id
                                )
                            )
                            await s.flush()

                            for ev, emb in zip(events, embeddings):
                                row = CultureAtomicEvent(
                                    culture_narrative_id=cn.id,
                                    story_outline_id=outline_id,
                                    culture_key=culture_key,
                                    seq=ev["seq"],
                                    actors=ev["actors"],
                                    verb=ev["verb"],
                                    verb_family=ev["verb_family"],
                                    objects=ev["objects"],
                                    materials=ev["materials"],
                                    place=ev["place"],
                                    outcome=ev["outcome"],
                                    outcome_keywords=ev["outcome_keywords"],
                                    quoted_phrase=ev["quoted_phrase"],
                                    source_ref=ev["source_ref"],
                                    action_embedding=emb if emb else None,
                                )
                                s.add(row)
                            await s.flush()
                        await s.commit()
                except Exception:
                    logger.exception("DB persist failed for %s", culture_key)
                    return False

                logger.info(
                    "    %s: %d events persisted", culture_key, len(events)
                )
                return True

        logger.info(
            "      Stage 1+2: parallel processing of %d cultures (concurrency=%d)",
            len(source_groups),
            CULTURE_CONCURRENCY,
        )
        await asyncio.gather(
            *[
                _process_culture(culture_key, culture_label, sources)
                for culture_key, culture_label, sources in source_groups
            ]
        )

    # ------------------------------------------------------------------
    # PHASE B: global clustering + archetype minting across all chapters
    # ------------------------------------------------------------------

    async def _run_phase_b_global(
        self,
        *,
        epoch_id: uuid.UUID,
        outline_records: list,
        equivalences: dict[str, set[str]],
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """Cluster ALL atomic events across every chapter in the epoch, then
        mint/resolve archetypes ONCE. Returns a mapping of outline_id →
        list of cluster_rows (ordered by chapter chronology) that each chapter
        should render with.

        This means:
          - A cluster whose events come from multiple chapters appears in ALL
            those chapters' cluster_rows with the SAME archetype_registry_id.
          - Across chapters, e.g. Marduk always resolves to "The Champion".
        """

        outline_ids = [rec[0] for rec in outline_records]
        outline_id_to_number = {rec[0]: rec[1] for rec in outline_records}

        # Load every atomic event for every chapter in this epoch (short session)
        async with async_session_factory() as s:
            atomic_rows = (
                await s.execute(
                    select(CultureAtomicEvent).where(
                        CultureAtomicEvent.story_outline_id.in_(outline_ids)
                    )
                )
            ).scalars().all()

            event_id_to_outline: dict[uuid.UUID, uuid.UUID] = {}
            atomic_events: list[AtomicEventRow] = []
            for r in atomic_rows:
                event_id_to_outline[r.id] = r.story_outline_id
                atomic_events.append(
                    AtomicEventRow(
                        id=r.id,
                        culture_key=r.culture_key,
                        seq=r.seq,
                        actors=list(r.actors or []),
                        verb=r.verb,
                        verb_family=r.verb_family,
                        objects=list(r.objects or []),
                        materials=list(r.materials or []),
                        place=r.place,
                        outcome=r.outcome,
                        outcome_keywords=list(r.outcome_keywords or []),
                        quoted_phrase=r.quoted_phrase,
                        source_ref=r.source_ref,
                        action_embedding=(
                            list(r.action_embedding) if r.action_embedding else None
                        ),
                    )
                )

            # Wipe prior cluster rows for all chapters in scope.
            await s.execute(
                delete(EventCluster).where(
                    EventCluster.story_outline_id.in_(outline_ids)
                )
            )
            await s.commit()

        logger.info(
            "    Phase B: clustering %d atomic events globally",
            len(atomic_events),
        )
        clusters = cluster_events(atomic_events, equivalences=equivalences)
        logger.info(
            "    Phase B: produced %d global clusters", len(clusters)
        )

        # For each global cluster, resolve the archetype ONCE (its own fresh
        # session, so the LLM call doesn't idle a long-held conn), then emit a
        # per-chapter cluster_row (same archetype_registry_id) for every chapter
        # whose events participated.
        chapter_to_rows: dict[uuid.UUID, list[dict[str, Any]]] = {
            oid: [] for oid in outline_ids
        }
        chapter_next_seq: dict[uuid.UUID, int] = {oid: 1 for oid in outline_ids}
        skipped_non_actor = 0

        for i, cluster in enumerate(clusters):
            canonical_row = cluster_to_row(cluster, seq=0)

            async with async_session_factory() as s:
                archetype = await resolve_archetype(
                    session=s,
                    cluster_row=canonical_row,
                    epoch_id=epoch_id,
                    chapter_id=None,
                    entity_type="actor",
                )
                if archetype is None:
                    skipped_non_actor += 1
                    await s.commit()
                    continue

                archetype_name = archetype.archetype_name
                archetype_id = archetype.id
                await s.commit()

            # Determine which chapters this cluster touches.
            participating_outlines: set[uuid.UUID] = set()
            for ev in cluster.members:
                oid = event_id_to_outline.get(ev.id)
                if oid is not None:
                    participating_outlines.add(oid)

            # Persist per-chapter cluster_rows in a short session.
            async with async_session_factory() as s:
                for outline_id in participating_outlines:
                    seq = chapter_next_seq[outline_id]
                    chapter_next_seq[outline_id] = seq + 1

                    chapter_members = [
                        ev
                        for ev in cluster.members
                        if event_id_to_outline.get(ev.id) == outline_id
                    ]
                    if not chapter_members:
                        continue

                    chapter_cluster = Cluster(
                        cluster_key=f"{cluster.cluster_key}::ch{outline_id}",
                        verb_family=cluster.verb_family,
                        members=chapter_members,
                    )
                    chapter_row = cluster_to_row(chapter_cluster, seq=seq)
                    chapter_row["primary_archetype_name"] = archetype_name
                    chapter_row["archetype_registry_id"] = archetype_id

                    db_row = EventCluster(
                        story_outline_id=outline_id,
                        cluster_key=chapter_row["cluster_key"],
                        seq=chapter_row["seq"],
                        primary_archetype_name=chapter_row["primary_archetype_name"],
                        archetype_registry_id=chapter_row["archetype_registry_id"],
                        contributing_event_ids=chapter_row["contributing_event_ids"],
                        contributing_cultures=chapter_row["contributing_cultures"],
                        canonical_verb=chapter_row["canonical_verb"],
                        canonical_outcome=chapter_row["canonical_outcome"],
                        verb_family=chapter_row["verb_family"],
                        materials=chapter_row["materials"],
                        vivid_details=chapter_row["vivid_details"],
                        source_quotes=chapter_row["source_quotes"],
                        age_rank_of_oldest=chapter_row["age_rank_of_oldest"],
                        retention_score=chapter_row["retention_score"],
                    )
                    s.add(db_row)
                    chapter_to_rows[outline_id].append(chapter_row)

                await s.commit()

        if skipped_non_actor:
            logger.info(
                "    Phase B: skipped %d non-actor clusters", skipped_non_actor
            )
        for oid, rows in chapter_to_rows.items():
            logger.info(
                "    Chapter %d: %d clusters assigned",
                outline_id_to_number.get(oid, -1),
                len(rows),
            )

        return chapter_to_rows

    # ------------------------------------------------------------------
    # render_only helper: load existing event_clusters → cluster_row dicts
    # ------------------------------------------------------------------

    async def _load_existing_cluster_rows(
        self,
        *,
        outline_records: list,
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """Rebuild the cluster_row dicts Phase C expects from the already-
        persisted `event_clusters` rows. Used when we've approved archetype
        merge proposals and want to re-render chapters with the updated
        `archetype_registry` without re-running Phase A or Phase B.

        The returned rows inherit the *current* `archetype_registry_id`
        and its `archetype_name` — meaning any rewiring done by an approved
        merge proposal is honored automatically.
        """
        outline_ids = [rec[0] for rec in outline_records]
        outline_id_to_number = {rec[0]: rec[1] for rec in outline_records}

        chapter_to_rows: dict[uuid.UUID, list[dict[str, Any]]] = {
            oid: [] for oid in outline_ids
        }

        async with async_session_factory() as s:
            rows = (
                await s.execute(
                    select(EventCluster, ArchetypeRegistry.archetype_name)
                    .outerjoin(
                        ArchetypeRegistry,
                        EventCluster.archetype_registry_id == ArchetypeRegistry.id,
                    )
                    .where(EventCluster.story_outline_id.in_(outline_ids))
                    .order_by(EventCluster.story_outline_id, EventCluster.seq)
                )
            ).all()

        for ec, live_archetype_name in rows:
            outline_id = ec.story_outline_id
            # Prefer the live archetype_registry.archetype_name if linked,
            # so rewired clusters pick up their new name automatically.
            archetype_name = live_archetype_name or ec.primary_archetype_name
            chapter_to_rows[outline_id].append(
                {
                    "cluster_key": ec.cluster_key,
                    "seq": ec.seq,
                    "primary_archetype_name": archetype_name,
                    "archetype_registry_id": ec.archetype_registry_id,
                    "contributing_event_ids": list(
                        ec.contributing_event_ids or []
                    ),
                    "contributing_cultures": dict(
                        ec.contributing_cultures or {}
                    ),
                    "canonical_verb": ec.canonical_verb,
                    "canonical_outcome": ec.canonical_outcome,
                    "verb_family": ec.verb_family,
                    "materials": list(ec.materials or []),
                    "vivid_details": list(ec.vivid_details or []),
                    "source_quotes": list(ec.source_quotes or []),
                    "age_rank_of_oldest": ec.age_rank_of_oldest,
                    "retention_score": ec.retention_score,
                }
            )

        for oid, chrows in chapter_to_rows.items():
            logger.info(
                "    Chapter %d: loaded %d clusters (render_only)",
                outline_id_to_number.get(oid, -1),
                len(chrows),
            )

        return chapter_to_rows

    # ------------------------------------------------------------------
    # PHASE C: per-chapter rendering + post-processing
    # ------------------------------------------------------------------

    async def _run_phase_c_render(
        self,
        *,
        epoch_id: uuid.UUID,
        outline_id: uuid.UUID,
        outline_title: str,
        outline_summary: str,
        cluster_rows: list[dict[str, Any]],
        prior_summaries: list[str],
    ) -> dict[str, Any]:
        """Render one chapter using pre-resolved archetype cluster rows.

        Opens short-lived sessions around DB work; nothing is held during
        the Stage 4 LLM render.
        """

        if not cluster_rows:
            logger.warning(
                "      Chapter %s produced zero clusters — skipping render",
                outline_title,
            )
            return {"cluster_count": 0}

        # Stage 4 input: look up archetype role descriptions (short session)
        arch_name_to_role: dict[str, str | None] = {}
        async with async_session_factory() as s:
            arch_rows_q = (
                await s.execute(
                    select(ArchetypeRegistry).where(
                        ArchetypeRegistry.archetype_name.in_(
                            [cr["primary_archetype_name"] for cr in cluster_rows]
                        )
                    )
                )
            ).scalars().all()
            for ar in arch_rows_q:
                arch_name_to_role[ar.archetype_name] = ar.role_description

        render_inputs: list[ClusterForRendering] = []
        for cr in cluster_rows:
            contributing_deities: list[str] = []
            for names in (cr.get("contributing_cultures") or {}).values():
                for n in names:
                    if n and n not in contributing_deities:
                        contributing_deities.append(n)
            render_inputs.append(
                ClusterForRendering(
                    seq=cr["seq"],
                    archetype_name=cr["primary_archetype_name"],
                    archetype_role=arch_name_to_role.get(cr["primary_archetype_name"]),
                    verb_family=cr["verb_family"],
                    canonical_verb=cr["canonical_verb"],
                    canonical_outcome=cr["canonical_outcome"],
                    materials=list(cr.get("materials") or []),
                    vivid_details=list(cr.get("vivid_details") or []),
                    source_quotes=list(cr.get("source_quotes") or []),
                    contributing_deities=contributing_deities,
                )
            )

        # LLM call with NO session held open.
        render_result = await render_chapter(
            chapter_title=outline_title,
            chapter_summary=outline_summary,
            prior_summaries=prior_summaries,
            clusters=render_inputs,
        )
        narrative_text = render_result["narrative_text"]
        archetypes_used = render_result["archetypes_used"]

        # Stage 5 post-process + persistence in a fresh session.
        async with async_session_factory() as session:
            post = await post_process(
                session=session,
                narrative_text=narrative_text,
                archetype_names=archetypes_used,
                cluster_rows=cluster_rows,
            )

            existing_ch = (
                await session.execute(
                    select(StoryChapter).where(
                        StoryChapter.story_outline_id == outline_id
                    )
                )
            ).scalar_one_or_none()

            wc = len((post["narrative_text"] or "").split())

            if existing_ch is None:
                ch = StoryChapter(
                    story_outline_id=outline_id,
                    epoch_id=epoch_id,
                    narrative_text=post["narrative_text"],
                    entity_mentions_json=post["entity_mentions_json"],
                    word_count=wc,
                    pipeline_version="v2",
                    cluster_count=len(cluster_rows),
                    archetypes_used=post["archetypes_used"],
                )
                session.add(ch)
            else:
                existing_ch.epoch_id = epoch_id
                existing_ch.narrative_text = post["narrative_text"]
                existing_ch.entity_mentions_json = post["entity_mentions_json"]
                existing_ch.word_count = wc
                existing_ch.pipeline_version = "v2"
                existing_ch.cluster_count = len(cluster_rows)
                existing_ch.archetypes_used = post["archetypes_used"]
                ch = existing_ch
            await session.flush()

            # Back-fill first_seen_chapter_id for newly-minted archetypes
            arch_rows_live = (
                await session.execute(
                    select(ArchetypeRegistry).where(
                        ArchetypeRegistry.archetype_name.in_(
                            [cr["primary_archetype_name"] for cr in cluster_rows]
                        )
                    )
                )
            ).scalars().all()
            for ar in arch_rows_live:
                if ar.first_seen_chapter_id is None:
                    ar.first_seen_chapter_id = ch.id

            await session.commit()

        if post["problems"]:
            logger.warning(
                "Chapter %s validator flagged %d issues: %s",
                outline_title,
                len(post["problems"]),
                post["problems"][:5],
            )

        return {
            "cluster_count": len(cluster_rows),
            "word_count": wc,
            "problems": post["problems"],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _wipe_epochs(
        self,
        session: AsyncSession,
        epoch_ids: list[uuid.UUID],
        chapter_numbers: list[int] | None = None,
    ) -> None:
        if not epoch_ids:
            return

        outlines_q = select(StoryOutline.id).where(
            StoryOutline.epoch_id.in_(epoch_ids)
        )
        if chapter_numbers:
            outlines_q = outlines_q.where(
                StoryOutline.chapter_number.in_(chapter_numbers)
            )
        outline_ids = list(
            (await session.execute(outlines_q)).scalars().all()
        )

        if outline_ids:
            await session.execute(
                delete(StoryChapter).where(
                    StoryChapter.story_outline_id.in_(outline_ids)
                )
            )
            await session.execute(
                delete(EventCluster).where(
                    EventCluster.story_outline_id.in_(outline_ids)
                )
            )
            await session.execute(
                delete(CultureAtomicEvent).where(
                    CultureAtomicEvent.story_outline_id.in_(outline_ids)
                )
            )
            await session.execute(
                delete(CultureEventSkeleton).where(
                    CultureEventSkeleton.story_outline_id.in_(outline_ids)
                )
            )
            await session.execute(
                delete(CultureNarrative).where(
                    CultureNarrative.story_outline_id.in_(outline_ids)
                )
            )
        await session.commit()
        logger.info("Wiped artifacts for %d outlines", len(outline_ids))
