#!/usr/bin/env python3
"""Ingest remaining missing texts: Pistis Sophia, Book of Jasher, Secret Teachings, Augustine."""

import asyncio
import hashlib
import json
import logging
import re

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://eden:eden@127.0.0.1:5432/eden"
GUTENBERG_TS = "e92b6a5b-8a20-4b39-a808-f8982cf0f62d"
SACRED_TS = "e74de463-456d-42e4-9b0a-001d908b30cc"
PERSEUS_TS = "c754d415-b1ee-4337-8622-28f875fa1163"


async def insert_text(pool, *, external_id, trusted_source_id, title, culture, language,
                      source_url, text, version_type="translation",
                      source_category="public_domain_library",
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
            """, trusted_source_id, external_id, source_url, checksum, byte_size, r2_key)
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
            """, ro_id, trusted_source_id, title, culture, language_family, origin_place,
               source_category)

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, copyright_status, text_extracted,
                                             created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, true, 'public_domain', $4, NOW(), NOW())
            """, sr_id, version_type, language, text)
    return "inserted"


def clean_gutenberg(text: str) -> str:
    for marker in ["*** START OF", "***START OF"]:
        idx = text.find(marker)
        if idx != -1:
            nl = text.find("\n", idx)
            if nl != -1:
                text = text[nl + 1:]
            break
    for marker in ["*** END OF", "***END OF"]:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
            break
    return text.strip()


async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3,
                                     command_timeout=300,
                                     server_settings={"statement_timeout": "300000"})
    total = 0

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        # 1. Pistis Sophia from Gutenberg
        log.info("Fetching Pistis Sophia from Gutenberg...")
        resp = await client.get("https://www.gutenberg.org/cache/epub/76266/pg76266.txt")
        if resp.status_code == 200:
            text = clean_gutenberg(resp.text)
            r = await insert_text(
                pool, external_id="gutenberg-pistis-sophia-76266",
                trusted_source_id=GUTENBERG_TS,
                title="Pistis Sophia (Horner & Legge Translation, 1924)",
                culture="Gnostic/Early Christian",
                language="English (translation from Coptic)",
                source_url="https://www.gutenberg.org/ebooks/76266",
                text=text)
            log.info("  Pistis Sophia: %s (%d chars)", r, len(text))
            total += 1 if r == "inserted" else 0

        # 2. Book of Jasher - try multiple sources
        log.info("Fetching Book of Jasher...")
        jasher_urls = [
            "https://www.holybooks.com/wp-content/uploads/Book-of-Jasher.pdf",
            "https://www.gutenberg.org/cache/epub/2501/pg2501.txt",
        ]
        # Try the Gutenberg mirror for related texts
        # Jasher doesn't have a standard Gutenberg entry, so try the plain text version
        resp = await client.get("https://raw.githubusercontent.com/LafeLabs/bookOfJasher/main/bookOfJasher.txt")
        if resp.status_code == 200 and len(resp.text) > 5000:
            text = resp.text.strip()
            r = await insert_text(
                pool, external_id="github-book-of-jasher",
                trusted_source_id=SACRED_TS,
                title="Book of Jasher (Sefer HaYashar, 1840 Translation from Hebrew)",
                culture="Jewish",
                language="English (1840 translation from Hebrew)",
                source_url="https://github.com/LafeLabs/bookOfJasher",
                text=text)
            log.info("  Book of Jasher: %s (%d chars)", r, len(text))
            total += 1 if r == "inserted" else 0
        else:
            log.warning("  Book of Jasher not available from GitHub, trying Sefaria...")
            # Try Sefaria's API with different ref formats
            for ref in ["Sefer HaYashar, Chapter 1", "Sefer_HaYashar,_Chapter_1"]:
                resp2 = await client.get(f"https://www.sefaria.org/api/texts/{ref}?context=0")
                if resp2.status_code == 200:
                    data = resp2.json()
                    if data.get("he"):
                        log.info("  Found Jasher on Sefaria: %s", ref)
                        break

        # 3. Manly P. Hall - Secret Teachings of All Ages (1928, public domain post-2023)
        log.info("Fetching Secret Teachings of All Ages...")
        # This entered public domain in 2024 (1928 + 95 years). Try Internet Archive.
        resp = await client.get(
            "https://archive.org/download/manaborium_hall_secret_teachings/The_Secret_Teachings_of_All_Ages.txt")
        if resp.status_code == 200 and len(resp.text) > 5000:
            text = resp.text.strip()
            r = await insert_text(
                pool, external_id="archive-secret-teachings",
                trusted_source_id=SACRED_TS,
                title="Manly P. Hall - The Secret Teachings of All Ages (1928)",
                culture="Esoteric/Western",
                language="English",
                source_url="https://archive.org/details/manaborium_hall_secret_teachings",
                text=text)
            log.info("  Secret Teachings: %s (%d chars)", r, len(text))
            total += 1 if r == "inserted" else 0
        else:
            log.warning("  Secret Teachings not available at expected URL (%d)", resp.status_code)

        # 4. Augustine - City of God (Latin) from different source
        log.info("Fetching Augustine - City of God (Latin)...")
        # Try The Latin Library
        all_parts = []
        for book_num in range(1, 23):
            url = f"https://www.thelatinlibrary.com/augustine/civ{book_num}.shtml"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    body_match = re.search(r"<body[^>]*>(.*?)</body>", resp.text, re.DOTALL | re.IGNORECASE)
                    if body_match:
                        body = body_match.group(1)
                        body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL)
                        body = re.sub(r"<[^>]+>", "", body)
                        clean = body.strip()
                        if len(clean) > 100:
                            all_parts.append(f"=== Liber {book_num} ===\n{clean}")
            except Exception as e:
                log.warning("  Error fetching Augustine book %d: %s", book_num, e)
            await asyncio.sleep(0.3)

        if all_parts:
            full = "\n\n".join(all_parts)
            r = await insert_text(
                pool, external_id="latin-library-augustine-civitate-dei",
                trusted_source_id=PERSEUS_TS,
                title="Augustine - De Civitate Dei (City of God) (Latin Original)",
                culture="Early Christian/Roman",
                language="Latin",
                source_url="https://www.thelatinlibrary.com/augustine.html",
                text=full,
                version_type="original",
                source_category="text_corpus",
                language_family="Indo-European",
                origin_place="Hippo Regius")
            log.info("  Augustine City of God: %s (%d chars)", r, len(full))
            total += 1 if r == "inserted" else 0

        # 5. Tertullian - Apologeticus (Latin)
        log.info("Fetching Tertullian - Apologeticus...")
        resp = await client.get("https://www.thelatinlibrary.com/tertullian/tertullian.apol.shtml")
        if resp.status_code == 200:
            body_match = re.search(r"<body[^>]*>(.*?)</body>", resp.text, re.DOTALL | re.IGNORECASE)
            if body_match:
                body = body_match.group(1)
                body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL)
                clean = re.sub(r"<[^>]+>", "", body).strip()
                if len(clean) > 500:
                    r = await insert_text(
                        pool, external_id="latin-library-tertullian-apologeticus",
                        trusted_source_id=PERSEUS_TS,
                        title="Tertullian - Apologeticus (Latin Original)",
                        culture="Early Christian/Roman",
                        language="Latin",
                        source_url="https://www.thelatinlibrary.com/tertullian/tertullian.apol.shtml",
                        text=clean,
                        version_type="original",
                        source_category="text_corpus",
                        language_family="Indo-European",
                        origin_place="Carthage")
                    log.info("  Tertullian Apologeticus: %s (%d chars)", r, len(clean))
                    total += 1 if r == "inserted" else 0

    # Update TSV
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
