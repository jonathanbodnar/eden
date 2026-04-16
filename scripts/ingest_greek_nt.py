"""Ingest the 27 books of the Greek New Testament (SBLGNT) in original Koine Greek."""
import asyncio
import hashlib
import logging

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SBLGNT_URL = "https://raw.githubusercontent.com/jtauber/gnt-texts/master/sblgnt.txt"

BOOK_MAP = {
    "01": "Matthew",
    "02": "Mark",
    "03": "Luke",
    "04": "John",
    "05": "Acts",
    "06": "Romans",
    "07": "1 Corinthians",
    "08": "2 Corinthians",
    "09": "Galatians",
    "10": "Ephesians",
    "11": "Philippians",
    "12": "Colossians",
    "13": "1 Thessalonians",
    "14": "2 Thessalonians",
    "15": "1 Timothy",
    "16": "2 Timothy",
    "17": "Titus",
    "18": "Philemon",
    "19": "Hebrews",
    "20": "James",
    "21": "1 Peter",
    "22": "2 Peter",
    "23": "1 John",
    "24": "2 John",
    "25": "3 John",
    "26": "Jude",
    "27": "Revelation",
}

TRUSTED_SOURCE_ID = "a1b2c3d4-0000-0000-0000-000000000003"  # placeholder, will look up


async def get_or_create_trusted_source(pool):
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT id FROM trusted_sources WHERE slug = 'sblgnt'"
        )
        if row:
            return row
        row = await conn.fetchval(
            "SELECT id FROM trusted_sources WHERE slug = 'sefaria'"
        )
        if row:
            return row
        row = await conn.fetchval(
            "SELECT id FROM trusted_sources ORDER BY created_at LIMIT 1"
        )
        return row


async def insert_book(pool, trusted_source_id, book_num, book_name, text):
    external_id = f"sblgnt-{book_num}-{book_name.lower().replace(' ', '-')}"
    title = f"{book_name} (Koine Greek Original - SBLGNT)"
    source_url = "https://github.com/morphgnt/sblgnt"
    checksum = hashlib.sha256(text.encode()).hexdigest()
    byte_size = len(text.encode("utf-8"))
    r2_key = f"original-texts/{external_id}.txt"

    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM raw_objects WHERE external_id = $1", external_id
        )
        if existing:
            log.info("  %s already exists, skipping", title)
            return "exists"

        async with conn.transaction():
            ro_id = await conn.fetchval("""
                INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                         content_type, checksum, byte_size, r2_key, fetched_at)
                VALUES (gen_random_uuid(), $1, $2, $3, 'text/plain', $4, $5, $6, NOW())
                ON CONFLICT (r2_key) DO NOTHING RETURNING id
            """, trusted_source_id, external_id, source_url, checksum, byte_size, r2_key)
            if not ro_id:
                log.info("  %s r2_key conflict, skipping", title)
                return "exists"

            sr_id = await conn.fetchval("""
                INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                            culture, language_family, origin_place_name,
                                            source_category, provenance_status, record_status,
                                            created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                        'verified', 'published', NOW(), NOW())
                RETURNING id
            """, ro_id, trusted_source_id, title,
                "Early Christian", "Hellenic", "Eastern Mediterranean", "text_corpus")

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, copyright_status, text_extracted,
                                             tsv,
                                             created_at, updated_at)
                VALUES (gen_random_uuid(), $1, 'original', 'Koine Greek',
                        true, 'public_domain', $2,
                        setweight(to_tsvector('english', $3), 'A') ||
                        to_tsvector('english', LEFT($2, 10000)),
                        NOW(), NOW())
            """, sr_id, text, title)

            await conn.execute("""
                UPDATE source_records SET tsv = to_tsvector('english',
                    COALESCE(canonical_title, '') || ' ' || COALESCE(culture, '') || ' ' ||
                    COALESCE(origin_place_name, '') || ' ' || COALESCE(language_family, ''))
                WHERE id = $1
            """, sr_id)

    return "inserted"


async def main():
    pool = await asyncpg.create_pool(
        host="localhost", port=5432, user="eden", password="eden", database="eden",
        min_size=1, max_size=3,
    )

    trusted_source_id = await get_or_create_trusted_source(pool)
    log.info("Using trusted_source_id: %s", trusted_source_id)

    async with httpx.AsyncClient(timeout=60) as client:
        log.info("Downloading SBLGNT text...")
        resp = await client.get(SBLGNT_URL)
        resp.raise_for_status()
        raw_text = resp.text
        log.info("Downloaded %d chars, %d lines", len(raw_text), raw_text.count("\n"))

    books: dict[str, list[str]] = {}
    for line in raw_text.strip().split("\n"):
        if not line.strip():
            continue
        book_num = line.split(".")[0]
        if book_num not in books:
            books[book_num] = []
        books[book_num].append(line)

    log.info("Parsed %d books", len(books))

    inserted = 0
    skipped = 0
    for book_num in sorted(books.keys()):
        book_name = BOOK_MAP.get(book_num, f"Book {book_num}")
        verse_lines = books[book_num]

        # Build clean text: strip verse refs, keep just Greek text
        text_lines = []
        current_chapter = None
        for vline in verse_lines:
            parts = vline.split(" ", 1)
            if len(parts) < 2:
                continue
            ref, greek = parts[0], parts[1]
            chapter = ref.split(".")[1]
            if chapter != current_chapter:
                if current_chapter is not None:
                    text_lines.append("")
                text_lines.append(f"[{book_name} {int(chapter)}]")
                current_chapter = chapter
            text_lines.append(greek)

        text = "\n".join(text_lines)
        log.info("Book %s: %s — %d verses, %d chars", book_num, book_name, len(verse_lines), len(text))

        result = await insert_book(pool, trusted_source_id, book_num, book_name, text)
        if result == "inserted":
            inserted += 1
        else:
            skipped += 1

    log.info("Done! Inserted: %d, Skipped: %d", inserted, skipped)
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
