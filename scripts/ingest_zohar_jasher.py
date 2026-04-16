#!/usr/bin/env python3
"""Ingest Zohar (Aramaic) and Sefer HaYashar from Sefaria using the correct API references."""

import asyncio
import hashlib
import html
import json
import logging
import re
from urllib.parse import quote

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://eden:eden@127.0.0.1:5432/eden"
SEFARIA_TS = "41132a8a-df91-4c56-90af-28fe45cb6119"
RATE_LIMIT = 0.4


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def flatten_text(data) -> str:
    if isinstance(data, str):
        return strip_html(data)
    if isinstance(data, list):
        parts = [flatten_text(item) for item in data]
        return "\n".join(p for p in parts if p)
    return ""


async def fetch_he(client, ref):
    url = f"https://www.sefaria.org/api/texts/{quote(ref, safe=',.')}?context=0"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            return flatten_text(resp.json().get("he", []))
        elif resp.status_code == 429:
            log.warning("Rate limited, sleeping 10s")
            await asyncio.sleep(10)
            return await fetch_he(client, ref)
        else:
            return None
    except Exception as e:
        log.warning("Error fetching %s: %s", ref, e)
        return None


async def insert_text(pool, *, external_id, title, culture, language, source_url, text,
                      version_type="original", source_category="text_corpus",
                      language_family=None, origin_place=None):
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
            """, SEFARIA_TS, external_id, source_url, checksum, byte_size, r2_key)
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
            """, ro_id, SEFARIA_TS, title, culture, language_family, origin_place, source_category)

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, copyright_status, text_extracted,
                                             created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, true, 'public_domain', $4, NOW(), NOW())
            """, sr_id, version_type, language, text)

    return "inserted"


ZOHAR_SECTIONS = [
    "Introduction", "Bereshit", "Noach", "Lech Lecha", "Vayera", "Chayei Sara",
    "Toldot", "Vayetzei", "Vayishlach", "Vayeshev", "Miketz", "Vayigash",
    "Vayechi", "Shemot", "Vaera", "Bo", "Beshalach", "Yitro", "Mishpatim",
    "Terumah", "Sifra DiTzniuta", "Tetzaveh", "Ki Tisa", "Vayakhel", "Pekudei",
    "Vayikra", "Tzav", "Shmini", "Tazria", "Metzora", "Achrei Mot", "Kedoshim",
    "Emor", "Behar", "Bechukotai", "Bamidbar", "Nasso", "Idra Rabba",
    "Beha'alotcha", "Sh'lach", "Korach", "Chukat", "Balak", "Pinchas",
    "Matot", "Vaetchanan", "Eikev", "Shoftim", "Ki Teitzei", "Vayeilech",
    "Ha'Azinu", "Idra Zuta",
]


async def ingest_zohar(pool, client):
    log.info("=== Ingesting Zohar (Aramaic original) ===")
    total = 0

    for section in ZOHAR_SECTIONS:
        all_parts = []
        consecutive_fails = 0
        for ch in range(1, 200):
            ref = f"Zohar, {section}.{ch}"
            he = await fetch_he(client, ref)
            if he and len(he) > 10:
                all_parts.append(f"=== Zohar {section} Ch {ch} ===\n{he}")
                consecutive_fails = 0
            else:
                consecutive_fails += 1
                if consecutive_fails > 2 and ch > 3:
                    break
            await asyncio.sleep(RATE_LIMIT)

        if not all_parts:
            log.info("  Zohar %s: no text found", section)
            continue

        full_text = "\n\n".join(all_parts)
        safe_section = section.replace(" ", "_").replace("'", "")
        ext_id = f"sefaria-he-zohar-{safe_section}"
        result = await insert_text(
            pool,
            external_id=ext_id,
            title=f"Zohar - {section} (Aramaic Original)",
            culture="Jewish/Kabbalistic",
            language="Aramaic",
            source_url=f"https://www.sefaria.org/Zohar,_{quote(section)}",
            text=full_text,
            language_family="Semitic",
        )
        log.info("  Zohar %s: %s (%d chars)", section, result, len(full_text))
        total += 1 if result == "inserted" else 0

    return total


async def ingest_sefer_hayashar(pool, client):
    """Try different Sefaria reference formats for Sefer HaYashar."""
    log.info("=== Ingesting Sefer HaYashar ===")
    refs_to_try = [
        "Sefer HaYashar", "Sefer_HaYashar", "Sefer HaYashar (midrash)",
        "Sefer HaYashar, Chapter 1",
    ]

    # Try the index API to find the correct ref
    resp = await client.get("https://www.sefaria.org/api/v2/index/Sefer_HaYashar_(midrash)")
    if resp.status_code == 200:
        idx = resp.json()
        log.info("Found index for Sefer HaYashar: %s", idx.get("title"))

    for ref_try in refs_to_try:
        he = await fetch_he(client, ref_try + ".1")
        if he and len(he) > 20:
            log.info("  Found working ref: %s", ref_try)
            all_parts = []
            for ch in range(1, 100):
                he = await fetch_he(client, f"{ref_try}.{ch}")
                if he and len(he) > 10:
                    all_parts.append(f"=== Chapter {ch} ===\n{he}")
                elif ch > 5:
                    break
                await asyncio.sleep(RATE_LIMIT)

            if all_parts:
                full = "\n\n".join(all_parts)
                result = await insert_text(
                    pool,
                    external_id="sefaria-he-sefer-hayashar",
                    title="Sefer HaYashar (Book of Jasher) (Hebrew Original)",
                    culture="Jewish/Medieval",
                    language="Hebrew",
                    source_url=f"https://www.sefaria.org/{quote(ref_try)}",
                    text=full,
                    language_family="Semitic",
                )
                log.info("  Sefer HaYashar: %s (%d chars)", result, len(full))
                return 1 if result == "inserted" else 0

        await asyncio.sleep(RATE_LIMIT)

    log.warning("  Sefer HaYashar not found on Sefaria with any reference format")
    return 0


async def ingest_targum_full(pool, client):
    """Ingest Targum Onkelos with full chapter-by-chapter fetching."""
    log.info("=== Ingesting Targum Onkelos (full, chapter by chapter) ===")
    total = 0
    torah_books = {
        "Genesis": 50, "Exodus": 40, "Leviticus": 27,
        "Numbers": 36, "Deuteronomy": 34,
    }

    for book, chapters in torah_books.items():
        all_parts = []
        for ch in range(1, chapters + 1):
            ref = f"Onkelos {book}.{ch}"
            he = await fetch_he(client, ref)
            if he and len(he) > 10:
                all_parts.append(f"=== Targum Onkelos {book} Ch {ch} ===\n{he}")
            await asyncio.sleep(RATE_LIMIT)

        if not all_parts:
            log.info("  Onkelos %s: no text", book)
            continue

        full = "\n\n".join(all_parts)
        ext_id = f"sefaria-he-onkelos-full-{book.lower()}"
        result = await insert_text(
            pool,
            external_id=ext_id,
            title=f"Targum Onkelos - {book} (Full Aramaic Text)",
            culture="Jewish/Aramaic",
            language="Aramaic",
            source_url=f"https://www.sefaria.org/Onkelos_{book}",
            text=full,
            version_type="translation",
            language_family="Semitic",
            origin_place="Babylon",
        )
        log.info("  Onkelos %s: %s (%d chars)", book, result, len(full))
        total += 1 if result == "inserted" else 0

    return total


async def update_tsv(pool):
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
        log.info("TSV columns updated")


async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3,
                                     command_timeout=300,
                                     server_settings={"statement_timeout": "300000"})
    try:
        total = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            total += await ingest_zohar(pool, client)
            total += await ingest_sefer_hayashar(pool, client)
            total += await ingest_targum_full(pool, client)

        await update_tsv(pool)
        log.info("TOTAL new records: %d", total)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
