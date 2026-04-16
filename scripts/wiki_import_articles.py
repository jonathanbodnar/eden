"""
Import filtered ancient-world articles from Wikipedia XML dump into the DB.

Reads ancient_page_ids.json (built by wiki_build_filter_v4.py) and streams
articles.xml.bz2, extracting only matching page IDs.

Uses asyncpg connection pool with auto-retry for resilience.

Usage:
  python3 wiki_import_articles.py [--batch-size 50] [--max-text 50000]
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
                                                created_at, updated_at)
                    VALUES (gen_random_uuid(), $1, $2, $3, $4, 'text_corpus',
                            'verified', 'published', NOW(), NOW())
                    RETURNING id
                """, ro_id, WIKI_SOURCE_ID, article['title'][:500], article['culture'])

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
    """Generator that yields article dicts from the bz2 XML dump.
    
    Uses start/end events to properly track page vs revision context."""
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

            # event == "end"
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
                                    "total_scanned": total_scanned,
                                }

                elem.clear()

                if total_scanned % 100000 == 0:
                    log.info(f"  XML scan: {total_scanned:,} pages scanned so far...")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=50)
    parser.add_argument('--max-text', type=int, default=50000)
    parser.add_argument('--fts-interval', type=int, default=2000,
                        help='Update FTS every N articles')
    args = parser.parse_args()

    filter_path = Path(DUMP_DIR) / "ancient_page_ids.json"
    articles_path = Path(DUMP_DIR) / "articles.xml.bz2"

    if not filter_path.exists():
        log.error("ancient_page_ids.json not found")
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

    # Check existing
    async def _check_existing(conn):
        rows = await conn.fetch("""
            SELECT external_id FROM raw_objects
            WHERE trusted_source_id = $1 AND external_id LIKE 'wiki-page-%'
        """, WIKI_SOURCE_ID)
        return {r['external_id'] for r in rows}

    existing_ids = await db_op(pool, _check_existing)
    log.info(f"Already have {len(existing_ids):,} Wikipedia articles in DB")

    log.info(f"Streaming articles.xml.bz2 ({articles_path})...")
    batch = []
    imported = 0
    skipped = 0
    total_matched = 0

    for article in stream_articles(str(articles_path), target_ids, args.max_text):
        total_matched += 1

        if article['external_id'] in existing_ids:
            skipped += 1
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

        scanned = article.get('total_scanned', 0)
        if total_matched % 1000 == 0:
            log.info(
                f"  Matched {total_matched:,} | Imported {imported:,} | "
                f"Skipped {skipped:,} | XML scanned ~{scanned:,}"
            )

    # Final batch
    if batch:
        try:
            n = await insert_batch(pool, batch)
            imported += n
        except Exception as e:
            log.error(f"Final batch insert failed: {e}")

    # Final FTS
    try:
        await update_fts(pool)
        log.info("Final FTS update done")
    except Exception as e:
        log.warning(f"Final FTS update failed: {e}")

    await pool.close()
    log.info(f"\n{'='*60}")
    log.info(f"DONE: {imported:,} imported, {skipped:,} skipped, {total_matched:,} total matched")
    log.info(f"{'='*60}")


asyncio.run(main())
