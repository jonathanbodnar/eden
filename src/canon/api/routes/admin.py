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
    """Phase 2: Generate unified cross-cultural narrative for each planned chapter.

    Requires story_outlines to exist (run /admin/plan-narrative first).
    Each chapter is committed individually for live frontend progress.

    Args:
        epoch_orders: comma-separated epoch_order values (e.g. "0,1,2,3"), omit for all
        skip_existing: skip chapters that already have a narrative (default True)
    """
    orders = [int(x.strip()) for x in epoch_orders.split(",")] if epoch_orders else None
    svc = NarrativeSynthesizer()
    result = await svc.run_full_synthesis(
        session,
        epoch_orders=orders,
        skip_existing=skip_existing,
    )
    return result


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
