"""
Import filtered ancient-world articles from Wikipedia XML dump into the DB (v2).

Key improvements over v1:
- Uses v5 tight filter (52k articles from 4,917 categories)
- Extracts dates from infoboxes and article text
- Stores dates in metadata_jsonb
- Only skips already-imported articles (by external_id)

Usage:
  python3 wiki_import_v2.py [--batch-size 50] [--max-text 50000]
"""

import asyncio
import argparse
import bz2
import hashlib
import json
import logging
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

DB_URL = 'postgresql://eden:eden@127.0.0.1:5432/eden'
DUMP_DIR = '/opt/wiki-dump'
WIKI_SOURCE_ID = uuid.UUID('bb45f74d-163b-4ee8-9eb6-52fba63e9360')

MAX_RETRIES = 5
RETRY_BACKOFF = 3

SKIP_SECTIONS = {
    "see also", "references", "external links", "further reading",
    "notes", "citations", "bibliography", "sources",
    "interpretation", "interpretations", "theories", "scholarly debate",
    "historiography", "modern reception", "legacy", "in popular culture",
    "in fiction", "cultural references", "influence", "modern scholarship",
    "academic debate", "controversy", "criticism", "gallery",
}

# ── Date extraction patterns ──

# "123 BC", "c. 456 BCE", "circa 789 BC", "fl. 200 BCE", etc.
BC_YEAR_RE = re.compile(
    r'(?:c\.?\s*|circa\s+|ca\.?\s*|fl\.?\s*|r\.?\s*)?'
    r'(?<!\d)(\d{1,4})\s*(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)

AD_YEAR_RE = re.compile(
    r'(?:c\.?\s*|circa\s+|ca\.?\s*|fl\.?\s*|r\.?\s*)?'
    r'(?<!\d)(\d{1,4})\s*(?:AD|CE|A\.D\.?|C\.E\.?)',
    re.IGNORECASE
)

# Century patterns: "3rd century BC", "5th century BCE"
BC_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+century\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)
AD_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+century\s+(?:AD|CE|A\.D\.?|C\.E\.?)',
    re.IGNORECASE
)

# Millennium patterns: "3rd millennium BC"
BC_MILLENNIUM_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+millennium\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)

# Infobox field patterns for dates
INFOBOX_DATE_FIELDS = re.compile(
    r'\|\s*(?:birth_date|death_date|date|reign|era|period|years?|'
    r'established|founded|dissolved|abandoned|built|'
    r'reign_start|reign_end|date_start|date_end|'
    r'born|died|flourished?)\s*=\s*([^\n|}{]+)',
    re.IGNORECASE
)

# Bare year in infobox (e.g., |birth_date = 356 BC)
BARE_YEAR_RE = re.compile(r'^\s*(?:c\.?\s*)?(\d{1,5})\s*$')


def extract_dates_from_text(raw_text: str) -> dict:
    """Extract date information from wiki markup, returning year range and text."""
    bc_years = []
    ad_years = []

    # Check infobox fields first (most reliable)
    for m in INFOBOX_DATE_FIELDS.finditer(raw_text[:5000]):
        field_text = m.group(1).strip()
        for ym in BC_YEAR_RE.finditer(field_text):
            bc_years.append(int(ym.group(1)))
        for ym in AD_YEAR_RE.finditer(field_text):
            ad_years.append(int(ym.group(1)))
        for cm in BC_CENTURY_RE.finditer(field_text):
            century = int(cm.group(1))
            bc_years.append(century * 100)
        for cm in AD_CENTURY_RE.finditer(field_text):
            century = int(cm.group(1))
            ad_years.append((century - 1) * 100 + 50)

    # Also scan first 2000 chars of article body
    body_sample = raw_text[:2000]
    for ym in BC_YEAR_RE.finditer(body_sample):
        bc_years.append(int(ym.group(1)))
    for ym in AD_YEAR_RE.finditer(body_sample):
        ad_years.append(int(ym.group(1)))
    for cm in BC_CENTURY_RE.finditer(body_sample):
        century = int(cm.group(1))
        bc_years.append(century * 100)
    for cm in AD_CENTURY_RE.finditer(body_sample):
        century = int(cm.group(1))
        ad_years.append((century - 1) * 100 + 50)
    for mm in BC_MILLENNIUM_RE.finditer(body_sample):
        mil = int(mm.group(1))
        bc_years.append(mil * 1000)

    bc_years = [y for y in bc_years if 1 <= y <= 10000]
    ad_years = [y for y in ad_years if 1 <= y <= 800]

    # Convert to negative (BCE) / positive (CE) unified timeline
    all_years = [-y for y in bc_years] + ad_years

    if not all_years:
        return {}

    date_start = min(all_years)
    date_end = max(all_years)

    # Build readable text
    parts = []
    if bc_years:
        parts.append(f"{max(bc_years)} BC")
    if ad_years:
        parts.append(f"{min(ad_years)} AD")
    date_text = " – ".join(parts) if len(parts) > 1 else parts[0] if parts else ""

    return {
        "date_start": date_start,
        "date_end": date_end,
        "date_text": date_text,
    }


def is_plausibly_ancient(dates: dict) -> bool:
    """Check if the extracted dates suggest genuinely ancient content (pre-700 CE)."""
    if not dates:
        return True  # No dates = can't disqualify; category filter already screened it
    return dates.get("date_start", 0) < 700


def filter_sections(text: str) -> str:
    lines = text.split("\n")
    result = []
    skip = False
    current_level = 0
    for line in lines:
        header_match = re.match(r"^(={2,})\s*(.+?)\s*={2,}", line)
        if header_match:
            level = len(header_match.group(1))
            section_name = header_match.group(2).strip().lower()
            if section_name in SKIP_SECTIONS:
                skip = True
                current_level = level
                continue
            elif skip and level <= current_level:
                skip = False
        if not skip:
            result.append(line)
    return "\n".join(result)


def clean_wiki_text(raw_text: str) -> str:
    text = raw_text
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^/]*/?>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://[^\]]*\]", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def infer_culture_from_categories(page_id: int, page_titles: dict) -> str:
    title = page_titles.get(str(page_id), '').lower().replace('_', ' ')
    if any(k in title for k in ['egypt', 'pharaoh', 'nile', 'hieroglyph']):
        return 'Egyptian'
    if any(k in title for k in ['greek', 'greece', 'athens', 'sparta', 'hellenic']):
        return 'Greek'
    if any(k in title for k in ['roman', 'rome', 'latin', 'caesar']):
        return 'Roman'
    if any(k in title for k in ['mesopotamia', 'sumer', 'babylon', 'assyria', 'akkad']):
        return 'Mesopotamian'
    if any(k in title for k in ['india', 'vedic', 'hindu', 'buddhist', 'sanskrit']):
        return 'Indic'
    if any(k in title for k in ['chinese', 'china', 'zhou', 'shang']):
        return 'Chinese'
    if any(k in title for k in ['persia', 'zoroastr', 'achaemenid']):
        return 'Persian'
    if any(k in title for k in ['norse', 'viking', 'odin']):
        return 'Norse'
    if any(k in title for k in ['celtic', 'druid', 'gaelic']):
        return 'Celtic'
    if any(k in title for k in ['maya', 'aztec', 'inca', 'olmec', 'mesoameric']):
        return 'Mesoamerican'
    if any(k in title for k in ['jewish', 'hebrew', 'israel', 'judah']):
        return 'Jewish/Hebrew'
    if any(k in title for k in ['phoenici', 'carthage', 'canaan']):
        return 'Phoenician'
    return 'Ancient'


async def db_op(pool, coro_factory):
    for attempt in range(MAX_RETRIES):
        conn = None
        try:
            conn = await pool.acquire()
            return await coro_factory(conn)
        except (asyncpg.ConnectionDoesNotExistError,
                asyncpg.InterfaceError,
                asyncpg.InternalClientError,
                OSError) as e:
            log.warning(f"DB error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
        except Exception:
            raise
        finally:
            if conn is not None:
                try:
                    await pool.release(conn)
                except Exception:
                    pass
    raise RuntimeError("DB operation failed after max retries")


async def insert_batch(pool, batch: list[dict]):
    async def _do(conn):
        inserted = 0
        for article in batch:
            ext_id = article['external_id']
            existing = await conn.fetchval(
                'SELECT id FROM raw_objects WHERE external_id = $1', ext_id)
            if existing:
                continue

            text = article['text']
            checksum = hashlib.sha256(text.encode()).hexdigest()
            byte_size = len(text.encode('utf-8'))
            r2_key = f"wiki-dump/{ext_id}.txt"
            metadata = json.dumps(article.get('dates', {})) if article.get('dates') else None

            async with conn.transaction():
                ro_id = await conn.fetchval("""
                    INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                             content_type, checksum, byte_size, r2_key, fetched_at)
                    VALUES (gen_random_uuid(), $1, $2, $3, 'text/html', $4, $5, $6, NOW())
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """, WIKI_SOURCE_ID, ext_id, article['source_url'],
                    checksum, byte_size, r2_key)

                if ro_id is None:
                    continue

                sr_id = await conn.fetchval("""
                    INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                                culture, source_category, provenance_status, record_status,
                                                metadata_jsonb,
                                                created_at, updated_at)
                    VALUES (gen_random_uuid(), $1, $2, $3, $4, 'text_corpus',
                            'verified', 'published', $5::jsonb, NOW(), NOW())
                    RETURNING id
                """, ro_id, WIKI_SOURCE_ID, article['title'][:500],
                    article['culture'], metadata)

                if sr_id:
                    await conn.execute("""
                        INSERT INTO source_versions (id, source_record_id, version_type, language,
                                                     is_preferred, text_extracted, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1, 'original', 'English', true, $2, NOW(), NOW())
                    """, sr_id, text)
                    inserted += 1

        return inserted

    return await db_op(pool, _do)


async def update_fts(pool):
    async def _do(conn):
        await conn.execute("""
            UPDATE source_records SET tsv = to_tsvector('english',
                COALESCE(canonical_title,'') || ' ' || COALESCE(culture,''))
            WHERE tsv IS NULL
        """)
        await conn.execute("""
            UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
            WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL
        """)
    await db_op(pool, _do)


def stream_articles(articles_path: str, target_ids: set[int], max_text: int):
    with bz2.open(articles_path, "rt", encoding="utf-8", errors="replace") as f:
        context = ET.iterparse(f, events=("start", "end"))

        page_id = None
        page_title = None
        page_ns = None
        page_text = None
        in_page = False
        in_revision = False
        total_scanned = 0

        for event, elem in context:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if event == "start":
                if tag == "page":
                    in_page = True
                    in_revision = False
                    page_id = None
                    page_title = None
                    page_ns = None
                    page_text = None
                elif tag == "revision":
                    in_revision = True
                continue

            if tag == "revision":
                in_revision = False
            elif tag == "id" and in_page and not in_revision and page_id is None:
                try:
                    page_id = int(elem.text) if elem.text else None
                except (ValueError, TypeError):
                    pass
            elif tag == "title" and in_page and not in_revision:
                page_title = elem.text
            elif tag == "ns" and in_page and not in_revision:
                try:
                    page_ns = int(elem.text) if elem.text else None
                except (ValueError, TypeError):
                    page_ns = None
            elif tag == "text":
                page_text = elem.text
            elif tag == "page":
                in_page = False
                total_scanned += 1

                if page_ns == 0 and page_id in target_ids:
                    if page_text and len(page_text) > 200:
                        if not page_text.strip().upper().startswith("#REDIRECT"):
                            dates = extract_dates_from_text(page_text)

                            cleaned = filter_sections(page_text)
                            cleaned = clean_wiki_text(cleaned)
                            if len(cleaned) > 200:
                                title = (page_title or f"Wikipedia Article {page_id}").replace('_', ' ')
                                yield {
                                    "page_id": page_id,
                                    "title": title,
                                    "external_id": f"wiki-page-{page_id}",
                                    "text": cleaned[:max_text],
                                    "source_url": f"https://en.wikipedia.org/wiki/{(page_title or '').replace(' ', '_')}",
                                    "dates": dates,
                                    "total_scanned": total_scanned,
                                }

                elem.clear()

                if total_scanned % 100000 == 0:
                    log.info(f"  XML scan: {total_scanned:,} pages scanned so far...")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=50)
    parser.add_argument('--max-text', type=int, default=50000)
    parser.add_argument('--fts-interval', type=int, default=2000)
    args = parser.parse_args()

    filter_path = Path(DUMP_DIR) / "ancient_page_ids_v5.json"
    articles_path = Path(DUMP_DIR) / "articles.xml.bz2"

    if not filter_path.exists():
        log.error("ancient_page_ids_v5.json not found")
        sys.exit(1)

    with open(str(filter_path)) as f:
        filter_data = json.load(f)

    target_ids = set(filter_data["page_ids"])
    page_titles = filter_data.get("page_titles", {})
    log.info(f"Loaded filter: {len(target_ids):,} target page IDs")

    pool = await asyncpg.create_pool(
        DB_URL, min_size=1, max_size=3,
        command_timeout=120,
        server_settings={'statement_timeout': '120000'},
    )

    async def _check_existing(conn):
        rows = await conn.fetch("""
            SELECT external_id FROM raw_objects
            WHERE trusted_source_id = $1 AND external_id LIKE 'wiki-page-%%'
        """, WIKI_SOURCE_ID)
        return {r['external_id'] for r in rows}

    existing_ids = await db_op(pool, _check_existing)
    log.info(f"Already have {len(existing_ids):,} Wikipedia articles in DB")

    log.info(f"Streaming articles.xml.bz2 ({articles_path})...")
    batch = []
    imported = 0
    skipped = 0
    skipped_modern = 0
    total_matched = 0
    dates_found = 0

    for article in stream_articles(str(articles_path), target_ids, args.max_text):
        total_matched += 1

        if article['external_id'] in existing_ids:
            skipped += 1
            if total_matched % 5000 == 0:
                scanned = article.get('total_scanned', 0)
                log.info(
                    f"  Matched {total_matched:,} | Imported {imported:,} | "
                    f"Skipped(existing) {skipped:,} | Skipped(modern) {skipped_modern:,} | "
                    f"Dates found {dates_found:,} | XML ~{scanned:,}"
                )
            continue

        if article.get('dates'):
            dates_found += 1
            if not is_plausibly_ancient(article['dates']):
                skipped_modern += 1
                continue

        article['culture'] = infer_culture_from_categories(
            article['page_id'], page_titles)
        batch.append(article)

        if len(batch) >= args.batch_size:
            try:
                n = await insert_batch(pool, batch)
                imported += n
                skipped += len(batch) - n
                for a in batch:
                    existing_ids.add(a['external_id'])
            except Exception as e:
                log.error(f"Batch insert failed: {e}")
            batch = []

            if imported > 0 and imported % args.fts_interval == 0:
                try:
                    await update_fts(pool)
                    log.info(f"  FTS updated at {imported:,} inserts")
                except Exception as e:
                    log.warning(f"  FTS update failed: {e}")

        if total_matched % 1000 == 0:
            scanned = article.get('total_scanned', 0)
            log.info(
                f"  Matched {total_matched:,} | Imported {imported:,} | "
                f"Skipped(existing) {skipped:,} | Skipped(modern) {skipped_modern:,} | "
                f"Dates found {dates_found:,} | XML ~{scanned:,}"
            )

    if batch:
        try:
            n = await insert_batch(pool, batch)
            imported += n
        except Exception as e:
            log.error(f"Final batch insert failed: {e}")

    try:
        await update_fts(pool)
        log.info("Final FTS update done")
    except Exception as e:
        log.warning(f"Final FTS update failed: {e}")

    await pool.close()
    log.info(f"\n{'='*60}")
    log.info(f"DONE: {imported:,} imported, {skipped:,} skipped(existing), "
             f"{skipped_modern:,} skipped(modern), {dates_found:,} had dates, "
             f"{total_matched:,} total matched")
    log.info(f"{'='*60}")


asyncio.run(main())
