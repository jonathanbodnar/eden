#!/usr/bin/env python3
"""Ingest Latin texts from The Latin Library: Augustine, Tertullian, Irenaeus."""

import asyncio
import hashlib
import logging
import re

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://eden:eden@127.0.0.1:5432/eden"
PERSEUS_TS = "c754d415-b1ee-4337-8622-28f875fa1163"


async def insert_text(pool, *, external_id, title, culture, language, source_url, text,
                      version_type="original", source_category="text_corpus",
                      language_family="Indo-European", origin_place=None):
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM raw_objects WHERE external_id = $1", external_id)
        if existing:
            return "exists"

        checksum = hashlib.sha256(text.encode()).hexdigest()
        byte_size = len(text.encode("utf-8"))
        r2_key = f"original-texts/{external_id}.txt"

        async with conn.transaction():
            ro_id = await conn.fetchval("""
                INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                         content_type, checksum, byte_size, r2_key, fetched_at)
                VALUES (gen_random_uuid(), $1, $2, $3, 'text/plain', $4, $5, $6, NOW())
                ON CONFLICT (r2_key) DO NOTHING RETURNING id
            """, PERSEUS_TS, external_id, source_url, checksum, byte_size, r2_key)
            if not ro_id:
                return "exists"

            sr_id = await conn.fetchval("""
                INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                            culture, language_family, origin_place_name,
                                            source_category, provenance_status, record_status,
                                            created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                        'verified', 'published', NOW(), NOW())
                RETURNING id
            """, ro_id, PERSEUS_TS, title, culture, language_family, origin_place, source_category)

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, copyright_status, text_extracted,
                                             created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, true, 'public_domain', $4, NOW(), NOW())
            """, sr_id, version_type, language, text)
    return "inserted"


def extract_body(html_text: str) -> str:
    body = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.IGNORECASE)
    if not body:
        return ""
    b = body.group(1)
    b = re.sub(r"<script[^>]*>.*?</script>", "", b, flags=re.DOTALL)
    b = re.sub(r"<style[^>]*>.*?</style>", "", b, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", "", b).strip()


async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3,
                                     command_timeout=300,
                                     server_settings={"statement_timeout": "300000"})
    total = 0

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) EdenResearch/1.0"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        # Augustine - De Civitate Dei (22 books)
        log.info("=== Augustine - De Civitate Dei ===")
        parts = []
        for book in range(1, 23):
            url = f"https://www.thelatinlibrary.com/augustine/civ{book}.shtml"
            resp = await client.get(url)
            if resp.status_code == 200:
                clean = extract_body(resp.text)
                if len(clean) > 100:
                    parts.append(f"=== Liber {book} ===\n{clean}")
                    log.info("  Book %d: %d chars", book, len(clean))
            await asyncio.sleep(0.3)

        if parts:
            full = "\n\n".join(parts)
            r = await insert_text(
                pool, external_id="latin-library-augustine-civitate-dei",
                title="Augustine - De Civitate Dei (City of God, Latin Original)",
                culture="Early Christian/Roman", language="Latin",
                source_url="https://www.thelatinlibrary.com/augustine.html",
                text=full, origin_place="Hippo Regius")
            log.info("  Augustine: %s (%d chars)", r, len(full))
            total += 1 if r == "inserted" else 0

        # Tertullian - Apologeticus
        log.info("=== Tertullian - Apologeticus ===")
        resp = await client.get("https://www.thelatinlibrary.com/tertullian/tertullian.apol.shtml")
        if resp.status_code == 200:
            clean = extract_body(resp.text)
            if len(clean) > 500:
                r = await insert_text(
                    pool, external_id="latin-library-tertullian-apologeticus",
                    title="Tertullian - Apologeticus (Latin Original)",
                    culture="Early Christian/Roman", language="Latin",
                    source_url="https://www.thelatinlibrary.com/tertullian/tertullian.apol.shtml",
                    text=clean, origin_place="Carthage")
                log.info("  Tertullian: %s (%d chars)", r, len(clean))
                total += 1 if r == "inserted" else 0

        # Irenaeus - Adversus Haereses (Latin)
        log.info("=== Irenaeus - Adversus Haereses ===")
        parts = []
        for book in range(1, 6):
            url = f"https://www.thelatinlibrary.com/irenaeus{book}.html"
            resp = await client.get(url)
            if resp.status_code == 200:
                clean = extract_body(resp.text)
                if len(clean) > 100:
                    parts.append(f"=== Liber {book} ===\n{clean}")
                    log.info("  Book %d: %d chars", book, len(clean))
            await asyncio.sleep(0.3)

        if parts:
            full = "\n\n".join(parts)
            r = await insert_text(
                pool, external_id="latin-library-irenaeus-adversus-haereses",
                title="Irenaeus - Adversus Haereses (Against Heresies, Latin Original)",
                culture="Early Christian", language="Latin",
                source_url="https://www.thelatinlibrary.com/irenaeus.html",
                text=full, origin_place="Lyon")
            log.info("  Irenaeus: %s (%d chars)", r, len(full))
            total += 1 if r == "inserted" else 0

    # TSV
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE source_records SET tsv = to_tsvector('english',
                COALESCE(canonical_title, '') || ' ' || COALESCE(culture, '') || ' ' ||
                COALESCE(origin_place_name, '') || ' ' || COALESCE(language_family, ''))
            WHERE tsv IS NULL
        """)
        await conn.execute("""
            UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
            WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL
        """)

    log.info("TOTAL: %d new records", total)
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
