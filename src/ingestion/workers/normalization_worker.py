"""Normalization worker: converts raw objects into canonical source records."""

from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.models.enums import (
    CopyrightStatus,
    DatingConfidence,
    DateType,
    JobType,
    ProvenanceStatus,
    RecordStatus,
    SourceCategory,
    VersionType,
)
from src.ingestion.models.job_checkpoint import JobCheckpoint
from src.ingestion.models.queued_job import QueuedJob
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.source_date import SourceDate
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.queue.manager import update_source_progress
from src.ingestion.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class NormalizationWorker(BaseWorker):
    job_types = [JobType.NORMALIZE]

    async def process(
        self,
        session: AsyncSession,
        job: QueuedJob,
        checkpoint: JobCheckpoint | None,
    ) -> None:
        from src.ingestion.queue.manager import is_upstream_done

        source = await session.get(TrustedSource, job.trusted_source_id)
        if not source:
            return

        records_processed = 0
        if checkpoint:
            records_processed = checkpoint.records_processed

        empty_polls = 0

        while True:
            result = await session.execute(
                select(RawObject)
                .where(RawObject.trusted_source_id == source.id)
                .where(~RawObject.id.in_(
                    select(SourceRecord.raw_object_id).where(SourceRecord.raw_object_id.isnot(None))
                ))
                .order_by(RawObject.fetched_at)
                .limit(200)
                .with_for_update(skip_locked=True)
            )
            batch = result.scalars().all()

            if not batch:
                upstream_done = await is_upstream_done(session, job.source_run_id, job.job_type)
                if upstream_done:
                    empty_polls += 1
                    if empty_polls >= 2:
                        logger.info("Normalize %s: upstream done, no more records", source.slug)
                        break
                await asyncio.sleep(3.0)
                continue

            empty_polls = 0
            for raw_obj in batch:
                try:
                    await self._normalize_raw_object(session, source, raw_obj)
                    records_processed += 1
                except Exception as exc:
                    logger.error("Failed to normalize %s: %s", raw_obj.id, exc)

            await update_source_progress(session, source.id, normalized_count=records_processed)
            await session.commit()
            logger.info("Normalize %s: %d done (committed)", source.slug, records_processed)

        await update_source_progress(session, source.id, normalized_count=records_processed)

    async def _normalize_raw_object(
        self,
        session: AsyncSession,
        source: TrustedSource,
        raw_obj: RawObject,
    ) -> SourceRecord:
        """Parse raw object metadata into canonical record.

        Uses the source's parser_type to determine parsing strategy.
        JSON API sources get rich structured normalization; HTML sources
        fall back to basic metadata extraction.
        """
        meta = raw_obj.raw_metadata_jsonb or {}

        has_provenance = bool(
            meta.get("origin_place")
            or meta.get("findspot_comments")
            or meta.get("excavation")
            or meta.get("geography", {}).get("excavation")
        )

        def _to_str(val, maxlen=500):
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            if isinstance(val, str) and len(val) > maxlen:
                return val[:maxlen]
            return val

        title = _to_str(meta.get("title", f"Record {raw_obj.external_id}"))

        existing = (await session.execute(
            select(SourceRecord).where(
                SourceRecord.trusted_source_id == source.id,
                SourceRecord.canonical_title == title,
            ).limit(1)
        )).scalar_one_or_none()
        if existing:
            logger.info("Skipping duplicate: %s already exists for source %s", title, source.slug)
            return

        source_record = SourceRecord(
            trusted_source_id=source.id,
            raw_object_id=raw_obj.id,
            canonical_title=title,
            source_category=source.source_category,
            culture=_to_str(meta.get("culture")),
            language_family=_to_str(meta.get("language_family", source.default_language)),
            origin_place_name=_to_str(meta.get("origin_place")),
            repository_institution=_to_str(meta.get("repository")),
            provenance_status=ProvenanceStatus.UNVERIFIED if has_provenance else ProvenanceStatus.UNKNOWN,
            record_status=RecordStatus.NORMALIZED,
            latitude=meta.get("latitude"),
            longitude=meta.get("longitude"),
            metadata_jsonb={k: v for k, v in meta.items() if k != "_raw"},
        )

        session.add(source_record)
        await session.flush()

        if "dates" in meta:
            for date_info in meta["dates"]:
                try:
                    date_record = SourceDate(
                        source_record_id=source_record.id,
                        date_type=DateType(date_info.get("type", "composition")),
                        date_start=date_info.get("start"),
                        date_end=date_info.get("end"),
                        date_label=date_info.get("label"),
                        dating_method=date_info.get("method"),
                        dating_confidence=DatingConfidence(
                            date_info.get("confidence", "uncertain")
                        ),
                        source_note=date_info.get("note"),
                    )
                    session.add(date_record)
                except Exception as exc:
                    logger.warning("Failed to add date for %s: %s", raw_obj.external_id, exc)

        text_content = meta.get("text", "")
        if text_content:
            text_content = re.sub(r"<[^>]+>", " ", text_content)
            text_content = text_content.replace("&nbsp;", " ").replace("&amp;", "&")
            text_content = re.sub(r"\s+", " ", text_content).strip()
        if not text_content:
            text_content = self._synthesize_description(meta)

        copyright_status = CopyrightStatus.UNKNOWN
        if meta.get("is_public_domain"):
            copyright_status = CopyrightStatus.PUBLIC_DOMAIN

        version = SourceVersion(
            source_record_id=source_record.id,
            version_type=VersionType.MUSEUM_DESCRIPTION if not meta.get("text") else VersionType.ORIGINAL,
            language=meta.get("language_family", source.default_language),
            copyright_status=copyright_status,
            is_preferred=True,
            r2_key=raw_obj.r2_key,
            text_extracted=text_content if text_content else None,
            metadata_jsonb={"parser": source.parser_type.value},
        )
        session.add(version)

        if meta.get("text") and meta.get("text_format") == "ATF":
            transliteration = SourceVersion(
                source_record_id=source_record.id,
                version_type=VersionType.TRANSLITERATION,
                language="Sumerian",
                copyright_status=CopyrightStatus.PUBLIC_DOMAIN,
                is_preferred=False,
                text_extracted=meta["text"],
                metadata_jsonb={"format": "ATF", "parser": "cdli_atf"},
            )
            session.add(transliteration)

        for tr in meta.get("translations", []):
            if not isinstance(tr, dict) or not tr.get("text"):
                continue
            tr_text = tr["text"]
            tr_text = re.sub(r"<[^>]+>", " ", tr_text)
            tr_text = tr_text.replace("&nbsp;", " ").replace("&amp;", "&")
            tr_text = re.sub(r"\s+", " ", tr_text).strip()
            if not tr_text:
                continue
            vtype = VersionType.ORIGINAL if tr.get("version_type") == "original" else VersionType.TRANSLATION
            tr_version = SourceVersion(
                source_record_id=source_record.id,
                version_type=vtype,
                language=tr.get("language", ""),
                translator_editor=tr.get("translator"),
                copyright_status=copyright_status,
                is_preferred=False,
                text_extracted=tr_text,
                metadata_jsonb={"parser": source.parser_type.value, "translation_source": meta.get("source_api", "")},
            )
            session.add(tr_version)

        await session.flush()
        return source_record

    @staticmethod
    def _synthesize_description(meta: dict) -> str:
        """Build a textual description from structured metadata.

        Captures all factual context: object type, material, culture,
        period, dynasty, findspot, excavation, geography, dimensions,
        repository, genre, tags, and publications.
        """
        parts: list[str] = []

        title = meta.get("title", "")
        if title:
            parts.append(title)

        obj_type = meta.get("object_type", "")
        medium = meta.get("medium", "")
        if obj_type and medium:
            parts.append(f"{obj_type}. Material: {medium}.")
        elif obj_type:
            parts.append(f"{obj_type}.")
        elif medium:
            parts.append(f"Material: {medium}.")

        culture = meta.get("culture", "")
        period = meta.get("period", "")
        dynasty = meta.get("dynasty", "")
        reign = meta.get("reign", "")
        date_label = meta.get("date_label", "")
        context_parts = [s for s in [culture, period, dynasty, reign, date_label] if s]
        if context_parts:
            parts.append(" | ".join(context_parts))

        genre = meta.get("genre", "")
        if genre:
            parts.append(f"Genre: {genre}")

        lang = meta.get("language_family", "")
        if lang:
            parts.append(f"Language: {lang}")

        geo = meta.get("geography") or {}
        geo_type = meta.get("geography_type", geo.get("geographyType", ""))
        origin = meta.get("origin_place", "")
        excavation = meta.get("excavation", geo.get("excavation", ""))
        locus = meta.get("locus", geo.get("locus", ""))
        river = meta.get("river", geo.get("river", ""))

        origin_line_parts = []
        if geo_type and origin:
            origin_line_parts.append(f"{geo_type}: {origin}")
        elif origin:
            origin_line_parts.append(f"Origin: {origin}")
        else:
            place_parts = [v for v in [geo.get("region"), geo.get("subregion"),
                                       geo.get("locale"), geo.get("city"),
                                       geo.get("country")] if v]
            if place_parts:
                origin_line_parts.append(f"Origin: {', '.join(place_parts)}")

        if excavation:
            origin_line_parts.append(f"Excavation: {excavation}")
        if locus:
            origin_line_parts.append(f"Locus: {locus}")
        if river:
            origin_line_parts.append(f"River: {river}")

        findspot = meta.get("findspot_comments", "")
        if findspot:
            origin_line_parts.append(f"Findspot: {findspot}")
        findspot_sq = meta.get("findspot_square", "")
        if findspot_sq:
            origin_line_parts.append(f"Grid square: {findspot_sq}")

        if origin_line_parts:
            parts.append("\n".join(origin_line_parts))

        dims = meta.get("dimensions", "")
        if dims:
            parts.append(f"Dimensions: {dims}.")

        museum_no = meta.get("museum_no", "")
        excavation_no = meta.get("excavation_no", "")
        if museum_no:
            parts.append(f"Museum number: {museum_no}")
        if excavation_no:
            parts.append(f"Excavation number: {excavation_no}")

        repo = meta.get("repository", "")
        acc = meta.get("accession_number", "")
        if repo:
            line = repo
            if acc:
                line += f" ({acc})"
            parts.append(line)

        credit = meta.get("credit_line", "")
        if credit:
            parts.append(credit)

        dept = meta.get("department", "")
        classification = meta.get("classification", "")
        if dept or classification:
            extra = [s for s in [dept, classification] if s]
            parts.append(f"Department: {', '.join(extra)}")

        tags = meta.get("tags", [])
        if tags and isinstance(tags, list):
            parts.append(f"Tags: {', '.join(str(t) for t in tags)}")

        composites = meta.get("composites", [])
        if composites:
            comp_descs = [c.get("designation", "") for c in composites if isinstance(c, dict) and c.get("designation")]
            if comp_descs:
                parts.append(f"Part of: {'; '.join(comp_descs)}")

        pubs = meta.get("publications", [])
        if pubs:
            pub_lines = []
            for p in pubs[:5]:
                if not isinstance(p, dict):
                    continue
                ref = p.get("designation", "")
                if p.get("exact_reference"):
                    ref += f" {p['exact_reference']}"
                if ref.strip():
                    pub_lines.append(ref.strip())
            if pub_lines:
                parts.append("References: " + "; ".join(pub_lines))

        return "\n\n".join(parts)
