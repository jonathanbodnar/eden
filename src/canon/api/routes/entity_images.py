"""Shared utility for fetching images linked to canonical entities via support links,
plus direct image discovery by culture/date for epochs without full support-link chains."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.system_a import SAObjectImage, SARawObject, SASourceDate, SASourceRecord


async def get_entity_images(
    session: AsyncSession,
    entity_ids: list[uuid.UUID],
    limit: int = 10000,
) -> dict[uuid.UUID, list[dict]]:
    """Return images keyed by canonical entity ID.

    Walks: canonical_id → support_link → source_record → raw_object → object_images
    """
    if not entity_ids:
        return {}

    link_q = select(
        CanonSupportLink.canonical_id,
        CanonSupportLink.archive_object_id,
    ).where(
        CanonSupportLink.canonical_id.in_(entity_ids),
    )
    links = (await session.execute(link_q)).all()
    if not links:
        return {}

    entity_to_sr: dict[uuid.UUID, set[uuid.UUID]] = {}
    all_sr_ids: set[uuid.UUID] = set()
    for canonical_id, archive_id in links:
        entity_to_sr.setdefault(canonical_id, set()).add(archive_id)
        all_sr_ids.add(archive_id)

    sr_to_ro_q = select(SASourceRecord.id, SASourceRecord.raw_object_id).where(
        SASourceRecord.id.in_(list(all_sr_ids))
    )
    sr_to_ro = {
        row[0]: row[1]
        for row in (await session.execute(sr_to_ro_q)).all()
    }

    all_ro_ids = set(sr_to_ro.values())
    if not all_ro_ids:
        return {}

    img_q = (
        select(SAObjectImage)
        .where(
            SAObjectImage.raw_object_id.in_(list(all_ro_ids)),
            SAObjectImage.image_url.isnot(None),
        )
        .order_by(SAObjectImage.image_order)
    )
    all_images = (await session.execute(img_q)).scalars().all()

    ro_to_images: dict[uuid.UUID, list] = {}
    for img in all_images:
        ro_to_images.setdefault(img.raw_object_id, []).append(img)

    result: dict[uuid.UUID, list[dict]] = {}
    for eid in entity_ids:
        images_for_entity: list[dict] = []
        seen_urls: set[str] = set()
        for sr_id in entity_to_sr.get(eid, set()):
            ro_id = sr_to_ro.get(sr_id)
            if not ro_id:
                continue
            for img in ro_to_images.get(ro_id, []):
                if img.image_url in seen_urls:
                    continue
                seen_urls.add(img.image_url)
                images_for_entity.append({
                    "id": str(img.id),
                    "image_url": img.image_url,
                    "caption": img.caption,
                    "alt_text": img.alt_text,
                })
                if len(images_for_entity) >= limit:
                    break
            if len(images_for_entity) >= limit:
                break
        result[eid] = images_for_entity

    return result


async def get_epoch_images(
    session: AsyncSession,
    chapter_ids: list[uuid.UUID],
    limit: int = 20,
    time_start: int | None = None,
    time_end: int | None = None,
) -> list[dict]:
    """Get images for an epoch. Tries chapter-linked sources first, then
    falls back to direct discovery by date range."""
    images: list[dict] = []

    if chapter_ids:
        from src.canon.models.chapter_source_set import ChapterSourceSet

        sr_q = (
            select(ChapterSourceSet.source_record_id)
            .where(ChapterSourceSet.chapter_id.in_(chapter_ids))
            .distinct()
        )
        sr_ids = [r[0] for r in (await session.execute(sr_q)).all()]
        if sr_ids:
            images = await _images_from_source_records(session, sr_ids[:500], limit)

    if len(images) < limit:
        remaining = limit - len(images)
        seen_ids = {img["id"] for img in images}
        direct = await discover_images_by_date(
            session, time_start, time_end, limit=remaining,
        )
        for img in direct:
            if img["id"] not in seen_ids:
                images.append(img)

    return images[:limit]


async def discover_images_by_date(
    session: AsyncSession,
    time_start: int | None,
    time_end: int | None,
    culture: str | None = None,
    limit: int = 10000,
) -> list[dict]:
    """Find images directly from source records matching a date range and/or culture.
    Bypasses the canon support-link chain entirely."""

    sr_q = (
        select(SASourceRecord.raw_object_id)
        .distinct()
        .limit(limit * 5)
    )

    if time_start is not None or time_end is not None:
        date_filter = select(SASourceDate.source_record_id).distinct()
        if time_start is not None and time_end is not None:
            date_filter = date_filter.where(
                SASourceDate.date_start <= time_end,
                SASourceDate.date_end >= time_start,
            )
        elif time_start is not None:
            date_filter = date_filter.where(SASourceDate.date_start >= time_start)
        else:
            date_filter = date_filter.where(SASourceDate.date_end <= time_end)
        sr_q = sr_q.where(SASourceRecord.id.in_(date_filter))

    if culture:
        sr_q = sr_q.where(SASourceRecord.culture == culture)

    # Only get records that actually have images (join through raw_objects)
    sr_q = sr_q.where(
        SASourceRecord.raw_object_id.in_(
            select(SAObjectImage.raw_object_id).distinct()
        )
    )

    ro_ids = [r[0] for r in (await session.execute(sr_q)).all()]
    if not ro_ids:
        return []

    return await _images_from_raw_objects(session, ro_ids, limit)


async def discover_images_for_culture(
    session: AsyncSession,
    culture: str,
    limit: int = 10000,
) -> list[dict]:
    """Find images from source records of a specific culture."""
    return await discover_images_by_date(session, None, None, culture=culture, limit=limit)


async def _images_from_source_records(
    session: AsyncSession,
    sr_ids: list[uuid.UUID],
    limit: int,
) -> list[dict]:
    ro_q = select(SASourceRecord.raw_object_id).where(
        SASourceRecord.id.in_(sr_ids)
    )
    ro_ids = list({r[0] for r in (await session.execute(ro_q)).all()})
    if not ro_ids:
        return []
    return await _images_from_raw_objects(session, ro_ids, limit)


async def _images_from_raw_objects(
    session: AsyncSession,
    ro_ids: list[uuid.UUID],
    limit: int,
) -> list[dict]:
    img_q = (
        select(SAObjectImage)
        .where(
            SAObjectImage.raw_object_id.in_(ro_ids[:500]),
            SAObjectImage.image_url.isnot(None),
        )
        .order_by(func.random())
        .limit(limit)
    )
    images = (await session.execute(img_q)).scalars().all()

    return [
        {
            "id": str(img.id),
            "image_url": img.image_url,
            "caption": img.caption,
            "alt_text": img.alt_text,
        }
        for img in images
    ]
