#!/usr/bin/env python3
"""Ingest original Greek/Latin from Perseus GitHub + public domain texts from Gutenberg."""

import asyncio
import hashlib
import html
import json
import logging
import re
import sys
from urllib.parse import quote
from xml.etree import ElementTree as ET

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://eden:eden@127.0.0.1:5432/eden"
PERSEUS_TS = "c754d415-b1ee-4337-8622-28f875fa1163"
GUTENBERG_TS = "e92b6a5b-8a20-4b39-a808-f8982cf0f62d"
SACRED_TS = "e74de463-456d-42e4-9b0a-001d908b30cc"


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


async def insert_text(pool, *, external_id, trusted_source_id, title, culture, language,
                      source_url, text, version_type="original", source_category="text_corpus",
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


# ==========================================================================
# PERSEUS GITHUB - TEI XML
# ==========================================================================

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

PERSEUS_GITHUB_TEXTS = [
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0012/tlg001",  # Homer Iliad
        "title": "Homer - Iliad",
        "culture": "Ancient Greek",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Greece",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0012/tlg002",  # Homer Odyssey
        "title": "Homer - Odyssey",
        "culture": "Ancient Greek",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Greece",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0020/tlg001",  # Hesiod Theogony
        "title": "Hesiod - Theogony",
        "culture": "Ancient Greek",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Greece",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0020/tlg002",  # Hesiod Works and Days
        "title": "Hesiod - Works and Days",
        "culture": "Ancient Greek",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Greece",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0526/tlg001",  # Josephus Antiquities
        "title": "Josephus - Antiquities of the Jews",
        "culture": "Jewish/Hellenistic",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Roman Palestine",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0526/tlg004",  # Josephus Jewish War
        "title": "Josephus - The Jewish War",
        "culture": "Jewish/Hellenistic",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Roman Palestine",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg0018/tlg001",  # Philo
        "title": "Philo of Alexandria - On the Creation",
        "culture": "Jewish/Hellenistic",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Alexandria",
    },
    {
        "repo": "PerseusDL/canonical-greekLit",
        "path": "data/tlg2018/tlg002",  # Eusebius
        "title": "Eusebius - Ecclesiastical History",
        "culture": "Early Christian",
        "language": "Ancient Greek",
        "lang_code": "grc",
        "origin": "Caesarea",
    },
    {
        "repo": "PerseusDL/canonical-latinLit",
        "path": "data/phi0959/phi006",  # Ovid Metamorphoses
        "title": "Ovid - Metamorphoses",
        "culture": "Roman",
        "language": "Latin",
        "lang_code": "lat",
        "origin": "Rome",
    },
    {
        "repo": "PerseusDL/canonical-latinLit",
        "path": "data/stoa0040/stoa001",  # Augustine City of God
        "title": "Augustine - City of God (De Civitate Dei)",
        "culture": "Early Christian/Roman",
        "language": "Latin",
        "lang_code": "lat",
        "origin": "Hippo Regius",
    },
]


def extract_text_from_tei(xml_bytes: bytes) -> str:
    """Extract text content from a TEI XML document."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    body = root.find(".//tei:body", TEI_NS)
    if body is None:
        body = root.find(".//{http://www.tei-c.org/ns/1.0}body")
    if body is None:
        body = root.find(".//body")
    if body is None:
        return ET.tostring(root, encoding="unicode", method="text")

    return ET.tostring(body, encoding="unicode", method="text").strip()


async def find_greek_xml(client: httpx.AsyncClient, repo: str, path: str, lang_code: str) -> tuple[str, bytes] | None:
    """Find the original-language TEI XML file in a Perseus GitHub directory."""
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        resp = await client.get(api_url)
        if resp.status_code != 200:
            log.warning("GitHub API %s returned %d", api_url, resp.status_code)
            return None

        files = resp.json()
        if not isinstance(files, list):
            return None

        # Look for original-language XML (grc1 or lat1 editions)
        target_files = []
        for f in files:
            name = f.get("name", "")
            if name.endswith(".xml"):
                # Prefer files with grc/lat in the name
                if f".{lang_code}" in name or f"_{lang_code}" in name:
                    target_files.insert(0, f)
                elif "eng" not in name.lower() and "english" not in name.lower():
                    target_files.append(f)

        if not target_files:
            log.warning("No suitable XML in %s", path)
            return None

        # Try each candidate
        for tf in target_files[:3]:
            raw_url = tf.get("download_url", "")
            if not raw_url:
                continue
            resp2 = await client.get(raw_url)
            if resp2.status_code == 200:
                text = extract_text_from_tei(resp2.content)
                if text and len(text) > 200:
                    return (raw_url, resp2.content)
                log.info("  File %s had insufficient text (%d chars)", tf["name"], len(text))
            await asyncio.sleep(0.5)

    except Exception as e:
        log.error("Error finding XML in %s: %s", path, e)
    return None


async def run_perseus(pool):
    log.info("=" * 60)
    log.info("PERSEUS GITHUB - Original Greek/Latin TEI XML")
    log.info("=" * 60)

    total = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                  headers={"Accept": "application/json"}) as client:
        for spec in PERSEUS_GITHUB_TEXTS:
            log.info("Fetching: %s", spec["title"])
            result = await find_greek_xml(client, spec["repo"], spec["path"], spec["lang_code"])
            if not result:
                log.warning("  No text found for %s", spec["title"])
                continue

            raw_url, xml_bytes = result
            text = extract_text_from_tei(xml_bytes)
            if not text or len(text) < 200:
                log.warning("  Text too short for %s", spec["title"])
                continue

            ext_id = f"perseus-{spec['lang_code']}-{spec['path'].replace('/', '-')}"
            r = await insert_text(
                pool,
                external_id=ext_id,
                trusted_source_id=PERSEUS_TS,
                title=f"{spec['title']} ({spec['language']} Original)",
                culture=spec["culture"],
                language=spec["language"],
                source_url=raw_url,
                text=text,
                version_type="original",
                language_family="Indo-European",
                origin_place=spec["origin"],
            )
            log.info("  %s: %s (%d chars)", spec["title"], r, len(text))
            total += 1 if r == "inserted" else 0
            await asyncio.sleep(1)

    log.info("Perseus complete: %d new records", total)
    return total


# ==========================================================================
# GUTENBERG / INTERNET ARCHIVE - Public domain texts
# ==========================================================================

GUTENBERG_TEXTS = [
    {
        "url": "https://www.gutenberg.org/cache/epub/2392/pg2392.txt",
        "title": "Albert Pike - Morals and Dogma (1871)",
        "culture": "Freemasonry/Esoteric",
        "language": "English",
        "ext_id": "gutenberg-morals-dogma-2392",
    },
    {
        "url": "https://www.gutenberg.org/cache/epub/22400/pg22400.txt",
        "title": "Foxe's Book of Martyrs (1563, Actes and Monuments)",
        "culture": "Christian/Reformation",
        "language": "English",
        "ext_id": "gutenberg-foxe-martyrs-22400",
    },
]

# For texts not on Gutenberg, try Internet Archive
ARCHIVE_TEXTS = [
    {
        "url": "https://archive.org/download/bookofJasher/bookOfJasher.txt",
        "alt_urls": [
            "https://raw.githubusercontent.com/scrollmapper/bible_databases_deuterocanonical/master/sources/en_jasher.txt",
        ],
        "title": "Book of Jasher (Sefer HaYashar, 1840 Translation)",
        "culture": "Jewish",
        "language": "English (1840 translation from Hebrew)",
        "ext_id": "archive-book-of-jasher",
    },
    {
        "url": "https://www.gutenberg.org/cache/epub/56encyclopaedia/pg56encyclopaedia.txt",
        "alt_urls": [
            "https://raw.githubusercontent.com/gnosis-library/pistis-sophia/master/text/pistis_sophia.txt",
        ],
        "title": "Pistis Sophia (G.R.S. Mead Translation, 1921)",
        "culture": "Gnostic",
        "language": "English (translation from Coptic)",
        "ext_id": "archive-pistis-sophia",
    },
]

# Manly P. Hall's Secret Teachings was originally published 1928 — checking public domain status
ADDITIONAL_TEXTS = [
    {
        "url": "https://www.gutenberg.org/cache/epub/7142/pg7142.txt",
        "title": "Flavius Josephus - Antiquities of the Jews (William Whiston Translation)",
        "culture": "Jewish/Hellenistic",
        "language": "English (Whiston translation)",
        "ext_id": "gutenberg-josephus-antiquities-7142",
        "version_type": "translation",
    },
    {
        "url": "https://www.gutenberg.org/cache/epub/2850/pg2850.txt",
        "title": "Flavius Josephus - The Wars of the Jews (William Whiston Translation)",
        "culture": "Jewish/Hellenistic",
        "language": "English (Whiston translation)",
        "ext_id": "gutenberg-josephus-wars-2850",
        "version_type": "translation",
    },
]


async def fetch_text_from_urls(client: httpx.AsyncClient, urls: list[str]) -> str | None:
    """Try fetching text from multiple URLs, returning the first success."""
    for url in urls:
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                text = resp.text
                if len(text) > 500:
                    return text
        except Exception as e:
            log.warning("Error fetching %s: %s", url, e)
        await asyncio.sleep(0.5)
    return None


async def run_gutenberg(pool):
    log.info("=" * 60)
    log.info("GUTENBERG + INTERNET ARCHIVE - Public Domain Texts")
    log.info("=" * 60)

    total = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        all_texts = []
        for spec in GUTENBERG_TEXTS:
            all_texts.append({**spec, "urls": [spec["url"]]})
        for spec in ARCHIVE_TEXTS:
            urls = [spec["url"]] + spec.get("alt_urls", [])
            all_texts.append({**spec, "urls": urls})
        for spec in ADDITIONAL_TEXTS:
            all_texts.append({**spec, "urls": [spec["url"]]})

        for spec in all_texts:
            log.info("Fetching: %s", spec["title"])
            text = await fetch_text_from_urls(client, spec["urls"])
            if not text:
                log.warning("  Could not fetch %s", spec["title"])
                continue

            # Clean up Gutenberg headers/footers
            start_markers = ["*** START OF", "***START OF", "*** START OF THE PROJECT"]
            end_markers = ["*** END OF", "***END OF", "*** END OF THE PROJECT"]
            for marker in start_markers:
                idx = text.find(marker)
                if idx != -1:
                    newline = text.find("\n", idx)
                    if newline != -1:
                        text = text[newline + 1:]
                    break
            for marker in end_markers:
                idx = text.find(marker)
                if idx != -1:
                    text = text[:idx]
                    break

            text = text.strip()
            if len(text) < 500:
                log.warning("  Text too short for %s (%d chars)", spec["title"], len(text))
                continue

            vtype = spec.get("version_type", "translation")
            r = await insert_text(
                pool,
                external_id=spec["ext_id"],
                trusted_source_id=GUTENBERG_TS,
                title=spec["title"],
                culture=spec["culture"],
                language=spec["language"],
                source_url=spec["urls"][0],
                text=text,
                version_type=vtype,
                source_category="public_domain_library",
            )
            log.info("  %s: %s (%d chars)", spec["title"], r, len(text))
            total += 1 if r == "inserted" else 0

    log.info("Gutenberg/Archive complete: %d new records", total)
    return total


# ==========================================================================
# TSV
# ==========================================================================

async def update_tsv(pool):
    log.info("Updating tsv columns...")
    async with pool.acquire() as conn:
        n1 = await conn.execute("""
            UPDATE source_records SET tsv = to_tsvector('english',
                COALESCE(canonical_title, '') || ' ' || COALESCE(culture, '') || ' ' ||
                COALESCE(origin_place_name, '') || ' ' || COALESCE(language_family, ''))
            WHERE tsv IS NULL
        """)
        log.info("  source_records: %s", n1)
        n2 = await conn.execute("""
            UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
            WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL
        """)
        log.info("  source_versions: %s", n2)


async def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3,
                                     command_timeout=300,
                                     server_settings={"statement_timeout": "300000"})
    try:
        total = 0
        if what in ("all", "perseus"):
            total += await run_perseus(pool)
        if what in ("all", "gutenberg"):
            total += await run_gutenberg(pool)
        await update_tsv(pool)
        log.info("GRAND TOTAL: %d new records", total)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
