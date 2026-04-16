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
        wipe: bool = False,
        max_cultures: int | None = None,
    ) -> dict[str, Any]:
        """Run V2 for the given epochs.

        Args:
            epoch_orders: list of epoch_order ints; None = all
            wipe: if True, delete all V1 and V2 artifacts before regenerating
            max_cultures: cap number of cultures per chapter (None = all)
        """

        q = select(CanonicalEpoch).where(CanonicalEpoch.is_current.is_(True))
        if epoch_orders is not None:
            q = q.where(CanonicalEpoch.epoch_order.in_(epoch_orders))
        q = q.order_by(CanonicalEpoch.epoch_order)
        epochs = (await session.execute(q)).scalars().all()

        if wipe:
            await self._wipe_epochs(session, [e.id for e in epochs])

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
                "V2 pipeline: processing epoch %d — %s",
                epoch_order,
                epoch_title,
            )

            async with async_session_factory() as s_init:
                outlines = (
                    await s_init.execute(
                        select(StoryOutline)
                        .where(StoryOutline.epoch_id == epoch_id)
                        .order_by(StoryOutline.chapter_number)
                    )
                ).scalars().all()

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

                # Detach outline objects so they're usable after session closes
                outline_records = [
                    (o.id, o.chapter_number, o.title, o.summary or "") for o in outlines
                ]

            prior_summaries: list[str] = []

            for outline_id, chapter_number, outline_title, outline_summary in outline_records:
                logger.info(
                    "  Chapter %d: %s",
                    chapter_number,
                    outline_title,
                )
                # Each chapter opens its own session; long-lived sessions die
                # during the multi-minute parallel LLM gather.
                async with async_session_factory() as chapter_session:
                    # Re-load the StoryOutline ORM object in this session
                    outline_obj = (
                        await chapter_session.execute(
                            select(StoryOutline).where(StoryOutline.id == outline_id)
                        )
                    ).scalar_one()
                    result = await self._run_chapter(
                        session=chapter_session,
                        epoch_id=epoch_id,
                        outline=outline_obj,
                        source_groups=source_groups,
                        equivalences=equivalences,
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
    # Per-chapter
    # ------------------------------------------------------------------

    async def _run_chapter(
        self,
        *,
        session: AsyncSession,
        epoch_id: uuid.UUID,
        outline: StoryOutline,
        source_groups: list,
        equivalences: dict[str, set[str]],
        prior_summaries: list[str],
    ) -> dict[str, Any]:
        """Run all five stages for one chapter."""

        # ------------- Stage 1 + 2: per-culture (parallel LLM calls) -------------
        atomic_events_for_chapter: list[AtomicEventRow] = []

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
                        chapter_title=outline.title,
                        chapter_summary=outline.summary or "",
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
                                    CultureNarrative.story_outline_id == outline.id,
                                    CultureNarrative.culture_key == culture_key,
                                )
                            )
                        ).scalar_one_or_none()

                        if existing_cn is None:
                            cn = CultureNarrative(
                                story_outline_id=outline.id,
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
                                    story_outline_id=outline.id,
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
            "  Stage 1+2: parallel processing of %d cultures (concurrency=%d)",
            len(source_groups),
            CULTURE_CONCURRENCY,
        )
        await asyncio.gather(
            *[
                _process_culture(culture_key, culture_label, sources)
                for culture_key, culture_label, sources in source_groups
            ]
        )

        # Open a fresh session for Stage 3-5 — the parent `session` may have
        # idled long enough during gather() that asyncpg dropped the conn.
        try:
            await session.close()
        except Exception:
            pass

        async with async_session_factory() as session:
            return await self._run_chapter_post_gather(
                session=session,
                epoch_id=epoch_id,
                outline=outline,
                equivalences=equivalences,
                prior_summaries=prior_summaries,
                atomic_events_for_chapter=atomic_events_for_chapter,
            )

    async def _run_chapter_post_gather(
        self,
        *,
        session: AsyncSession,
        epoch_id: uuid.UUID,
        outline: StoryOutline,
        equivalences: dict[str, set[str]],
        prior_summaries: list[str],
        atomic_events_for_chapter: list[AtomicEventRow],
    ) -> dict[str, Any]:
        """Stage 3-5 of a chapter, run with a fresh session post-gather."""

        atomic_rows = (
            await session.execute(
                select(CultureAtomicEvent).where(
                    CultureAtomicEvent.story_outline_id == outline.id
                )
            )
        ).scalars().all()

        for r in atomic_rows:
            atomic_events_for_chapter.append(
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
                    action_embedding=list(r.action_embedding) if r.action_embedding else None,
                )
            )

        # ------------- Stage 3: cluster -------------
        clusters = cluster_events(atomic_events_for_chapter, equivalences=equivalences)
        logger.info(
            "  Stage 3: %d clusters (from %d atomic events)",
            len(clusters),
            len(atomic_events_for_chapter),
        )

        # Wipe prior clusters for this outline
        await session.execute(
            delete(EventCluster).where(EventCluster.story_outline_id == outline.id)
        )
        await session.flush()

        cluster_rows: list[dict[str, Any]] = []
        skipped_non_actor = 0
        next_seq = 1
        for cluster in clusters:
            cluster_row = cluster_to_row(cluster, seq=next_seq)

            # Stage 3B: resolve archetype (returns None for non-actor clusters)
            archetype = await resolve_archetype(
                session=session,
                cluster_row=cluster_row,
                epoch_id=epoch_id,
                chapter_id=None,  # Will be updated after StoryChapter insert
                entity_type="actor",
            )
            if archetype is None:
                skipped_non_actor += 1
                continue

            cluster_row["seq"] = next_seq
            next_seq += 1
            cluster_row["primary_archetype_name"] = archetype.archetype_name
            cluster_row["archetype_registry_id"] = archetype.id

            db_row = EventCluster(
                story_outline_id=outline.id,
                cluster_key=cluster_row["cluster_key"],
                seq=cluster_row["seq"],
                primary_archetype_name=cluster_row["primary_archetype_name"],
                archetype_registry_id=cluster_row["archetype_registry_id"],
                contributing_event_ids=cluster_row["contributing_event_ids"],
                contributing_cultures=cluster_row["contributing_cultures"],
                canonical_verb=cluster_row["canonical_verb"],
                canonical_outcome=cluster_row["canonical_outcome"],
                verb_family=cluster_row["verb_family"],
                materials=cluster_row["materials"],
                vivid_details=cluster_row["vivid_details"],
                source_quotes=cluster_row["source_quotes"],
                age_rank_of_oldest=cluster_row["age_rank_of_oldest"],
                retention_score=cluster_row["retention_score"],
            )
            session.add(db_row)
            cluster_rows.append(cluster_row)

        await session.flush()
        await session.commit()

        if skipped_non_actor:
            logger.info(
                "  Stage 3B: skipped %d non-actor clusters (places/absence)",
                skipped_non_actor,
            )

        if not cluster_rows:
            logger.warning(
                "Chapter %s produced zero clusters — skipping narrative render",
                outline.title,
            )
            return {"cluster_count": 0}

        # ------------- Stage 4: render -------------
        # Build ClusterForRendering inputs; look up archetype role descriptions
        arch_name_to_role: dict[str, str | None] = {}
        arch_rows = (
            await session.execute(
                select(ArchetypeRegistry).where(
                    ArchetypeRegistry.archetype_name.in_(
                        [cr["primary_archetype_name"] for cr in cluster_rows]
                    )
                )
            )
        ).scalars().all()
        for ar in arch_rows:
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

        render_result = await render_chapter(
            chapter_title=outline.title,
            chapter_summary=outline.summary or "",
            prior_summaries=prior_summaries,
            clusters=render_inputs,
        )
        narrative_text = render_result["narrative_text"]
        archetypes_used = render_result["archetypes_used"]

        # ------------- Stage 5: post-process -------------
        post = await post_process(
            session=session,
            narrative_text=narrative_text,
            archetype_names=archetypes_used,
            cluster_rows=cluster_rows,
        )

        # ------------- Persist StoryChapter -------------
        existing_ch = (
            await session.execute(
                select(StoryChapter).where(
                    StoryChapter.story_outline_id == outline.id
                )
            )
        ).scalar_one_or_none()

        wc = len((post["narrative_text"] or "").split())

        if existing_ch is None:
            ch = StoryChapter(
                story_outline_id=outline.id,
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
        for ar in arch_rows:
            if ar.first_seen_chapter_id is None:
                ar.first_seen_chapter_id = ch.id

        await session.commit()

        if post["problems"]:
            logger.warning(
                "Chapter %s validator flagged %d issues: %s",
                outline.title,
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
        self, session: AsyncSession, epoch_ids: list[uuid.UUID]
    ) -> None:
        if not epoch_ids:
            return

        # Get outlines for these epochs
        outline_ids = [
            r
            for r in (
                await session.execute(
                    select(StoryOutline.id).where(
                        StoryOutline.epoch_id.in_(epoch_ids)
                    )
                )
            ).scalars().all()
        ]

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
