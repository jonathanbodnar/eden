"""Restore database records from R2 raw objects.

Reads all raw/<source>/<date>/<external_id>/ objects from R2,
re-parses them through the existing parsers, and re-creates
raw_objects -> source_records -> source_versions -> segments.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion.models.base import Base
from src.ingestion.models.enums import (
    CopyrightStatus,
    DiscoveredRecordStatus,
    ProvenanceStatus,
    RecordStatus,
    VersionType,
)
from src.ingestion.models.discovered_record import DiscoveredRecord
from src.ingestion.models.raw_object import RawObject
from src.ingestion.models.source_record import SourceRecord
from src.ingestion.models.source_version import SourceVersion
from src.ingestion.models.trusted_source import TrustedSource
from src.ingestion.services.api_fetch import (
    parse_api_metadata,
    parse_dss_html,
    parse_gutenberg_text,
    parse_sacred_texts_html,
    parse_wikisource_html,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "EDEN_DATABASE_URL",
    "postgresql+asyncpg://eden:eden@postgres:5432/eden",
)
R2_ENDPOINT = os.environ["EDEN_R2_ENDPOINT_URL"]
R2_KEY = os.environ["EDEN_R2_ACCESS_KEY_ID"]
R2_SECRET = os.environ["EDEN_R2_SECRET_ACCESS_KEY"]
BUCKET = os.environ.get("EDEN_R2_BUCKET_NAME", "eden-raw")

BATCH_SIZE = 200
COMMIT_EVERY = 500

HTML_PARSERS = {
    "dss-bible": lambda data, eid: parse_dss_html(data, eid),
    "sacred-texts": lambda data, eid: parse_sacred_texts_html(data, eid),
    "gutenberg": lambda data, eid: parse_gutenberg_text(data, eid),
    "wikisource": lambda data, eid: parse_wikisource_html(data, eid),
}


def _to_str(val, maxlen=500):
    if isinstance(val, list):
        val = ", ".join(str(v) for v in val)
    if isinstance(val, str) and len(val) > maxlen:
        return val[:maxlen]
    return val


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def restore():
    engine = create_async_engine(DB_URL, pool_size=10, max_overflow=5)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r2 = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_KEY,
        aws_secret_access_key=R2_SECRET,
    )

    async with async_session() as session:
        result = await session.execute(select(TrustedSource))
        sources = {s.slug: s for s in result.scalars().all()}
        logger.info("Loaded %d trusted sources", len(sources))

        existing_r2_keys = set()
        rows = await session.execute(text("SELECT r2_key FROM raw_objects"))
        for row in rows:
            existing_r2_keys.add(row[0])
        logger.info("Found %d existing raw_objects to skip", len(existing_r2_keys))

    paginator = r2.get_paginator("list_objects_v2")
    all_objects = {}

    logger.info("Scanning R2 for raw objects...")
    for page in paginator.paginate(Bucket=BUCKET, Prefix="raw/", MaxKeys=1000):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/")
            # Structure: raw/<source>/<year>/<month>/<day>/<external_id>/<filename>
            if len(parts) < 7:
                continue
            source_slug = parts[1]
            external_id = parts[5]
            group_key = f"{source_slug}/{external_id}"

            if group_key not in all_objects:
                all_objects[group_key] = {"slug": source_slug, "eid": external_id, "files": {}}

            filename = parts[-1]
            all_objects[group_key]["files"][filename] = key

    logger.info("Found %d unique raw objects across R2", len(all_objects))

    restored = 0
    skipped = 0
    failed = 0
    commit_pending = 0

    logger.info("Starting restore of %d objects (skipping %d already in DB)...",
                len(all_objects), len(existing_r2_keys))

    async with async_session() as session:
        for idx, (group_key, info) in enumerate(all_objects.items()):
            if idx % 1000 == 0:
                logger.info("Processing %d/%d...", idx, len(all_objects))
            slug = info["slug"]
            eid = info["eid"]
            files = info["files"]

            if slug not in sources:
                skipped += 1
                continue

            source = sources[slug]
            original_key = files.get("original")
            if not original_key:
                skipped += 1
                continue

            if original_key in existing_r2_keys:
                skipped += 1
                continue

            try:
                meta_key = files.get("metadata.json")
                r2_meta = {}
                if meta_key:
                    meta_resp = r2.get_object(Bucket=BUCKET, Key=meta_key)
                    r2_meta = json.loads(meta_resp["Body"].read())

                head = r2.head_object(Bucket=BUCKET, Key=original_key)
                content_type = head.get("ContentType", "application/octet-stream")
                byte_size = head["ContentLength"]

                original_resp = r2.get_object(Bucket=BUCKET, Key=original_key)
                raw_data = original_resp["Body"].read()
                checksum = compute_checksum(raw_data)

                source_url = r2_meta.get("source_url", f"https://{source.domain}/{eid}")
                http_status = r2_meta.get("http_status", 200)

                if "json" in content_type.lower():
                    try:
                        api_json = json.loads(raw_data)
                        if isinstance(api_json, list) and len(api_json) == 1:
                            api_json = api_json[0]
                        parsed = parse_api_metadata(slug, api_json)
                    except Exception:
                        parsed = {"_raw": {}, "source_api": slug}
                elif slug in HTML_PARSERS:
                    text_data = raw_data.decode("utf-8", errors="replace")
                    parsed = HTML_PARSERS[slug](text_data, eid)
                else:
                    parsed = {"_raw": {}, "source_api": slug}

                if parsed.get("_skip"):
                    skipped += 1
                    continue

                existing_raw = await session.execute(
                    select(RawObject).where(
                        RawObject.trusted_source_id == source.id,
                        RawObject.external_id == eid,
                    )
                )
                if existing_raw.scalar_one_or_none():
                    skipped += 1
                    continue

                existing_disc = await session.execute(
                    select(DiscoveredRecord).where(
                        DiscoveredRecord.trusted_source_id == source.id,
                        DiscoveredRecord.external_id == eid,
                    )
                )
                disc = existing_disc.scalar_one_or_none()
                if not disc:
                    disc = DiscoveredRecord(
                        trusted_source_id=source.id,
                        record_url=source_url,
                        external_id=eid,
                        title_hint=_to_str(parsed.get("title", eid))[:300],
                        status=DiscoveredRecordStatus.FETCHED,
                    )
                    session.add(disc)
                    try:
                        await session.flush()
                    except Exception:
                        await session.rollback()
                        existing_disc = await session.execute(
                            select(DiscoveredRecord).where(
                                DiscoveredRecord.trusted_source_id == source.id,
                                DiscoveredRecord.external_id == eid,
                            )
                        )
                        disc = existing_disc.scalar_one_or_none()
                        if not disc:
                            failed += 1
                            continue

                raw_obj = RawObject(
                    trusted_source_id=source.id,
                    discovered_record_id=disc.id,
                    external_id=eid,
                    source_url=source_url,
                    content_type=content_type,
                    checksum=checksum,
                    byte_size=byte_size,
                    r2_key=original_key,
                    http_status=http_status,
                    raw_metadata_jsonb=parsed,
                )
                session.add(raw_obj)
                await session.flush()

                text_content = parsed.get("text", "")
                if not text_content and isinstance(parsed.get("translations"), list):
                    for t in parsed["translations"]:
                        if t.get("language") == "English" and t.get("text"):
                            text_content = t["text"]
                            break
                    if not text_content:
                        for t in parsed["translations"]:
                            if t.get("text"):
                                text_content = t["text"]
                                break

                has_provenance = any(
                    parsed.get(k) for k in ("provenance", "repository", "excavation_site")
                )

                sr = SourceRecord(
                    trusted_source_id=source.id,
                    raw_object_id=raw_obj.id,
                    canonical_title=_to_str(parsed.get("title", f"Record {eid}"))[:500],
                    source_category=source.source_category,
                    culture=_to_str(parsed.get("culture")),
                    language_family=_to_str(parsed.get("language_family", source.default_language)),
                    origin_place_name=_to_str(parsed.get("origin_place")),
                    repository_institution=_to_str(parsed.get("repository")),
                    provenance_status=(
                        ProvenanceStatus.UNVERIFIED if has_provenance else ProvenanceStatus.UNKNOWN
                    ),
                    record_status=RecordStatus.NORMALIZED,
                    latitude=parsed.get("latitude"),
                    longitude=parsed.get("longitude"),
                    metadata_jsonb={k: v for k, v in parsed.items() if k != "_raw"},
                )
                session.add(sr)
                await session.flush()

                sv = SourceVersion(
                    source_record_id=sr.id,
                    version_type=VersionType.ORIGINAL,
                    language=_to_str(parsed.get("language_family", source.default_language)),
                    copyright_status=CopyrightStatus.PUBLIC_DOMAIN,
                    text_extracted=text_content[:500000] if text_content else "",
                    is_preferred=True,
                    metadata_jsonb={"restored_from_r2": True},
                )
                session.add(sv)

                restored += 1
                commit_pending += 1

                if commit_pending >= COMMIT_EVERY:
                    await session.commit()
                    logger.info(
                        "Progress: restored=%d, skipped=%d, failed=%d",
                        restored, skipped, failed,
                    )
                    commit_pending = 0

            except Exception as exc:
                failed += 1
                await session.rollback()
                commit_pending = 0
                if failed <= 20 or failed % 500 == 0:
                    logger.error("Failed to restore %s/%s: %s", slug, eid, exc)
                continue

        if commit_pending > 0:
            await session.commit()

    logger.info(
        "RESTORE COMPLETE: restored=%d, skipped=%d, failed=%d",
        restored, skipped, failed,
    )
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(restore())
    except Exception as exc:
        logger.exception("FATAL ERROR: %s", exc)
        sys.exit(1)
