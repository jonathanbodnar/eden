#!/usr/bin/env python3
"""Ingest key Sumerian literary texts from ETCSL (Electronic Text Corpus of Sumerian Literature)."""

import asyncio
import hashlib
import html
import logging
import re

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://eden:eden@127.0.0.1:5432/eden"
EDEN_TS = "ea108065-4d71-49e2-bda6-d7d54b48b9c7"

ETCSL_TEXTS = [
    # Creation / Origin myths
    {"id": "t.1.1.1", "title": "Enki and Ninhursag", "desc": "Sumerian creation/paradise myth"},
    {"id": "t.1.1.2", "title": "Enki and Ninmah", "desc": "Creation of humankind"},
    {"id": "t.1.1.3", "title": "Enki and the World Order", "desc": "Organization of civilization"},
    {"id": "t.1.1.4", "title": "Enki's Journey to Nibru", "desc": "Enki's journey"},
    {"id": "t.1.3.1", "title": "Inana's Descent to the Nether World", "desc": "Major Inana myth"},
    {"id": "t.1.4.1", "title": "Dumuzid's Dream", "desc": "Dream of the shepherd-god"},
    {"id": "t.1.6.1", "title": "Ninurta's Exploits (Lugal-e)", "desc": "Warrior god epic"},
    {"id": "t.1.6.2", "title": "Ninurta's Return to Nibru (Angim)", "desc": "Ninurta's triumph"},
    {"id": "t.1.8.1.1", "title": "Enmerkar and the Lord of Aratta", "desc": "Epic about Uruk vs Aratta"},
    {"id": "t.1.8.1.2", "title": "Enmerkar and En-suhgir-ana", "desc": "Epic about Enmerkar"},
    {"id": "t.1.8.1.3", "title": "Lugalbanda in the Mountain Cave", "desc": "Lugalbanda epic pt 1"},
    {"id": "t.1.8.1.4", "title": "Lugalbanda and the Anzud Bird", "desc": "Lugalbanda epic pt 2"},
    {"id": "t.1.8.1.5", "title": "Gilgamesh and Aga", "desc": "Sumerian Gilgamesh story"},
    {"id": "t.1.8.1.5.1", "title": "Gilgamesh and Huwawa (Version A)", "desc": "Gilgamesh forest journey"},
    {"id": "t.1.8.1.5.2", "title": "Gilgamesh and Huwawa (Version B)", "desc": "Alternate version"},
    {"id": "t.1.8.2.1", "title": "Gilgamesh, Enkidu and the Nether World", "desc": "Sumerian underworld text"},
    {"id": "t.1.8.2.2", "title": "The Death of Gilgamesh", "desc": "Death of Gilgamesh"},
    # Flood narrative
    {"id": "t.1.7.4", "title": "The Flood Story (Eridu Genesis)", "desc": "Sumerian flood narrative"},
    # Debates and wisdom
    {"id": "t.5.3.2", "title": "The Debate between Bird and Fish", "desc": "Sumerian wisdom debate"},
    {"id": "t.5.3.3", "title": "The Debate between Winter and Summer", "desc": "Seasonal debate"},
    {"id": "t.5.3.5", "title": "The Debate between Sheep and Grain", "desc": "Origin of agriculture"},
    {"id": "t.5.6.1", "title": "The Instructions of Shuruppag", "desc": "Oldest known wisdom text"},
    {"id": "t.5.6.7", "title": "The Farmer's Instructions", "desc": "Agricultural instructions"},
    # Laments
    {"id": "t.2.2.2", "title": "The Lament for Urim", "desc": "Lament for the fall of Ur III"},
    {"id": "t.2.2.3", "title": "The Lament for Sumer and Urim", "desc": "Combined lament"},
    {"id": "t.2.2.4", "title": "The Lament for Nibru", "desc": "Lament for Nippur"},
    {"id": "t.2.2.5", "title": "The Lament for Eridu", "desc": "Lament for Eridu"},
    # Royal hymns
    {"id": "t.2.4.2.01", "title": "Shulgi A", "desc": "Self-praise of King Shulgi"},
    {"id": "t.2.4.2.02", "title": "Shulgi B", "desc": "Shulgi's accomplishments"},
    # Divine hymns
    {"id": "t.4.07.2", "title": "Inana and Ebih", "desc": "Inana conquering a mountain"},
    {"id": "t.4.07.3", "title": "The Exaltation of Inana (Nin-me-šara)", "desc": "Enheduanna's hymn to Inana"},
    {"id": "t.4.08.09", "title": "A Hymn to Nanna", "desc": "Moon god hymn"},
    {"id": "t.4.13.01", "title": "Enlil A", "desc": "Hymn to Enlil"},
]


async def insert_text(pool, *, external_id, title, source_url, text):
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
            """, EDEN_TS, external_id, source_url, checksum, byte_size, r2_key)
            if not ro_id:
                return "exists"

            sr_id = await conn.fetchval("""
                INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                            culture, language_family, origin_place_name,
                                            source_category, provenance_status, record_status,
                                            created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, 'Sumerian', 'Sumerian',
                        'Mesopotamia', 'text_corpus', 'verified', 'published', NOW(), NOW())
                RETURNING id
            """, ro_id, EDEN_TS, title)

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, copyright_status, text_extracted,
                                             created_at, updated_at)
                VALUES (gen_random_uuid(), $1, 'translation', 'English (scholarly translation from Sumerian)',
                        true, 'public_domain', $2, NOW(), NOW())
            """, sr_id, text)
    return "inserted"


def extract_etcsl_text(html_text: str) -> str:
    body = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.IGNORECASE)
    if not body:
        return ""
    b = body.group(1)
    b = re.sub(r"<script[^>]*>.*?</script>", "", b, flags=re.DOTALL)
    b = re.sub(r"<style[^>]*>.*?</style>", "", b, flags=re.DOTALL)
    # Keep paragraph breaks
    b = re.sub(r"</p>", "\n\n", b, flags=re.IGNORECASE)
    b = re.sub(r"<br\s*/?>", "\n", b, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", "", b)
    clean = html.unescape(clean)
    # Remove navigation/header content
    lines = clean.split("\n")
    text_lines = []
    started = False
    for line in lines:
        line = line.strip()
        if not line:
            if started:
                text_lines.append("")
            continue
        # Detect the start of actual text (numbered lines)
        if re.match(r"^\d+-?\d*\.", line) or started:
            started = True
            text_lines.append(line)
    return "\n".join(text_lines).strip()


async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3,
                                     command_timeout=300,
                                     server_settings={"statement_timeout": "300000"})
    total = 0

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) EdenResearch/1.0"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for spec in ETCSL_TEXTS:
            text_id = spec["id"]
            url = f"https://etcsl.orinst.ox.ac.uk/cgi-bin/etcsl.cgi?text={text_id}&display=Crit&charenc=gcirc"
            log.info("Fetching: %s (%s)", spec["title"], text_id)

            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    log.warning("  HTTP %d for %s", resp.status_code, text_id)
                    continue

                text = extract_etcsl_text(resp.text)
                if not text or len(text) < 100:
                    log.warning("  Too short for %s (%d chars)", spec["title"], len(text) if text else 0)
                    continue

                ext_id = f"etcsl-{text_id.replace('.', '-')}"
                full_title = f"{spec['title']} - {spec['desc']} (ETCSL Sumerian Literary Text)"
                r = await insert_text(
                    pool, external_id=ext_id, title=full_title,
                    source_url=url, text=text)
                log.info("  %s: %s (%d chars)", spec["title"], r, len(text))
                total += 1 if r == "inserted" else 0
            except Exception as e:
                log.error("  Error for %s: %s", spec["title"], e)

            await asyncio.sleep(0.5)

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

    log.info("ETCSL TOTAL: %d new records", total)
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
