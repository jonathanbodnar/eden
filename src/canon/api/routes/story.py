"""Story Mode API routes — serves the unified narrative for the frontend."""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import get_session
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.canon_score import CanonScore
from src.canon.models.enums import CanonicalType
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.image_generation_job import ImageGenerationJob
from src.canon.models.story_chapter import StoryChapter
from src.canon.models.story_outline import StoryOutline
from src.canon.models.system_a import SASourceRecord, SASourceVersion, SAObjectImage, SASegment

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/epochs")
async def get_story_epochs(session: AsyncSession = Depends(get_session)):
    """Get all epochs with story chapter counts for book navigation."""
    q = select(CanonicalEpoch).where(
        CanonicalEpoch.is_current.is_(True)
    ).order_by(CanonicalEpoch.epoch_order)
    epochs = (await session.execute(q)).scalars().all()

    result = []
    for e in epochs:
        ch_count = (await session.execute(
            select(func.count(StoryOutline.id)).where(StoryOutline.epoch_id == e.id)
        )).scalar() or 0

        written_count = (await session.execute(
            select(func.count(StoryChapter.id)).where(StoryChapter.epoch_id == e.id)
        )).scalar() or 0

        result.append({
            "id": str(e.id),
            "title": e.title,
            "epoch_order": e.epoch_order,
            "time_start": e.time_start,
            "time_end": e.time_end,
            "summary": e.summary,
            "chapter_count": ch_count,
            "written_count": written_count,
        })
    return result


@router.get("/chapters")
async def get_story_chapters(session: AsyncSession = Depends(get_session)):
    """Get all story chapters in order, joined with outline metadata."""
    q = (
        select(StoryChapter, StoryOutline, CanonicalEpoch)
        .join(StoryOutline, StoryOutline.id == StoryChapter.story_outline_id)
        .join(CanonicalEpoch, CanonicalEpoch.id == StoryChapter.epoch_id)
        .order_by(CanonicalEpoch.epoch_order, StoryOutline.chapter_number)
    )
    rows = (await session.execute(q)).all()

    result = []
    for sc, outline, ep in rows:
        images = await _get_chapter_images(session, sc.id)
        result.append({
            "id": str(sc.id),
            "outline_id": str(outline.id),
            "epoch_id": str(sc.epoch_id),
            "epoch_title": ep.title,
            "chapter_title": outline.title,
            "chapter_number": outline.chapter_number,
            "chapter_summary": outline.summary,
            "themes": outline.themes or [],
            "time_hint": outline.time_hint,
            "scope": outline.scope or "universal",
            "regions": outline.regions or [],
            "narrative_text": sc.narrative_text,
            "claims": sc.claims_json or [],
            "entity_mentions": sc.entity_mentions_json or [],
            "images": images,
            "word_count": sc.word_count,
            "time_start": ep.time_start,
            "time_end": ep.time_end,
            "synthesis_version": sc.synthesis_version,
        })
    return result


@router.get("/chapters/{story_chapter_id}")
async def get_story_chapter(story_chapter_id: str, session: AsyncSession = Depends(get_session)):
    """Get a single story chapter with full narrative and evidence."""
    import uuid
    sc = await session.get(StoryChapter, uuid.UUID(story_chapter_id))
    if not sc:
        from fastapi import HTTPException
        raise HTTPException(404, "Story chapter not found")

    outline = await session.get(StoryOutline, sc.story_outline_id) if sc.story_outline_id else None
    ep = await session.get(CanonicalEpoch, sc.epoch_id)
    images = await _get_chapter_images(session, sc.id)

    return {
        "id": str(sc.id),
        "outline_id": str(outline.id) if outline else None,
        "epoch_id": str(sc.epoch_id),
        "epoch_title": ep.title if ep else "",
        "chapter_title": outline.title if outline else "Untitled",
        "chapter_number": outline.chapter_number if outline else 0,
        "chapter_summary": outline.summary if outline else "",
        "themes": outline.themes if outline else [],
        "time_hint": outline.time_hint if outline else None,
        "scope": outline.scope if outline else "universal",
        "regions": outline.regions if outline else [],
        "narrative_text": sc.narrative_text,
        "claims": sc.claims_json or [],
        "entity_mentions": sc.entity_mentions_json or [],
        "images": images,
        "word_count": sc.word_count,
        "time_start": ep.time_start if ep else None,
        "time_end": ep.time_end if ep else None,
        "synthesis_version": sc.synthesis_version,
    }


@router.get("/chapters/{story_chapter_id}/evidence")
async def get_story_chapter_evidence(
    story_chapter_id: str, session: AsyncSession = Depends(get_session)
):
    """Get source evidence supporting a story chapter."""
    import uuid
    sc = await session.get(StoryChapter, uuid.UUID(story_chapter_id))
    if not sc:
        return []

    claims = sc.claims_json or []
    source_ids = set()
    for claim in claims:
        for sid in claim.get("source_ids", []):
            source_ids.add(sid)

    if not source_ids:
        return []

    evidence = []
    for sid in list(source_ids)[:30]:
        try:
            sr = await session.get(SASourceRecord, uuid.UUID(sid))
            if not sr:
                continue

            sv_q = select(SASourceVersion.text_extracted).where(
                SASourceVersion.source_record_id == sr.id
            ).limit(1)
            sv_row = (await session.execute(sv_q)).first()
            excerpt = sv_row[0][:600] if sv_row and sv_row[0] else ""

            evidence.append({
                "source_id": str(sr.id),
                "title": sr.canonical_title,
                "culture": sr.culture,
                "category": sr.source_category,
                "excerpt": excerpt,
                "origin_place": sr.origin_place_name,
            })
        except Exception:
            continue

    return evidence


@router.get("/entities/{entity_type}/{entity_id}/merge-breakdown")
async def get_entity_merge_breakdown(
    entity_type: str, entity_id: str, session: AsyncSession = Depends(get_session)
):
    """Get the merge breakdown for a canonical entity — which entities were unified,
    why, and the source evidence for each component."""
    eid = _uuid.UUID(entity_id)

    # Get the primary entity
    entity_info = None
    if entity_type == "actor":
        entity = await session.get(CanonicalActor, eid)
        if entity:
            entity_info = {
                "id": str(entity.id),
                "name": entity.canonical_name,
                "type": "actor",
                "subtype": entity.actor_type.value,
                "summary": entity.summary,
                "time_start": entity.time_start,
                "time_end": entity.time_end,
                "merge_confidence": entity.merge_confidence,
            }
    elif entity_type == "event":
        entity = await session.get(CanonicalEvent, eid)
        if entity:
            entity_info = {
                "id": str(entity.id),
                "name": entity.canonical_name,
                "type": "event",
                "subtype": entity.event_type.value,
                "summary": entity.summary,
                "time_start": entity.time_start,
                "time_end": entity.time_end,
                "merge_confidence": entity.merge_confidence,
            }
    elif entity_type == "place":
        entity = await session.get(CanonicalPlace, eid)
        if entity:
            entity_info = {
                "id": str(entity.id),
                "name": entity.canonical_name,
                "type": "place",
                "subtype": entity.place_type.value,
                "summary": entity.summary,
            }

    if not entity_info:
        raise HTTPException(404, "Entity not found")

    # Get score
    type_map = {"actor": CanonicalType.ACTOR, "event": CanonicalType.EVENT, "place": CanonicalType.PLACE}
    canon_type = type_map.get(entity_type, CanonicalType.ACTOR)
    score_q = select(CanonScore).where(
        CanonScore.canonical_type == canon_type,
        CanonScore.canonical_id == eid,
    )
    score = (await session.execute(score_q)).scalar_one_or_none()
    if score:
        entity_info["score"] = {
            "final": score.final_score,
            "age": score.age_score,
            "corroboration": score.corroboration_score,
            "independence": score.independence_score,
            "ambiguity": score.ambiguity_score,
        }

    # Get entity equivalences (both directions)
    equivalences = []
    try:
        eq_q = await session.execute(text("""
            SELECT id, primary_entity_type, primary_entity_id,
                   equivalent_entity_type, equivalent_entity_id,
                   merge_basis, confidence, evidence_json
            FROM entity_equivalences
            WHERE (primary_entity_type = :etype AND primary_entity_id = :eid)
               OR (equivalent_entity_type = :etype AND equivalent_entity_id = :eid)
            ORDER BY confidence DESC
        """), {"etype": entity_type, "eid": str(eid)})

        for row in eq_q.all():
            r = dict(row._mapping)
            other_id = r["equivalent_entity_id"] if str(r["primary_entity_id"]) == entity_id else r["primary_entity_id"]
            other_type = r["equivalent_entity_type"] if str(r["primary_entity_id"]) == entity_id else r["primary_entity_type"]

            other_name = None
            other_summary = None
            other_cultures = []

            if other_type == "actor":
                other_entity = await session.get(CanonicalActor, other_id)
                if other_entity:
                    other_name = other_entity.canonical_name
                    other_summary = other_entity.summary
            elif other_type == "event":
                other_entity = await session.get(CanonicalEvent, other_id)
                if other_entity:
                    other_name = other_entity.canonical_name
                    other_summary = other_entity.summary
            elif other_type == "place":
                other_entity = await session.get(CanonicalPlace, other_id)
                if other_entity:
                    other_name = other_entity.canonical_name
                    other_summary = other_entity.summary

            # Get cultures for the other entity
            try:
                culture_q = (
                    select(distinct(SASourceRecord.culture))
                    .select_from(CanonSupportLink)
                    .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
                    .where(
                        CanonSupportLink.canonical_type == type_map.get(other_type, CanonicalType.ACTOR),
                        CanonSupportLink.canonical_id == other_id,
                        SASourceRecord.culture.isnot(None),
                        SASourceRecord.culture != "",
                    ).limit(20)
                )
                other_cultures = [c[0] for c in (await session.execute(culture_q)).all()]
            except Exception:
                pass

            evidence = r.get("evidence_json") or {}
            equivalences.append({
                "equivalent_id": str(other_id),
                "equivalent_type": other_type,
                "equivalent_name": other_name,
                "equivalent_summary": other_summary,
                "cultures": other_cultures,
                "merge_basis": r["merge_basis"],
                "confidence": r["confidence"],
                "reasoning": evidence.get("reasoning", ""),
                "role_match": evidence.get("role_match"),
                "action_match": evidence.get("action_match"),
                "context_match": evidence.get("context_match"),
                "pattern_match": evidence.get("pattern_match"),
            })
    except Exception:
        logger.exception("Failed to get equivalences")

    # Get source evidence for the primary entity
    sources = []
    try:
        links_q = (
            select(CanonSupportLink, SASourceRecord)
            .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
            .where(
                CanonSupportLink.canonical_type == canon_type,
                CanonSupportLink.canonical_id == eid,
            )
            .order_by(CanonSupportLink.weight.desc())
            .limit(15)
        )
        for link, sr in (await session.execute(links_q)).all():
            sv_q = select(SASourceVersion.text_extracted).where(
                SASourceVersion.source_record_id == sr.id
            ).limit(1)
            sv_row = (await session.execute(sv_q)).first()
            excerpt = sv_row[0][:500] if sv_row and sv_row[0] else ""
            sources.append({
                "source_id": str(sr.id),
                "title": sr.canonical_title,
                "culture": sr.culture,
                "excerpt": excerpt,
                "weight": link.weight,
            })
    except Exception:
        logger.exception("Failed to get sources")

    # Get cultures for the primary entity
    primary_cultures = []
    try:
        culture_q = (
            select(distinct(SASourceRecord.culture))
            .select_from(CanonSupportLink)
            .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
            .where(
                CanonSupportLink.canonical_type == canon_type,
                CanonSupportLink.canonical_id == eid,
                SASourceRecord.culture.isnot(None),
                SASourceRecord.culture != "",
            ).limit(30)
        )
        primary_cultures = [c[0] for c in (await session.execute(culture_q)).all()]
    except Exception:
        pass

    return {
        "entity": entity_info,
        "cultures": primary_cultures,
        "equivalences": equivalences,
        "sources": sources,
    }


@router.get("/chapters/{story_chapter_id}/culture-variants")
async def get_culture_variants(
    story_chapter_id: str,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Get per-culture variants for a story chapter.

    Only returns cultures that have substantive source material related to
    the chapter's themes.  Includes original source texts as the main content,
    with entity breakdowns for the right panel.

    Args:
        q: optional search filter on culture name
    """
    sc = await session.get(StoryChapter, _uuid.UUID(story_chapter_id))
    if not sc:
        raise HTTPException(404, "Story chapter not found")

    outline = await session.get(StoryOutline, sc.story_outline_id) if sc.story_outline_id else None
    themes = outline.themes if outline else []

    epoch_id = str(sc.epoch_id)

    # Find cultures via canonical chapter titles (fast string parse) as primary
    # source, then enrich with source record data where available.
    # This avoids the slow join across 10K+ entities.
    import re as _re
    ch_q = select(CanonicalChapter.title).where(
        CanonicalChapter.epoch_id == sc.epoch_id,
        CanonicalChapter.is_current.is_(True),
    )
    ch_rows = (await session.execute(ch_q)).all()
    culture_pattern = _re.compile(r':\s*(.+?)(?:\s+Tradition)?$')
    culture_names: dict[str, int] = {}
    for (title,) in ch_rows:
        m = culture_pattern.search(title)
        if m:
            cname = m.group(1).strip()
            if cname.lower() != "overview":
                culture_names[cname] = culture_names.get(cname, 0) + 1

    # Now for each culture, check if there's actual source text via a fast
    # bounded query using only a sample of entities (LIMIT 500).
    culture_q = text("""
        WITH epoch_entities AS (
            SELECT DISTINCT d.child_id as entity_id
            FROM canon_dependencies d
            JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
            WHERE c.epoch_id = :epoch_id AND c.is_current = true
              AND d.child_type IN ('actor', 'event')
            LIMIT 500
        )
        SELECT sr.culture, count(DISTINCT sr.id) as source_count,
               sum(LENGTH(sv.text_extracted)) as total_text
        FROM epoch_entities ee
        JOIN canon_support_links cl ON cl.canonical_id = ee.entity_id
        JOIN source_records sr ON sr.id = cl.archive_object_id
        JOIN source_versions sv ON sv.source_record_id = sr.id
        WHERE sr.culture IS NOT NULL AND sr.culture != ''
          AND sv.text_extracted IS NOT NULL
          AND LENGTH(sv.text_extracted) > 100
        GROUP BY sr.culture
        HAVING sum(LENGTH(sv.text_extracted)) > 200
        ORDER BY sum(LENGTH(sv.text_extracted)) DESC
        LIMIT 40
    """)

    try:
        culture_rows = (await session.execute(culture_q, {"epoch_id": epoch_id})).all()
    except Exception:
        logger.exception("Failed to query culture variants")
        culture_rows = []

    # Merge: use source-query cultures + chapter-title cultures
    source_cultures = {r[0]: (int(r[1]), int(r[2])) for r in culture_rows}

    # Build final list: prefer cultures that have source data, but also include
    # cultures from chapter titles that might not have direct source links
    all_cultures: list[tuple[str, int, int]] = []
    seen = set()
    for cname, (sc_count, tlen) in source_cultures.items():
        all_cultures.append((cname, sc_count, tlen))
        seen.add(cname.lower())
    for cname, ch_count in culture_names.items():
        if cname.lower() not in seen:
            all_cultures.append((cname, 0, 0))

    all_cultures.sort(key=lambda x: x[2], reverse=True)

    # Apply search filter
    if q:
        q_lower = q.lower()
        all_cultures = [r for r in all_cultures if q_lower in r[0].lower()]

    result = []
    for culture_name, source_count, total_text in all_cultures[:30]:
        culture_key = culture_name.split("/")[0].strip().replace("'", "")

        # Get the actual original source texts for this culture + epoch
        src_q = text(f"""
            WITH epoch_entities AS (
                SELECT DISTINCT d.child_id as entity_id
                FROM canon_dependencies d
                JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
                WHERE c.epoch_id = :epoch_id AND c.is_current = true
                  AND d.child_type IN ('actor', 'event')
            )
            SELECT DISTINCT ON (sr.id)
                sr.canonical_title, sr.culture,
                LEFT(sv.text_extracted, 1500) as source_text,
                cl.weight
            FROM epoch_entities ee
            JOIN canon_support_links cl ON cl.canonical_id = ee.entity_id
            JOIN source_records sr ON sr.id = cl.archive_object_id
            JOIN source_versions sv ON sv.source_record_id = sr.id
            WHERE sr.culture ILIKE '%{culture_key}%'
              AND sv.text_extracted IS NOT NULL
              AND LENGTH(sv.text_extracted) > 200
            ORDER BY sr.id, cl.weight DESC
            LIMIT 8
        """)

        # Get entities linked to this culture
        entity_q = text(f"""
            WITH epoch_entities AS (
                SELECT d.child_id as entity_id, d.child_type as entity_type
                FROM canon_dependencies d
                JOIN canonical_chapters c ON c.id = d.parent_id AND d.parent_type = 'chapter'
                WHERE c.epoch_id = :epoch_id AND c.is_current = true
                  AND d.child_type IN ('actor', 'event', 'place')
            ),
            culture_entities AS (
                SELECT DISTINCT ee.entity_id, ee.entity_type
                FROM epoch_entities ee
                JOIN canon_support_links cl ON cl.canonical_id = ee.entity_id
                JOIN source_records sr ON sr.id = cl.archive_object_id
                WHERE sr.culture ILIKE '%{culture_key}%'
            )
            SELECT
                ce.entity_id::text,
                ce.entity_type,
                COALESCE(
                    (SELECT canonical_name FROM canonical_actors WHERE id = ce.entity_id),
                    (SELECT canonical_name FROM canonical_events WHERE id = ce.entity_id),
                    (SELECT canonical_name FROM canonical_places WHERE id = ce.entity_id)
                ) as entity_name,
                COALESCE(
                    (SELECT LEFT(summary, 200) FROM canonical_actors WHERE id = ce.entity_id),
                    (SELECT LEFT(summary, 200) FROM canonical_events WHERE id = ce.entity_id),
                    (SELECT LEFT(summary, 200) FROM canonical_places WHERE id = ce.entity_id)
                ) as entity_summary
            FROM culture_entities ce
            LIMIT 20
        """)

        try:
            src_rows = (await session.execute(src_q, {"epoch_id": epoch_id})).all()
            ent_rows = (await session.execute(entity_q, {"epoch_id": epoch_id})).all()
        except Exception:
            logger.exception("Failed to get culture detail for %s", culture_name)
            continue

        source_texts = [
            {"title": r[0] or "Unknown", "culture": r[1], "text": r[2] or "", "weight": float(r[3] or 0)}
            for r in src_rows if r[2] and len(r[2].strip()) > 100
        ]
        source_texts.sort(key=lambda x: x["weight"], reverse=True)

        actors = [
            {"id": r[0], "name": r[2] or "Unknown", "type": r[1], "summary": r[3] or ""}
            for r in ent_rows if r[1] == "actor" and r[2]
        ]
        events = [
            {"id": r[0], "name": r[2] or "Unknown", "type": r[1], "summary": r[3] or ""}
            for r in ent_rows if r[1] == "event" and r[2]
        ]
        places = [
            {"id": r[0], "name": r[2] or "Unknown", "type": r[1], "summary": r[3] or ""}
            for r in ent_rows if r[1] == "place" and r[2]
        ]

        if not source_texts:
            continue

        result.append({
            "culture": culture_name,
            "source_count": int(source_count),
            "source_texts": source_texts[:6],
            "actors": actors[:10],
            "events": events[:10],
            "places": places[:5],
        })

    return result


@router.get("/outlines")
async def get_story_outlines(session: AsyncSession = Depends(get_session)):
    """Get all planned story outlines (the 'table of contents')."""
    q = (
        select(StoryOutline, CanonicalEpoch)
        .join(CanonicalEpoch, CanonicalEpoch.id == StoryOutline.epoch_id)
        .order_by(CanonicalEpoch.epoch_order, StoryOutline.chapter_number)
    )
    rows = (await session.execute(q)).all()

    result = []
    for outline, ep in rows:
        has_narrative = (await session.execute(
            select(func.count(StoryChapter.id)).where(
                StoryChapter.story_outline_id == outline.id
            )
        )).scalar() or 0

        result.append({
            "id": str(outline.id),
            "epoch_id": str(outline.epoch_id),
            "epoch_title": ep.title,
            "chapter_number": outline.chapter_number,
            "title": outline.title,
            "summary": outline.summary,
            "themes": outline.themes or [],
            "time_hint": outline.time_hint,
            "has_narrative": has_narrative > 0,
        })
    return result


@router.get("/stats")
async def get_story_stats(session: AsyncSession = Depends(get_session)):
    """Get comprehensive stats for the About page."""
    source_records = (await session.execute(
        select(func.count(SASourceRecord.id))
    )).scalar() or 0

    images = (await session.execute(
        select(func.count(SAObjectImage.id))
    )).scalar() or 0

    cultures = (await session.execute(
        select(func.count(distinct(SASourceRecord.culture))).where(
            SASourceRecord.culture.isnot(None), SASourceRecord.culture != ""
        )
    )).scalar() or 0

    languages = (await session.execute(
        select(func.count(distinct(SASourceVersion.language))).where(
            SASourceVersion.language.isnot(None), SASourceVersion.language != ""
        )
    )).scalar() or 0

    segments = (await session.execute(
        select(func.count(SASegment.id))
    )).scalar() or 0

    story_chapters = (await session.execute(
        select(func.count(StoryChapter.id))
    )).scalar() or 0

    total_words = (await session.execute(
        select(func.sum(StoryChapter.word_count))
    )).scalar() or 0

    planned_chapters = (await session.execute(
        select(func.count(StoryOutline.id))
    )).scalar() or 0

    epochs = (await session.execute(
        select(func.count(CanonicalEpoch.id)).where(CanonicalEpoch.is_current.is_(True))
    )).scalar() or 0

    actors = (await session.execute(
        select(func.count(CanonicalActor.id)).where(CanonicalActor.is_current.is_(True))
    )).scalar() or 0

    events = (await session.execute(
        select(func.count(CanonicalEvent.id)).where(CanonicalEvent.is_current.is_(True))
    )).scalar() or 0

    places = (await session.execute(
        select(func.count(CanonicalPlace.id)).where(CanonicalPlace.is_current.is_(True))
    )).scalar() or 0

    return {
        "total_source_records": source_records,
        "total_images": images,
        "total_cultures": cultures,
        "total_languages": languages,
        "total_segments": segments,
        "total_story_chapters": story_chapters,
        "total_planned_chapters": planned_chapters,
        "total_words": total_words,
        "total_epochs": epochs,
        "total_canonical_actors": actors,
        "total_canonical_events": events,
        "total_canonical_places": places,
    }


async def _get_chapter_images(session: AsyncSession, story_chapter_id) -> list[dict]:
    """Get completed generated images for a story chapter."""
    q = select(ImageGenerationJob).where(
        ImageGenerationJob.story_chapter_id == story_chapter_id,
        ImageGenerationJob.status == "completed",
    ).order_by(ImageGenerationJob.created_at)
    jobs = (await session.execute(q)).scalars().all()
    return [
        {
            "url": j.result_url or "",
            "caption": j.prompt_text[:150] if j.prompt_text else "",
            "prompt": j.prompt_text,
        }
        for j in jobs
    ]
