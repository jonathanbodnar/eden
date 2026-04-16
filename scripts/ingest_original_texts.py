#!/usr/bin/env python3
"""Ingest original-language ancient texts from Sefaria, Perseus, sacred-texts.com, and ETCSL."""

import asyncio
import hashlib
import html
import json
import logging
import re
import sys
import time
from urllib.parse import quote

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://eden:eden@127.0.0.1:5432/eden"

# Trusted source IDs from DB
SEFARIA_TS = "41132a8a-df91-4c56-90af-28fe45cb6119"
PERSEUS_TS = "c754d415-b1ee-4337-8622-28f875fa1163"
SACRED_TEXTS_TS = "e74de463-456d-42e4-9b0a-001d908b30cc"
EDEN_RESEARCH_TS = "ea108065-4d71-49e2-bda6-d7d54b48b9c7"
GUTENBERG_TS = "e92b6a5b-8a20-4b39-a808-f8982cf0f62d"

MAX_RETRIES = 3
RATE_LIMIT_DELAY = 0.5  # seconds between API calls


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def flatten_text(data) -> str:
    """Recursively flatten nested lists/strings from Sefaria JSON into text."""
    if isinstance(data, str):
        return strip_html(data)
    if isinstance(data, list):
        parts = []
        for item in data:
            t = flatten_text(item)
            if t:
                parts.append(t)
        return "\n".join(parts)
    return ""


async def db_op(pool, func):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with pool.acquire() as conn:
                return await func(conn)
        except Exception as e:
            log.warning("DB error (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(2 ** attempt)


async def insert_text(pool, *, external_id, trusted_source_id, title, culture, language,
                      source_url, text, version_type="original", source_category="text_corpus",
                      language_family=None, origin_place=None, metadata_json=None):
    """Insert a complete raw_object + source_record + source_version chain."""
    async def _do(conn):
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
                ON CONFLICT (r2_key) DO NOTHING
                RETURNING id
            """, trusted_source_id, external_id, source_url, checksum, byte_size, r2_key)

            if not ro_id:
                return "exists"

            meta = json.dumps(metadata_json) if metadata_json else None
            sr_id = await conn.fetchval("""
                INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                            culture, language_family, origin_place_name,
                                            source_category, provenance_status, record_status,
                                            metadata_jsonb, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                        'verified', 'published', $8::jsonb, NOW(), NOW())
                RETURNING id
            """, ro_id, trusted_source_id, title, culture, language_family, origin_place,
               source_category, meta)

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, copyright_status, text_extracted,
                                             created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, true, 'public_domain', $4, NOW(), NOW())
            """, sr_id, version_type, language, text)

        return "inserted"

    return await db_op(pool, _do)


# ============================================================
# SEFARIA INGESTION
# ============================================================

SEFARIA_BOOKS = {
    # Tanakh - Torah
    "Genesis": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Exodus": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Leviticus": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Numbers": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Deuteronomy": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    # Tanakh - Prophets (Nevi'im)
    "Joshua": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Judges": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "I_Samuel": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "II_Samuel": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "I_Kings": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "II_Kings": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Isaiah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Jeremiah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Ezekiel": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Hosea": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Joel": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Amos": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Obadiah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Jonah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Micah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Nahum": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Habakkuk": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Zephaniah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Haggai": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Zechariah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Malachi": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    # Tanakh - Writings (Ketuvim)
    "Psalms": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Proverbs": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Job": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Song_of_Songs": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Ruth": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Lamentations": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Ecclesiastes": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Esther": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel/Persia"},
    "Daniel": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Babylon"},
    "Ezra": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "Nehemiah": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "I_Chronicles": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
    "II_Chronicles": {"culture": "Ancient Israelite", "lang_family": "Semitic", "place": "Ancient Israel"},
}

# Sefaria API uses spaces, not underscores for some book names
SEFARIA_API_NAMES = {
    "I_Samuel": "I Samuel",
    "II_Samuel": "II Samuel",
    "I_Kings": "I Kings",
    "II_Kings": "II Kings",
    "I_Chronicles": "I Chronicles",
    "II_Chronicles": "II Chronicles",
    "Song_of_Songs": "Song of Songs",
}

SEFARIA_EXTRA_TEXTS = [
    # Targumim
    {"ref": "Onkelos_Genesis", "title": "Targum Onkelos - Genesis", "culture": "Jewish/Aramaic", "lang": "Aramaic", "lang_family": "Semitic", "place": "Babylon"},
    {"ref": "Onkelos_Exodus", "title": "Targum Onkelos - Exodus", "culture": "Jewish/Aramaic", "lang": "Aramaic", "lang_family": "Semitic", "place": "Babylon"},
    {"ref": "Onkelos_Leviticus", "title": "Targum Onkelos - Leviticus", "culture": "Jewish/Aramaic", "lang": "Aramaic", "lang_family": "Semitic", "place": "Babylon"},
    {"ref": "Onkelos_Numbers", "title": "Targum Onkelos - Numbers", "culture": "Jewish/Aramaic", "lang": "Aramaic", "lang_family": "Semitic", "place": "Babylon"},
    {"ref": "Onkelos_Deuteronomy", "title": "Targum Onkelos - Deuteronomy", "culture": "Jewish/Aramaic", "lang": "Aramaic", "lang_family": "Semitic", "place": "Babylon"},
    # Midrash
    {"ref": "Bereishit_Rabbah", "title": "Bereishit Rabbah (Genesis Rabbah)", "culture": "Jewish/Rabbinic", "lang": "Hebrew", "lang_family": "Semitic", "place": "Land of Israel"},
    {"ref": "Shemot_Rabbah", "title": "Shemot Rabbah (Exodus Rabbah)", "culture": "Jewish/Rabbinic", "lang": "Hebrew", "lang_family": "Semitic", "place": "Land of Israel"},
    {"ref": "Pirkei_DeRabbi_Eliezer", "title": "Pirkei de-Rabbi Eliezer", "culture": "Jewish/Rabbinic", "lang": "Hebrew", "lang_family": "Semitic", "place": "Land of Israel"},
    # Jasher
    {"ref": "Sefer_HaYashar_(midrash)", "title": "Sefer HaYashar (Book of Jasher)", "culture": "Jewish/Medieval", "lang": "Hebrew", "lang_family": "Semitic", "place": "Unknown"},
    # Mishnah (core tractates)
    {"ref": "Mishnah_Sanhedrin", "title": "Mishnah Sanhedrin", "culture": "Jewish/Rabbinic", "lang": "Hebrew", "lang_family": "Semitic", "place": "Land of Israel"},
    {"ref": "Mishnah_Avot", "title": "Mishnah Avot (Ethics of the Fathers)", "culture": "Jewish/Rabbinic", "lang": "Hebrew", "lang_family": "Semitic", "place": "Land of Israel"},
    {"ref": "Mishnah_Berakhot", "title": "Mishnah Berakhot", "culture": "Jewish/Rabbinic", "lang": "Hebrew", "lang_family": "Semitic", "place": "Land of Israel"},
]

# Key Talmud tractates (the full Talmud is thousands of pages, so take the most relevant)
TALMUD_TRACTATES = [
    "Berakhot", "Shabbat", "Pesachim", "Yoma", "Sukkah", "Rosh_Hashanah",
    "Megillah", "Chagigah", "Sanhedrin", "Makkot", "Avodah_Zarah",
    "Bava_Kamma", "Bava_Metzia", "Bava_Batra", "Niddah",
]

ZOHAR_SECTIONS = [
    "Zohar.1", "Zohar.2", "Zohar.3",
]

# Jerusalem Talmud key tractates
YERUSHALMI_TRACTATES = [
    "Jerusalem_Talmud_Berakhot", "Jerusalem_Talmud_Sanhedrin",
    "Jerusalem_Talmud_Shabbat", "Jerusalem_Talmud_Pesachim",
]


async def fetch_sefaria_text(client: httpx.AsyncClient, ref: str) -> tuple[str, str] | None:
    """Fetch Hebrew text from Sefaria API. Returns (hebrew_text, english_text) or None."""
    url = f"https://www.sefaria.org/api/texts/{quote(ref)}?context=0"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            he_text = flatten_text(data.get("he", []))
            return he_text
        elif resp.status_code == 429:
            log.warning("Rate limited on %s, sleeping 10s", ref)
            await asyncio.sleep(10)
            return await fetch_sefaria_text(client, ref)
        else:
            log.warning("Sefaria %s returned %d", ref, resp.status_code)
            return None
    except Exception as e:
        log.error("Error fetching %s: %s", ref, e)
        return None


async def get_chapter_count(client: httpx.AsyncClient, book: str) -> int:
    """Get the number of chapters in a Sefaria book."""
    url = f"https://www.sefaria.org/api/texts/{quote(book)}.1?context=0"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if "lengths" in data and data["lengths"]:
                return data["lengths"][0]
            # Try index API
        resp2 = await client.get(f"https://www.sefaria.org/api/v2/index/{quote(book)}")
        if resp2.status_code == 200:
            idx = resp2.json()
            if "schema" in idx and "lengths" in idx["schema"]:
                return idx["schema"]["lengths"][0]
    except Exception:
        pass
    return 50  # fallback estimate


async def ingest_sefaria_book(pool, client, book_key: str, info: dict):
    """Ingest an entire book from Sefaria, chapter by chapter."""
    api_name = SEFARIA_API_NAMES.get(book_key, book_key)
    display_name = api_name.replace("_", " ")

    num_chapters = await get_chapter_count(client, api_name)
    log.info("Ingesting %s (%d chapters) from Sefaria", display_name, num_chapters)

    all_text_parts = []
    for ch in range(1, num_chapters + 1):
        ref = f"{api_name}.{ch}"
        he = await fetch_sefaria_text(client, ref)
        if he:
            all_text_parts.append(f"=== {display_name} Chapter {ch} ===\n{he}")
        await asyncio.sleep(RATE_LIMIT_DELAY)

    if not all_text_parts:
        log.warning("No text retrieved for %s", display_name)
        return 0

    full_text = "\n\n".join(all_text_parts)
    if len(full_text) < 100:
        log.warning("Too little text for %s (%d chars)", display_name, len(full_text))
        return 0

    result = await insert_text(
        pool,
        external_id=f"sefaria-he-{book_key}",
        trusted_source_id=SEFARIA_TS,
        title=f"{display_name} (Hebrew Original - Masoretic Text)",
        culture=info["culture"],
        language="Hebrew",
        source_url=f"https://www.sefaria.org/{quote(api_name)}",
        text=full_text,
        version_type="original",
        source_category="text_corpus",
        language_family=info.get("lang_family"),
        origin_place=info.get("place"),
    )
    log.info("  %s: %s (%d chars)", display_name, result, len(full_text))
    return 1 if result == "inserted" else 0


async def ingest_sefaria_ref(pool, client, spec: dict):
    """Ingest a specific Sefaria reference (whole text at once)."""
    ref = spec["ref"]
    he = await fetch_sefaria_text(client, ref)
    if not he or len(he) < 50:
        log.warning("No/insufficient text for %s", ref)
        return 0

    result = await insert_text(
        pool,
        external_id=f"sefaria-he-{ref.replace(' ', '_')}",
        trusted_source_id=SEFARIA_TS,
        title=f"{spec['title']} ({spec['lang']} Original)",
        culture=spec["culture"],
        language=spec["lang"],
        source_url=f"https://www.sefaria.org/{quote(ref)}",
        text=he,
        version_type="original",
        source_category="text_corpus",
        language_family=spec.get("lang_family"),
        origin_place=spec.get("place"),
    )
    log.info("  %s: %s (%d chars)", spec["title"], result, len(he))
    return 1 if result == "inserted" else 0


async def ingest_talmud_tractate(pool, client, tractate: str, talmud_type: str = "Bavli"):
    """Ingest a Talmud tractate page by page."""
    display = f"{talmud_type} {tractate.replace('_', ' ')}"
    if talmud_type == "Yerushalmi":
        ref_base = tractate
    else:
        ref_base = tractate

    all_parts = []
    # Talmud pages go 2a, 2b, 3a, 3b ... up to ~150+
    for page_num in range(2, 180):
        for side in ("a", "b"):
            if talmud_type == "Yerushalmi":
                ref = f"{ref_base}.{page_num}.{1 if side == 'a' else 2}"
            else:
                ref = f"{ref_base}.{page_num}{side}"
            he = await fetch_sefaria_text(client, ref)
            if he and len(he) > 10:
                all_parts.append(f"=== {display} {page_num}{side} ===\n{he}")
            elif he is None and page_num > 10:
                break  # reached end of tractate
            await asyncio.sleep(RATE_LIMIT_DELAY)
        if not all_parts or (he is None and page_num > 10):
            break

    if not all_parts:
        log.warning("No text for %s", display)
        return 0

    full_text = "\n\n".join(all_parts)
    result = await insert_text(
        pool,
        external_id=f"sefaria-he-talmud-{talmud_type.lower()}-{tractate}",
        trusted_source_id=SEFARIA_TS,
        title=f"Talmud {display} (Hebrew/Aramaic Original)",
        culture="Jewish/Rabbinic",
        language="Hebrew/Aramaic",
        source_url=f"https://www.sefaria.org/{quote(ref_base)}",
        text=full_text,
        version_type="original",
        source_category="text_corpus",
        language_family="Semitic",
        origin_place="Babylon" if talmud_type == "Bavli" else "Land of Israel",
    )
    log.info("  %s: %s (%d chars)", display, result, len(full_text))
    return 1 if result == "inserted" else 0


async def ingest_zohar(pool, client):
    """Ingest Zohar volumes."""
    total = 0
    for section in ZOHAR_SECTIONS:
        vol = section.split(".")[1]
        all_parts = []
        for page in range(1, 300):
            ref = f"Zohar.{vol}.{page}"
            he = await fetch_sefaria_text(client, ref)
            if he and len(he) > 10:
                all_parts.append(f"=== Zohar Vol {vol}, Page {page} ===\n{he}")
            elif he is None and page > 5:
                break
            await asyncio.sleep(RATE_LIMIT_DELAY)

        if not all_parts:
            continue

        full_text = "\n\n".join(all_parts)
        result = await insert_text(
            pool,
            external_id=f"sefaria-he-zohar-vol{vol}",
            trusted_source_id=SEFARIA_TS,
            title=f"Zohar Volume {vol} (Aramaic Original)",
            culture="Jewish/Kabbalistic",
            language="Aramaic",
            source_url=f"https://www.sefaria.org/Zohar.{vol}",
            text=full_text,
            version_type="original",
            source_category="text_corpus",
            language_family="Semitic",
        )
        log.info("  Zohar Vol %s: %s (%d chars)", vol, result, len(full_text))
        total += 1 if result == "inserted" else 0

    return total


async def run_sefaria_ingestion(pool):
    """Main Sefaria ingestion orchestrator."""
    log.info("=" * 60)
    log.info("SEFARIA INGESTION - Original Hebrew/Aramaic texts")
    log.info("=" * 60)

    total = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Hebrew Bible (Tanakh) - all 39 books
        log.info("--- Hebrew Bible (Tanakh) ---")
        for book_key, info in SEFARIA_BOOKS.items():
            n = await ingest_sefaria_book(pool, client, book_key, info)
            total += n

        # 2. Targumim, Midrash, Jasher, Mishnah
        log.info("--- Targumim, Midrash, Jasher, Mishnah ---")
        for spec in SEFARIA_EXTRA_TEXTS:
            n = await ingest_sefaria_ref(pool, client, spec)
            total += n
            await asyncio.sleep(RATE_LIMIT_DELAY)

        # 3. Talmud Bavli (key tractates)
        log.info("--- Talmud Bavli (key tractates) ---")
        for tractate in TALMUD_TRACTATES:
            n = await ingest_talmud_tractate(pool, client, tractate, "Bavli")
            total += n

        # 4. Jerusalem Talmud
        log.info("--- Jerusalem Talmud ---")
        for tractate in YERUSHALMI_TRACTATES:
            n = await ingest_talmud_tractate(pool, client, tractate, "Yerushalmi")
            total += n

        # 5. Zohar
        log.info("--- Zohar ---")
        n = await ingest_zohar(pool, client)
        total += n

    log.info("Sefaria ingestion complete: %d new records", total)
    return total


# ============================================================
# SACRED-TEXTS.COM INGESTION
# ============================================================

SACRED_TEXTS_BOOKS = [
    {
        "base_url": "https://sacred-texts.com/chr/apo/jasher/",
        "index_range": range(1, 92),
        "page_fmt": "{:02d}.htm",
        "title": "Book of Jasher (Sefer HaYashar, 1887 Edition)",
        "culture": "Jewish",
        "language": "English (1887 translation from Hebrew)",
        "ext_id": "sacred-texts-jasher",
    },
    {
        "base_url": "https://sacred-texts.com/chr/ps/",
        "index_range": range(1, 164),
        "page_fmt": "ps{:03d}.htm",
        "title": "Pistis Sophia (G.R.S. Mead, 1921)",
        "culture": "Gnostic",
        "language": "English (1921 translation from Coptic)",
        "ext_id": "sacred-texts-pistis-sophia",
    },
    {
        "base_url": "https://sacred-texts.com/mas/md/",
        "index_range": range(0, 33),
        "page_fmt": "md{:02d}.htm",
        "title": "Albert Pike - Morals and Dogma (1871)",
        "culture": "Freemasonry/Esoteric",
        "language": "English",
        "ext_id": "sacred-texts-morals-dogma",
    },
    {
        "base_url": "https://sacred-texts.com/eso/sta/",
        "index_range": range(1, 50),
        "page_fmt": "sta{:02d}.htm",
        "title": "Manly P. Hall - The Secret Teachings of All Ages (1928)",
        "culture": "Esoteric/Western",
        "language": "English",
        "ext_id": "sacred-texts-secret-teachings",
    },
]


async def scrape_sacred_text(client: httpx.AsyncClient, book_spec: dict) -> str | None:
    """Scrape a multi-page book from sacred-texts.com."""
    parts = []
    for i in book_spec["index_range"]:
        page_name = book_spec["page_fmt"].format(i)
        url = book_spec["base_url"] + page_name
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                if i > 5 and len(parts) > 0:
                    break
                continue
            text = resp.text
            # Extract body content between <body> tags
            body_match = re.search(r"<body[^>]*>(.*?)</body>", text, re.DOTALL | re.IGNORECASE)
            if body_match:
                body = body_match.group(1)
                body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
                body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
                clean = strip_html(body)
                if clean and len(clean) > 50:
                    parts.append(clean)
        except Exception as e:
            log.warning("Error scraping %s page %d: %s", book_spec["title"], i, e)
        await asyncio.sleep(0.3)

    if parts:
        return "\n\n---\n\n".join(parts)
    return None


async def run_sacred_texts_ingestion(pool):
    """Ingest texts from sacred-texts.com."""
    log.info("=" * 60)
    log.info("SACRED-TEXTS.COM INGESTION")
    log.info("=" * 60)

    total = 0
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for spec in SACRED_TEXTS_BOOKS:
            log.info("Scraping: %s", spec["title"])
            text = await scrape_sacred_text(client, spec)
            if not text or len(text) < 500:
                log.warning("  Insufficient text for %s", spec["title"])
                continue

            result = await insert_text(
                pool,
                external_id=spec["ext_id"],
                trusted_source_id=SACRED_TEXTS_TS,
                title=spec["title"],
                culture=spec["culture"],
                language=spec["language"],
                source_url=spec["base_url"],
                text=text,
                version_type="translation",
                source_category="public_domain_library",
            )
            log.info("  %s: %s (%d chars)", spec["title"], result, len(text))
            total += 1 if result == "inserted" else 0

    log.info("Sacred-texts.com ingestion complete: %d new records", total)
    return total


# ============================================================
# PERSEUS DIGITAL LIBRARY INGESTION (Greek/Latin)
# ============================================================

PERSEUS_TEXTS = [
    {"urn": "tlg0012.tlg001", "lang_code": "grc", "title": "Homer - Iliad", "culture": "Ancient Greek", "language": "Ancient Greek"},
    {"urn": "tlg0012.tlg002", "lang_code": "grc", "title": "Homer - Odyssey", "culture": "Ancient Greek", "language": "Ancient Greek"},
    {"urn": "tlg0020.tlg001", "lang_code": "grc", "title": "Hesiod - Theogony", "culture": "Ancient Greek", "language": "Ancient Greek"},
    {"urn": "tlg0020.tlg002", "lang_code": "grc", "title": "Hesiod - Works and Days", "culture": "Ancient Greek", "language": "Ancient Greek"},
    {"urn": "phi0959.phi006", "lang_code": "lat", "title": "Ovid - Metamorphoses", "culture": "Roman", "language": "Latin"},
]

# Scaife viewer API for fetching passage text
SCAIFE_BASE = "https://scaife-cts.perseus.org/api/cts"


async def fetch_perseus_text(client: httpx.AsyncClient, urn: str, lang_code: str) -> str | None:
    """Fetch text from Perseus Scaife CTS API."""
    # Try the GitHub raw files first (more reliable for full texts)
    if lang_code == "grc":
        repo = "PerseusDL/canonical-greekLit"
    else:
        repo = "PerseusDL/canonical-latinLit"

    # Try Scaife viewer passage API
    full_urn = f"urn:cts:{'greekLit' if lang_code == 'grc' else 'latinLit'}:{urn}"
    url = f"https://scaife.perseus.org/library/{full_urn}/"

    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            body = resp.text
            # Extract the text content from the Scaife page
            text_match = re.findall(r'class="text-[^"]*"[^>]*>(.*?)</(?:div|p|span)', body, re.DOTALL)
            if text_match:
                clean = "\n".join(strip_html(m) for m in text_match if len(strip_html(m)) > 5)
                if len(clean) > 200:
                    return clean
    except Exception as e:
        log.warning("Scaife fetch failed for %s: %s", urn, e)

    # Fallback: try Perseus hopper
    url2 = f"https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:{urn}"
    try:
        resp = await client.get(url2)
        if resp.status_code == 200:
            body_match = re.search(r'id="text_container"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            if body_match:
                return strip_html(body_match.group(1))
    except Exception:
        pass

    return None


async def run_perseus_ingestion(pool):
    """Ingest original Greek/Latin texts from Perseus."""
    log.info("=" * 60)
    log.info("PERSEUS DIGITAL LIBRARY - Original Greek/Latin")
    log.info("=" * 60)

    total = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for spec in PERSEUS_TEXTS:
            log.info("Fetching: %s", spec["title"])
            text = await fetch_perseus_text(client, spec["urn"], spec["lang_code"])
            if not text or len(text) < 200:
                log.warning("  Insufficient text for %s, trying alternate approach", spec["title"])
                # Try fetching from raw GitHub
                continue

            result = await insert_text(
                pool,
                external_id=f"perseus-{spec['lang_code']}-{spec['urn']}",
                trusted_source_id=PERSEUS_TS,
                title=f"{spec['title']} ({spec['language']} Original)",
                culture=spec["culture"],
                language=spec["language"],
                source_url=f"https://scaife.perseus.org/library/urn:cts:{'greekLit' if spec['lang_code'] == 'grc' else 'latinLit'}:{spec['urn']}/",
                text=text,
                version_type="original",
                source_category="text_corpus",
                language_family="Indo-European",
                origin_place="Greece" if spec["lang_code"] == "grc" else "Rome",
            )
            log.info("  %s: %s (%d chars)", spec["title"], result, len(text))
            total += 1 if result == "inserted" else 0
            await asyncio.sleep(1)

    log.info("Perseus ingestion complete: %d new records", total)
    return total


# ============================================================
# TSV UPDATE
# ============================================================

async def update_tsv(pool):
    """Populate tsv columns on all new records."""
    log.info("Updating tsv columns...")
    async with pool.acquire() as conn:
        n1 = await conn.execute("""
            UPDATE source_records SET tsv = to_tsvector('english',
                COALESCE(canonical_title, '') || ' ' || COALESCE(culture, '') || ' ' ||
                COALESCE(origin_place_name, '') || ' ' || COALESCE(language_family, ''))
            WHERE tsv IS NULL
        """)
        log.info("  source_records tsv updated: %s", n1)

        n2 = await conn.execute("""
            UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
            WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL
        """)
        log.info("  source_versions tsv updated: %s", n2)


# ============================================================
# MAIN
# ============================================================

async def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"

    pool = await asyncpg.create_pool(
        DB_URL, min_size=1, max_size=3,
        command_timeout=300,
        server_settings={"statement_timeout": "300000"},
    )

    try:
        grand_total = 0

        if what in ("all", "sefaria"):
            grand_total += await run_sefaria_ingestion(pool)

        if what in ("all", "sacred"):
            grand_total += await run_sacred_texts_ingestion(pool)

        if what in ("all", "perseus"):
            grand_total += await run_perseus_ingestion(pool)

        # Always update tsv at the end
        await update_tsv(pool)

        log.info("=" * 60)
        log.info("TOTAL NEW RECORDS INGESTED: %d", grand_total)
        log.info("=" * 60)

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
