"""Restore CDLI records from R2.

Focuses on the hardest-to-re-fetch source. Downloads from R2 in batches
and inserts into DB, handling duplicates gracefully.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys

import boto3
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
from src.ingestion.services.api_fetch import parse_api_metadata

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("EDEN_DATABASE_URL", "postgresql+asyncpg://eden:eden@postgres:5432/eden")
BUCKET = os.environ.get("EDEN_R2_BUCKET_NAME", "eden-raw")

SOURCES_TO_RESTORE = [
    "cdli", "sacred-texts", "internet-archive", "tla-egyptian",
    "suttacentral", "met-museum", "wikipedia-ancient",
    "ctext", "dss-bible", "sefaria", "unesco-whc",
    "wikidata-artifacts", "wikidata-locations", "pleiades",
    "openalex", "gutenberg", "perseus", "open-context",
    "british-museum", "wikisource", "oracc", "loc",
]


def _to_str(val, maxlen=500):
    if isinstance(val, list):
        val = ", ".join(str(v) for v in val)
    if isinstance(val, str) and len(val) > maxlen:
        return val[:maxlen]
    return val


async def restore():
    engine = create_async_engine(DB_URL, pool_size=5, max_overflow=3)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r2 = boto3.client(
        "s3",
        endpoint_url=os.environ["EDEN_R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["EDEN_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["EDEN_R2_SECRET_ACCESS_KEY"],
    )

    async with async_session() as session:
        result = await session.execute(select(TrustedSource))
        sources = {s.slug: s for s in result.scalars().all()}
        logger.info("Loaded %d trusted sources", len(sources))

    for slug in SOURCES_TO_RESTORE:
        if slug not in sources:
            logger.warning("Source %s not found, skipping", slug)
            continue

        source = sources[slug]
        logger.info("=== Restoring %s ===", slug)

        async with async_session() as session:
            existing = set()
            rows = await session.execute(
                text("SELECT external_id FROM raw_objects WHERE trusted_source_id = :sid"),
                {"sid": str(source.id)},
            )
            for row in rows:
                existing.add(row[0])
            logger.info("  %s: %d already in DB", slug, len(existing))

        r2_objects = {}
        paginator = r2.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET, Prefix=f"raw/{slug}/", MaxKeys=1000):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                parts = key.split("/")
                if len(parts) < 7:
                    continue
                eid = parts[5]
                if eid in existing:
                    continue
                if eid not in r2_objects:
                    r2_objects[eid] = {}
                r2_objects[eid][parts[-1]] = key

        to_restore = {eid: files for eid, files in r2_objects.items() if "original" in files}
        logger.info("  %s: %d to restore from R2", slug, len(to_restore))

        restored = 0
        failed = 0

        for eid, files in to_restore.items():
            async with async_session() as session:
                try:
                    original_key = files["original"]
                    meta_key = files.get("metadata.json")

                    r2_meta = {}
                    if meta_key:
                        resp = r2.get_object(Bucket=BUCKET, Key=meta_key)
                        r2_meta = json.loads(resp["Body"].read())

                    head = r2.head_object(Bucket=BUCKET, Key=original_key)
                    content_type = head.get("ContentType", "application/octet-stream")
                    byte_size = head["ContentLength"]

                    raw_data = r2.get_object(Bucket=BUCKET, Key=original_key)["Body"].read()
                    checksum = hashlib.sha256(raw_data).hexdigest()

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
                    elif slug == "sacred-texts" and "html" in content_type.lower():
                        from src.ingestion.services.api_fetch import parse_sacred_texts_html
                        parsed = parse_sacred_texts_html(raw_data.decode("utf-8", errors="replace"), eid)
                    elif slug == "dss-bible" and "html" in content_type.lower():
                        from src.ingestion.services.api_fetch import parse_dss_html
                        parsed = parse_dss_html(raw_data.decode("utf-8", errors="replace"), eid)
                    elif slug == "gutenberg" and "text" in content_type.lower():
                        from src.ingestion.services.api_fetch import parse_gutenberg_text
                        parsed = parse_gutenberg_text(raw_data.decode("utf-8", errors="replace"), eid)
                    elif slug == "wikisource" and "html" in content_type.lower():
                        from src.ingestion.services.api_fetch import parse_wikisource_html
                        parsed = parse_wikisource_html(raw_data.decode("utf-8", errors="replace"), eid)
                    else:
                        parsed = {"_raw": {}, "source_api": slug}

                    if parsed.get("_skip"):
                        continue

                    # Get or create discovered record
                    row = await session.execute(
                        text("""
                            INSERT INTO discovered_records (trusted_source_id, external_id, record_url, title_hint, status)
                            VALUES (:sid, :eid, :url, :title, 'fetched')
                            ON CONFLICT (trusted_source_id, external_id) DO UPDATE SET status = 'fetched'
                            RETURNING id
                        """),
                        {
                            "sid": str(source.id),
                            "eid": eid,
                            "url": source_url[:4096],
                            "title": _to_str(parsed.get("title", eid))[:300],
                        },
                    )
                    disc_id = row.scalar_one()

                    # Insert raw object
                    await session.execute(
                        text("""
                            INSERT INTO raw_objects (trusted_source_id, discovered_record_id, external_id, source_url, content_type, checksum, byte_size, r2_key, http_status, raw_metadata_jsonb)
                            VALUES (:sid, :did, :eid, :url, :ct, :cs, :bs, :r2, :hs, :meta)
                            ON CONFLICT (r2_key) DO NOTHING
                        """),
                        {
                            "sid": str(source.id),
                            "did": str(disc_id),
                            "eid": eid,
                            "url": source_url[:4096],
                            "ct": content_type,
                            "cs": checksum,
                            "bs": byte_size,
                            "r2": original_key,
                            "hs": http_status,
                            "meta": json.dumps(parsed, default=str),
                        },
                    )

                    # Get the raw object id
                    ro_row = await session.execute(
                        text("SELECT id FROM raw_objects WHERE r2_key = :r2"),
                        {"r2": original_key},
                    )
                    raw_obj_id = ro_row.scalar_one_or_none()
                    if not raw_obj_id:
                        await session.commit()
                        continue

                    text_content = parsed.get("text", "")
                    if not text_content and isinstance(parsed.get("translations"), list):
                        for t in parsed["translations"]:
                            if t.get("text"):
                                text_content = t["text"]
                                break

                    has_prov = any(parsed.get(k) for k in ("provenance", "repository", "excavation_site"))

                    # Insert source record
                    sr_row = await session.execute(
                        text("""
                            INSERT INTO source_records (trusted_source_id, raw_object_id, canonical_title, source_category, culture, language_family, origin_place_name, repository_institution, provenance_status, record_status, latitude, longitude, metadata_jsonb)
                            VALUES (:sid, :roid, :title, :cat, :culture, :lang, :place, :repo, :prov, 'normalized', :lat, :lon, :meta)
                            RETURNING id
                        """),
                        {
                            "sid": str(source.id),
                            "roid": str(raw_obj_id),
                            "title": _to_str(parsed.get("title", f"Record {eid}"))[:500],
                            "cat": source.source_category.value,
                            "culture": _to_str(parsed.get("culture")),
                            "lang": _to_str(parsed.get("language_family", source.default_language)),
                            "place": _to_str(parsed.get("origin_place")),
                            "repo": _to_str(parsed.get("repository")),
                            "prov": "unverified" if has_prov else "unknown",
                            "lat": parsed.get("latitude"),
                            "lon": parsed.get("longitude"),
                            "meta": json.dumps({k: v for k, v in parsed.items() if k != "_raw"}, default=str),
                        },
                    )
                    sr_id = sr_row.scalar_one()

                    # Insert source version
                    await session.execute(
                        text("""
                            INSERT INTO source_versions (source_record_id, version_type, language, copyright_status, text_extracted, is_preferred, metadata_jsonb)
                            VALUES (:srid, 'original', :lang, 'public_domain', :txt, true, '{"restored_from_r2": true}')
                        """),
                        {
                            "srid": str(sr_id),
                            "lang": _to_str(parsed.get("language_family", source.default_language)),
                            "txt": text_content[:500000] if text_content else "",
                        },
                    )

                    await session.commit()
                    restored += 1

                    if restored % 500 == 0:
                        logger.info("  %s: restored %d, failed %d", slug, restored, failed)

                except Exception as exc:
                    await session.rollback()
                    failed += 1
                    if failed <= 5 or failed % 200 == 0:
                        logger.error("  %s/%s failed: %s", slug, eid, str(exc)[:200])

        logger.info("  %s DONE: restored=%d, failed=%d", slug, restored, failed)

    logger.info("ALL SOURCES RESTORED")
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(restore())
    except Exception as exc:
        logger.exception("FATAL: %s", exc)
        sys.exit(1)
