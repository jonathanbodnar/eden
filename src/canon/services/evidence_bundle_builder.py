"""EvidenceBundleBuilder: populates chapter_source_sets, chapter_context_sets,
chapter_artifact_sets, and chapter_image_sets by querying System A tables
through canon_support_links."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.chapter_artifact_set import ChapterArtifactSet
from src.canon.models.chapter_context_set import ChapterContextSet
from src.canon.models.chapter_image_set import ChapterImageSet
from src.canon.models.chapter_source_set import ChapterSourceSet
from src.canon.models.enums import ArchiveObjectType, CanonicalType
from src.canon.models.system_a import (
    SAContextualStatement,
    SAObjectImage,
    SARawObject,
    SASourceRecord,
)

logger = logging.getLogger(__name__)


class EvidenceBundleBuilder:
    async def build_for_chapter(self, session: AsyncSession, chapter_id: uuid.UUID) -> dict:
        """Build all evidence bundles for a single chapter by following support links
        from the chapter's actors/events/places back to System A records."""
        chapter = await session.get(CanonicalChapter, chapter_id)
        if not chapter:
            return {"error": "chapter not found"}

        support_links = await self._get_chapter_support_links(session, chapter)

        source_record_ids: dict[uuid.UUID, float] = {}
        statement_ids: dict[uuid.UUID, float] = {}
        segment_ids: dict[uuid.UUID, float] = {}

        for link in support_links:
            obj_type = link.archive_object_type
            weight = link.weight or 1.0
            if obj_type == ArchiveObjectType.SOURCE_RECORD.value or obj_type == ArchiveObjectType.SOURCE_RECORD:
                source_record_ids[link.archive_object_id] = max(source_record_ids.get(link.archive_object_id, 0), weight)
            elif obj_type == ArchiveObjectType.CONTEXTUAL_STATEMENT.value or obj_type == ArchiveObjectType.CONTEXTUAL_STATEMENT:
                statement_ids[link.archive_object_id] = max(statement_ids.get(link.archive_object_id, 0), weight)
            elif obj_type == ArchiveObjectType.SEGMENT.value or obj_type == ArchiveObjectType.SEGMENT:
                segment_ids[link.archive_object_id] = max(segment_ids.get(link.archive_object_id, 0), weight)

        await self._clear_existing(session, chapter_id)

        sources_created = await self._build_source_sets(session, chapter_id, source_record_ids)
        contexts_created = await self._build_context_sets(session, chapter_id, statement_ids)
        artifacts_created = await self._build_artifact_sets(session, chapter_id, source_record_ids)
        images_created = await self._build_image_sets(session, chapter_id, source_record_ids)

        await session.flush()

        return {
            "chapter_id": str(chapter_id),
            "sources": sources_created,
            "contexts": contexts_created,
            "artifacts": artifacts_created,
            "images": images_created,
        }

    async def build_all(self, session: AsyncSession) -> dict:
        """Build evidence bundles for every current chapter."""
        q = select(CanonicalChapter).where(CanonicalChapter.is_current.is_(True))
        chapters = (await session.execute(q)).scalars().all()
        results = []
        for ch in chapters:
            r = await self.build_for_chapter(session, ch.id)
            results.append(r)
        return {"chapters_processed": len(results), "results": results}

    async def _get_chapter_support_links(
        self, session: AsyncSession, chapter: CanonicalChapter
    ) -> list[CanonSupportLink]:
        """Gather support links for all canonical objects that belong to this chapter's
        time range, plus direct chapter-level links."""
        canon_types_to_search = [
            CanonicalType.CHAPTER,
            CanonicalType.ACTOR,
            CanonicalType.EVENT,
            CanonicalType.PLACE,
        ]

        q = select(CanonSupportLink).where(
            CanonSupportLink.canonical_type.in_([ct.value for ct in canon_types_to_search])
        )
        all_links = (await session.execute(q)).scalars().all()

        chapter_links = [l for l in all_links if l.canonical_type in (CanonicalType.CHAPTER.value, CanonicalType.CHAPTER) and l.canonical_id == chapter.id]

        from src.canon.models.canonical_actor import CanonicalActor
        from src.canon.models.canonical_event import CanonicalEvent
        from src.canon.models.canonical_place import CanonicalPlace

        for model, ctype in [
            (CanonicalActor, CanonicalType.ACTOR),
            (CanonicalEvent, CanonicalType.EVENT),
            (CanonicalPlace, CanonicalType.PLACE),
        ]:
            entity_q = select(model.id).where(model.is_current.is_(True))
            if chapter.time_start is not None:
                entity_q = entity_q.where(
                    (model.time_end.is_(None)) | (model.time_end >= chapter.time_start)
                )
            if chapter.time_end is not None:
                entity_q = entity_q.where(
                    (model.time_start.is_(None)) | (model.time_start <= chapter.time_end)
                )
            entity_ids = set((await session.execute(entity_q)).scalars().all())

            for l in all_links:
                cv = ctype.value if isinstance(ctype, CanonicalType) else ctype
                lv = l.canonical_type.value if hasattr(l.canonical_type, 'value') else l.canonical_type
                if lv == cv and l.canonical_id in entity_ids:
                    chapter_links.append(l)

        return chapter_links

    async def _clear_existing(self, session: AsyncSession, chapter_id: uuid.UUID) -> None:
        for model in [ChapterSourceSet, ChapterContextSet, ChapterArtifactSet, ChapterImageSet]:
            await session.execute(delete(model).where(model.chapter_id == chapter_id))

    async def _build_source_sets(
        self, session: AsyncSession, chapter_id: uuid.UUID, source_ids: dict[uuid.UUID, float]
    ) -> int:
        count = 0
        for src_id, weight in source_ids.items():
            record = await session.get(SASourceRecord, src_id)
            if not record:
                continue
            entry = ChapterSourceSet(
                id=uuid.uuid4(),
                chapter_id=chapter_id,
                source_record_id=src_id,
                title=record.canonical_title,
                excerpt=None,
                relevance_weight=weight,
                source_type=record.source_category,
            )
            session.add(entry)
            count += 1
        return count

    async def _build_context_sets(
        self, session: AsyncSession, chapter_id: uuid.UUID, statement_ids: dict[uuid.UUID, float]
    ) -> int:
        count = 0
        for stmt_id, weight in statement_ids.items():
            stmt = await session.get(SAContextualStatement, stmt_id)
            if not stmt:
                continue
            entry = ChapterContextSet(
                id=uuid.uuid4(),
                chapter_id=chapter_id,
                contextual_statement_id=stmt_id,
                summary=stmt.statement_text[:500] if stmt.statement_text else None,
                artifact_description=None,
                relevance_weight=weight,
            )
            session.add(entry)
            count += 1
        return count

    async def _build_artifact_sets(
        self, session: AsyncSession, chapter_id: uuid.UUID, source_ids: dict[uuid.UUID, float]
    ) -> int:
        count = 0
        for src_id in source_ids:
            record = await session.get(SASourceRecord, src_id)
            if not record or not record.raw_object_id:
                continue
            raw_obj = await session.get(SARawObject, record.raw_object_id)
            if not raw_obj:
                continue
            entry = ChapterArtifactSet(
                id=uuid.uuid4(),
                chapter_id=chapter_id,
                raw_object_id=raw_obj.id,
                title=record.canonical_title,
                description=None,
                image_url=None,
            )
            session.add(entry)
            count += 1
        return count

    async def _build_image_sets(
        self, session: AsyncSession, chapter_id: uuid.UUID, source_ids: dict[uuid.UUID, float]
    ) -> int:
        count = 0
        raw_object_ids = set()
        for src_id in source_ids:
            record = await session.get(SASourceRecord, src_id)
            if record and record.raw_object_id:
                raw_object_ids.add(record.raw_object_id)

        if not raw_object_ids:
            return 0

        q = select(SAObjectImage).where(SAObjectImage.raw_object_id.in_(list(raw_object_ids)))
        images = (await session.execute(q)).scalars().all()

        for idx, img in enumerate(images):
            entry = ChapterImageSet(
                id=uuid.uuid4(),
                chapter_id=chapter_id,
                object_image_id=img.id,
                image_url=img.image_url,
                caption=img.caption or img.alt_text,
                image_type="artifact_image",
                display_order=idx,
            )
            session.add(entry)
            count += 1
        return count
