"""Story Mode API routes — serves the unified narrative for the frontend."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid as _uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select, func, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
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

_CULTURE_HINTS = [
    (["yahweh", "yhwh", "elohim", "hebrew", "israel", "moses", "adam", "eve", "noah", "abraham",
      "genesis", "tehom", "tohu", "bohu", "eden"], "Hebrew / Israelite"),
    (["enki", "enlil", "anu", "marduk", "tiamat", "apsu", "gilgamesh", "sumerian", "akkadian",
      "babylonian", "mesopotami", "enuma elish", "eridu"], "Mesopotamian"),
    (["atum", "osiris", "isis", "horus", "thoth", "ptah", "khnum", "egyptian", "kemet",
      "pharaoh", "pyramid text", "nun"], "Ancient Egyptian"),
    (["brahma", "vishnu", "shiva", "prajapati", "purusha", "vedic", "hindu", "sanskrit",
      "indra", "agni", "rig veda", "manu", "hiranyagarbha"], "Vedic / Hindu"),
    (["zeus", "prometheus", "athena", "apollo", "greek", "olymp", "titan", "hesiod", "homer"], "Greek"),
    (["odin", "thor", "freya", "norse", "ymir", "asgard", "edda"], "Norse / Germanic"),
    (["ahura mazda", "zoroast", "avesta", "persian", "zarathustra", "angra mainyu"], "Zoroastrian / Persian"),
    (["quetzalcoatl", "tezcatlipoca", "aztec", "maya", "popol vuh", "mesoameric"], "Mesoamerican"),
    (["dreamtime", "aboriginal", "rainbow serpent", "wandjina"], "Australian Aboriginal"),
    (["ainu", "kamuy"], "Ainu / Japanese"),
    (["maori", "tane", "polynesi"], "Polynesian / Maori"),
    (["sky father", "great spirit", "plains", "native american"], "Indigenous / Cross-cultural"),
    (["chinese", "pangu", "nuwa", "fuxi", "jade emperor"], "Chinese"),
]

_VAGUE_CULTURES = {"ancient", "unknown", "other", "unspecified", "general"}


_WORD_BOUNDARY_RE = re.compile(r'\b(?:' + '|'.join([
    'ra',
]) + r')\b', re.IGNORECASE)


def _infer_culture_from_entity(name: str, summary: str) -> list[str]:
    """Best-effort culture inference from entity name/summary when DB has no culture data."""
    combined = f"{name} {summary}".lower()
    cultures = []
    for keywords, culture in _CULTURE_HINTS:
        if any(kw in combined for kw in keywords):
            cultures.append(culture)
    if _WORD_BOUNDARY_RE.search(f"{name} {summary}"):
        if "Ancient Egyptian" not in cultures:
            cultures.append("Ancient Egyptian")
    return cultures


def _refine_cultures(db_cultures: list[str], name: str, summary: str) -> list[str]:
    """Replace vague DB cultures (e.g. 'Ancient') with specific inferred ones when possible."""
    specific = [c for c in db_cultures if c.lower() not in _VAGUE_CULTURES]
    vague = [c for c in db_cultures if c.lower() in _VAGUE_CULTURES]
    if not vague:
        return db_cultures
    inferred = _infer_culture_from_entity(name, summary)
    new_cultures = [c for c in inferred if c not in specific]
    if new_cultures:
        return specific + new_cultures
    return db_cultures


def _build_merge_reasoning(entity_name: str, entity_summary: str | None, archetype_name: str, cultures: list[str]) -> str:
    """Build a meaningful explanation of why this entity belongs to the archetype."""
    culture_str = cultures[0] if cultures else "its tradition"
    summary_snippet = ""
    if entity_summary:
        first_sentence = entity_summary.split(". ")[0].rstrip(".")
        if len(first_sentence) < 150:
            summary_snippet = first_sentence
        else:
            summary_snippet = first_sentence[:147] + "..."

    if summary_snippet:
        return f"{culture_str} tradition: {summary_snippet}. Shares core attributes and cosmological role with other identities in this archetype."
    return f"Represents the {archetype_name} concept within the {culture_str} tradition. Shares core attributes and cosmological role with other identities in this archetype."


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
    entity_type: str,
    entity_id: str,
    aka: str | None = None,
    all_ids: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Get the merge breakdown for a canonical entity — which entities were unified,
    why, and the source evidence for each component.

    Args:
        aka: comma-separated list of also-known-as names from the narrative's
             entity mentions (used to find additional equivalences not in the DB).
        all_ids: comma-separated list of ALL canonical IDs matched by the archetype's
                 also_known_as names (for proper multi-culture display).
    """
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

            if other_cultures and other_name:
                other_cultures = _refine_cultures(other_cultures, other_name, other_summary or "")
            elif not other_cultures and other_name:
                other_cultures = _infer_culture_from_entity(other_name, other_summary or "")

            evidence = r.get("evidence_json") or {}
            db_reasoning = evidence.get("reasoning", "")
            if not db_reasoning and other_name:
                db_reasoning = _build_merge_reasoning(other_name, other_summary, entity_info["name"], other_cultures)
            equivalences.append({
                "equivalent_id": str(other_id),
                "equivalent_type": other_type,
                "equivalent_name": other_name,
                "equivalent_summary": other_summary,
                "cultures": other_cultures,
                "merge_basis": r["merge_basis"],
                "confidence": r["confidence"],
                "reasoning": db_reasoning,
                "role_match": evidence.get("role_match"),
                "action_match": evidence.get("action_match"),
                "context_match": evidence.get("context_match"),
                "pattern_match": evidence.get("pattern_match"),
            })
    except Exception:
        logger.exception("Failed to get equivalences")

    # Enrich with also_known_as names from the narrative (finds entities that
    # share the same archetype but aren't in entity_equivalences yet)
    if aka:
        aka_names = [n.strip() for n in aka.split(",") if n.strip()]
        existing_ids = {eq["equivalent_id"] for eq in equivalences}
        existing_ids.add(entity_id)

        for aka_name in aka_names:
            aka_lower = aka_name.lower()
            found_entity = None
            found_type = entity_type

            for tbl_type, tbl in [("actor", CanonicalActor), ("event", CanonicalEvent), ("place", CanonicalPlace)]:
                try:
                    q = select(tbl).where(
                        func.lower(tbl.canonical_name) == aka_lower,
                        tbl.is_current.is_(True),
                    ).limit(1)
                    row = (await session.execute(q)).scalar_one_or_none()
                    if row:
                        found_entity = row
                        found_type = tbl_type
                        break
                except Exception:
                    pass

            if not found_entity or str(found_entity.id) in existing_ids:
                continue
            existing_ids.add(str(found_entity.id))

            aka_cultures = []
            try:
                aka_type_map = {"actor": CanonicalType.ACTOR, "event": CanonicalType.EVENT, "place": CanonicalType.PLACE}
                c_q = (
                    select(distinct(SASourceRecord.culture))
                    .select_from(CanonSupportLink)
                    .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
                    .where(
                        CanonSupportLink.canonical_type == aka_type_map.get(found_type, CanonicalType.ACTOR),
                        CanonSupportLink.canonical_id == found_entity.id,
                        SASourceRecord.culture.isnot(None),
                        SASourceRecord.culture != "",
                    ).limit(10)
                )
                aka_cultures = [c[0] for c in (await session.execute(c_q)).all()]
            except Exception:
                pass

            entity_name_for_inf = found_entity.canonical_name
            entity_summary_for_inf = getattr(found_entity, "summary", "") or ""
            if aka_cultures:
                aka_cultures = _refine_cultures(aka_cultures, entity_name_for_inf, entity_summary_for_inf)
            elif not aka_cultures:
                aka_cultures = _infer_culture_from_entity(entity_name_for_inf, entity_summary_for_inf)

            equivalences.append({
                "equivalent_id": str(found_entity.id),
                "equivalent_type": found_type,
                "equivalent_name": found_entity.canonical_name,
                "equivalent_summary": found_entity.summary,
                "cultures": aka_cultures,
                "merge_basis": "narrative_convergence",
                "confidence": 0.85,
                "reasoning": _build_merge_reasoning(
                    found_entity.canonical_name,
                    found_entity.summary,
                    entity_info["name"],
                    aka_cultures,
                ),
                "role_match": True,
                "action_match": True,
                "context_match": True,
                "pattern_match": True,
            })

    # Resolve all_ids: these are additional canonical entities that the narrative
    # synthesizer matched to this archetype's also_known_as names
    if all_ids:
        extra_ids = [i.strip() for i in all_ids.split(",") if i.strip()]
        existing_ids = {eq["equivalent_id"] for eq in equivalences}
        existing_ids.add(entity_id)

        for extra_id_str in extra_ids:
            if extra_id_str in existing_ids:
                continue
            existing_ids.add(extra_id_str)
            try:
                extra_uuid = _uuid.UUID(extra_id_str)
            except ValueError:
                continue

            found_entity = None
            found_type = entity_type
            for tbl_type, tbl in [("actor", CanonicalActor), ("event", CanonicalEvent), ("place", CanonicalPlace)]:
                try:
                    row = await session.get(tbl, extra_uuid)
                    if row:
                        found_entity = row
                        found_type = tbl_type
                        break
                except Exception:
                    pass

            if not found_entity:
                continue

            extra_cultures = []
            try:
                aka_type_map = {"actor": CanonicalType.ACTOR, "event": CanonicalType.EVENT, "place": CanonicalType.PLACE}
                c_q = (
                    select(distinct(SASourceRecord.culture))
                    .select_from(CanonSupportLink)
                    .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
                    .where(
                        CanonSupportLink.canonical_type == aka_type_map.get(found_type, CanonicalType.ACTOR),
                        CanonSupportLink.canonical_id == extra_uuid,
                        SASourceRecord.culture.isnot(None),
                        SASourceRecord.culture != "",
                    ).limit(10)
                )
                extra_cultures = [c[0] for c in (await session.execute(c_q)).all()]
            except Exception:
                pass

            ename = found_entity.canonical_name
            esummary = getattr(found_entity, "summary", "") or ""
            if extra_cultures:
                extra_cultures = _refine_cultures(extra_cultures, ename, esummary)
            elif not extra_cultures:
                extra_cultures = _infer_culture_from_entity(ename, esummary)

            equivalences.append({
                "equivalent_id": extra_id_str,
                "equivalent_type": found_type,
                "equivalent_name": ename,
                "equivalent_summary": esummary,
                "cultures": extra_cultures,
                "merge_basis": "narrative_convergence",
                "confidence": 0.85,
                "reasoning": _build_merge_reasoning(ename, esummary, entity_info["name"], extra_cultures),
                "role_match": True,
                "action_match": True,
                "context_match": True,
                "pattern_match": True,
            })

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

    if primary_cultures:
        primary_cultures = _refine_cultures(primary_cultures, entity_info["name"], entity_info.get("summary") or "")
    else:
        primary_cultures = _infer_culture_from_entity(entity_info["name"], entity_info.get("summary") or "")

    # Include the resolved/primary entity as a peer in equivalences so
    # the frontend treats ALL cultural identities equally under the archetype.
    resolved_peer = {
        "equivalent_id": entity_info["id"],
        "equivalent_type": entity_info["type"],
        "equivalent_name": entity_info["name"],
        "equivalent_summary": entity_info.get("summary"),
        "cultures": primary_cultures,
        "merge_basis": "primary_resolution",
        "confidence": 1.0,
        "reasoning": _build_merge_reasoning(
            entity_info["name"],
            entity_info.get("summary"),
            entity_info["name"],
            primary_cultures,
        ),
        "role_match": True,
        "action_match": True,
        "context_match": True,
        "pattern_match": True,
    }
    all_identities = [resolved_peer] + equivalences

    # Collect all cultures across all identities
    all_cultures = list(dict.fromkeys(
        c for ident in all_identities for c in ident.get("cultures", [])
    ))

    return {
        "entity": entity_info,
        "cultures": all_cultures,
        "equivalences": all_identities,
        "sources": sources,
    }


@router.get("/chapters/{story_chapter_id}/culture-variants")
async def get_culture_variants(
    story_chapter_id: str,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Return the list of cultures that have generated narratives for this chapter."""
    from src.canon.models.culture_narrative import CultureNarrative

    sc = await session.get(StoryChapter, _uuid.UUID(story_chapter_id))
    if not sc:
        raise HTTPException(404, "Story chapter not found")

    narr_q = select(
        CultureNarrative.culture_key,
        CultureNarrative.culture_label,
        CultureNarrative.word_count,
        CultureNarrative.source_count,
    ).where(
        CultureNarrative.story_outline_id == sc.story_outline_id,
    ).order_by(CultureNarrative.culture_key)

    rows = (await session.execute(narr_q)).all()

    results = []
    for culture_key, culture_label, word_count, source_count in rows:
        if q and q.lower() not in culture_label.lower():
            continue
        results.append({
            "culture": culture_label,
            "culture_key": culture_key,
            "source_count": source_count or 0,
            "word_count": word_count or 0,
            "source_texts": [],
            "actors": [],
            "events": [],
            "places": [],
        })

    return results


@router.get("/chapters/{story_chapter_id}/culture-detail")
async def get_culture_detail(
    story_chapter_id: str,
    culture: str,
    session: AsyncSession = Depends(get_session),
):
    """Load a culture's generated narrative + source texts for the right panel."""
    from src.canon.models.culture_narrative import CultureNarrative

    sc = await session.get(StoryChapter, _uuid.UUID(story_chapter_id))
    if not sc:
        raise HTTPException(404, "Story chapter not found")

    # Try matching by culture_key first, then by culture_label
    culture_lower = culture.lower().strip()
    narr = (await session.execute(
        select(CultureNarrative).where(
            CultureNarrative.story_outline_id == sc.story_outline_id,
            func.lower(CultureNarrative.culture_key) == culture_lower,
        ).limit(1)
    )).scalar_one_or_none()

    if not narr:
        narr = (await session.execute(
            select(CultureNarrative).where(
                CultureNarrative.story_outline_id == sc.story_outline_id,
                func.lower(CultureNarrative.culture_label) == culture_lower,
            ).limit(1)
        )).scalar_one_or_none()

    if not narr:
        # Fuzzy match on label
        narr = (await session.execute(
            select(CultureNarrative).where(
                CultureNarrative.story_outline_id == sc.story_outline_id,
                CultureNarrative.culture_label.ilike(f"%{culture}%"),
            ).limit(1)
        )).scalar_one_or_none()

    if not narr:
        return {
            "culture": culture,
            "narrative_text": None,
            "source_count": 0,
            "source_texts": [],
            "actors": [],
            "events": [],
            "places": [],
        }

    # Load source texts from source_ids
    source_texts = []
    source_ids = narr.source_ids or []
    if source_ids:
        ids_list = ",".join(f"'{sid}'" for sid in source_ids[:15])
        try:
            src_q = text(f"""
                SELECT sr.canonical_title, sr.culture,
                    LEFT(sv.text_extracted, 1500), 1.0 as weight
                FROM source_records sr
                JOIN source_versions sv ON sv.source_record_id = sr.id
                WHERE sr.id IN ({ids_list})
                  AND sv.text_extracted IS NOT NULL
                  AND LENGTH(sv.text_extracted) > 100
                LIMIT 10
            """)
            src_rows = (await session.execute(src_q)).all()
            source_texts = [
                {"title": r[0] or "Unknown", "culture": r[1], "text": r[2] or "", "weight": float(r[3])}
                for r in src_rows
            ]
        except Exception:
            logger.exception("Failed to load source texts for culture %s", culture)

    return {
        "culture": narr.culture_label,
        "culture_key": narr.culture_key,
        "narrative_text": narr.narrative_text,
        "source_count": narr.source_count or 0,
        "word_count": narr.word_count or 0,
        "source_texts": source_texts,
        "actors": narr.actors_json or [],
        "events": narr.events_json or [],
        "places": narr.places_json or [],
    }


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


# ── Audio TTS endpoints ───────────────────────────────────────────────────

_ENTITY_RE = re.compile(r"\[\[(actor|event|place):([^\]]+)\]\]")


def _strip_annotations(narrative: str) -> str:
    """Remove [[type:Name]] markup, keeping just the entity name."""
    return _ENTITY_RE.sub(r"\2", narrative)


@router.head("/chapters/{story_chapter_id}/audio")
@router.get("/chapters/{story_chapter_id}/audio")
async def get_chapter_audio(
    story_chapter_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Serve cached MP3 audio for a chapter, with Range header support."""
    cid = _uuid.UUID(story_chapter_id)
    row = (await session.execute(
        text("SELECT audio_data, duration_seconds FROM story_chapter_audio WHERE story_chapter_id = :cid"),
        {"cid": str(cid)},
    )).first()

    if not row:
        raise HTTPException(404, "Audio not generated yet")

    audio_bytes: bytes = row[0]
    total = len(audio_bytes)

    range_header = request.headers.get("range")
    if range_header:
        try:
            range_spec = range_header.replace("bytes=", "")
            start_str, end_str = range_spec.split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else total - 1
            end = min(end, total - 1)
            chunk = audio_bytes[start : end + 1]
            return Response(
                content=chunk,
                status_code=206,
                media_type="audio/mpeg",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(chunk)),
                },
            )
        except Exception:
            pass

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(total),
        },
    )


_audio_tasks: dict[str, str] = {}  # chapter_id -> "generating" | "failed:<msg>"


async def _generate_audio_background(story_chapter_id: str) -> None:
    """Run Cartesia TTS in background, store result in DB."""
    from src.canon.database import async_session_factory

    cid_str = str(story_chapter_id)
    try:
        # Read chapter text in a short-lived session, then close it
        # before the long TTS call so the connection doesn't go stale.
        async with async_session_factory() as session:
            chapter = await session.get(StoryChapter, _uuid.UUID(cid_str))
            if not chapter:
                _audio_tasks[cid_str] = "failed:Chapter not found"
                return

            outline = await session.get(StoryOutline, chapter.story_outline_id) if chapter.story_outline_id else None
            title = outline.title if outline else "Chapter"
            clean_text = _strip_annotations(chapter.narrative_text or "")
            transcript = f"{title}\n\n{clean_text}"

        # TTS call can take minutes — no DB connection held open
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "X-API-Key": settings.cartesia_api_key,
                    "Cartesia-Version": "2026-03-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model_id": "sonic-3",
                    "transcript": transcript,
                    "voice": {
                        "mode": "id",
                        "id": settings.cartesia_voice_id,
                    },
                    "language": "en",
                    "output_format": {
                        "container": "mp3",
                        "sample_rate": 44100,
                        "bit_rate": 128000,
                    },
                    "generation_config": {
                        "speed": 0.9,
                        "emotion": "contemplative",
                    },
                },
            )
            if resp.status_code != 200:
                logger.error("Cartesia TTS error %s: %s", resp.status_code, resp.text[:500])
                _audio_tasks[cid_str] = f"failed:Cartesia error {resp.status_code}"
                return

            audio_bytes = resp.content

        word_count = len(transcript.split())
        estimated_duration = word_count / 2.5

        # Fresh session for the DB write — guaranteed live connection
        async with async_session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO story_chapter_audio (story_chapter_id, audio_data, duration_seconds, file_size_bytes, voice_id, model_id)
                    VALUES (:cid, :audio, :dur, :size, :voice, :model)
                    ON CONFLICT (story_chapter_id) DO UPDATE SET
                        audio_data = EXCLUDED.audio_data,
                        duration_seconds = EXCLUDED.duration_seconds,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        created_at = now()
                """),
                {
                    "cid": cid_str,
                    "audio": audio_bytes,
                    "dur": estimated_duration,
                    "size": len(audio_bytes),
                    "voice": settings.cartesia_voice_id,
                    "model": "sonic-3",
                },
            )
            await session.commit()

        _audio_tasks.pop(cid_str, None)
        logger.info("Audio generated for chapter %s (%d bytes)", cid_str, len(audio_bytes))
    except Exception as e:
        logger.exception("Background audio generation failed for %s", cid_str)
        _audio_tasks[cid_str] = f"failed:{e}"


@router.post("/chapters/{story_chapter_id}/audio")
async def generate_chapter_audio(
    story_chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Kick off TTS generation in background. Returns immediately with status."""
    cid = _uuid.UUID(story_chapter_id)
    cid_str = str(cid)

    existing = (await session.execute(
        text("SELECT id FROM story_chapter_audio WHERE story_chapter_id = :cid"),
        {"cid": cid_str},
    )).first()
    if existing:
        return {"status": "already_exists"}

    task_status = _audio_tasks.get(cid_str)
    if task_status == "generating":
        return {"status": "generating"}
    if task_status and task_status.startswith("failed:"):
        msg = task_status[7:]
        _audio_tasks.pop(cid_str, None)
        raise HTTPException(502, f"Audio generation failed: {msg}")

    chapter = await session.get(StoryChapter, cid)
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    if not settings.cartesia_api_key:
        raise HTTPException(500, "Cartesia API key not configured")

    _audio_tasks[cid_str] = "generating"
    asyncio.create_task(_generate_audio_background(cid_str))

    return {"status": "generating"}
