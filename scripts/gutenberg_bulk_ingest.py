"""
Bulk ingest ancient texts from Project Gutenberg using the filtered list.
Runs on the server, inserts directly to the DB via asyncpg.

Usage:
  python3 gutenberg_bulk_ingest.py [--offset N] [--limit N] [--dry-run]
"""

import asyncio
import argparse
import hashlib
import json
import logging
import re
import sys
import uuid
from pathlib import Path

import asyncpg
import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://eden:eden@127.0.0.1:5432/eden'
TS_ID = uuid.UUID('bb45f74d-163b-4ee8-9eb6-52fba63e9360')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; EdinWorldResearch/1.0)'}
SLEEP_BETWEEN = 2
MAX_RETRIES = 5
RETRY_BACKOFF = 3


def clean_html(html: str, max_chars: int = 500000) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'noscript', 'aside']):
        tag.decompose()
    body = soup.find('body') or soup
    text = body.get_text(separator='\n', strip=True)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    result = '\n'.join(lines)
    start_markers = ['*** START OF', '***START OF', 'START OF THIS PROJECT GUTENBERG']
    end_markers = ['*** END OF', '***END OF', 'END OF THIS PROJECT GUTENBERG',
                   'End of the Project Gutenberg', 'End of Project Gutenberg']
    for m in start_markers:
        idx = result.find(m)
        if idx != -1:
            nl = result.find('\n', idx)
            result = result[nl+1:] if nl != -1 else result[idx+len(m):]
            break
    for m in end_markers:
        idx = result.find(m)
        if idx != -1:
            result = result[:idx]
            break
    return result.strip()[:max_chars]


async def fetch_text(client: httpx.AsyncClient, book: dict) -> str | None:
    gid = book['gutenberg_id']
    urls_to_try = [
        f"https://www.gutenberg.org/files/{gid}/{gid}-0.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}.txt",
        f"https://www.gutenberg.org/files/{gid}/{gid}-h/{gid}-h.htm",
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}-images.html",
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
    ]
    for url in urls_to_try:
        try:
            r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=60)
            if r.status_code == 200 and len(r.text) > 500:
                book['fetched_url'] = url
                if url.endswith('.txt'):
                    text = r.text
                    for m in ['*** START OF', '***START OF']:
                        idx = text.find(m)
                        if idx != -1:
                            nl = text.find('\n', idx)
                            text = text[nl+1:] if nl != -1 else text[idx+len(m):]
                            break
                    for m in ['*** END OF', '***END OF', 'End of the Project Gutenberg']:
                        idx = text.find(m)
                        if idx != -1:
                            text = text[:idx]
                            break
                    return text.strip()[:500000]
                else:
                    return clean_html(r.text)
        except Exception:
            continue
    return None


async def get_conn(pool: asyncpg.Pool) -> asyncpg.Connection:
    """Acquire a connection from pool with retry."""
    for attempt in range(MAX_RETRIES):
        try:
            return await pool.acquire()
        except Exception as e:
            log.warning(f"  DB acquire failed (attempt {attempt+1}): {e}")
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
    raise RuntimeError("Could not acquire DB connection after retries")


async def db_op_with_retry(pool: asyncpg.Pool, coro_factory):
    """Run a DB operation with auto-retry on connection errors.
    coro_factory(conn) should return the result."""
    for attempt in range(MAX_RETRIES):
        conn = None
        try:
            conn = await pool.acquire()
            result = await coro_factory(conn)
            return result
        except (asyncpg.ConnectionDoesNotExistError,
                asyncpg.InterfaceError,
                asyncpg.InternalClientError,
                OSError) as e:
            log.warning(f"  DB error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
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


async def insert_record(pool: asyncpg.Pool, title: str, culture: str,
                        url: str, ext_id: str, text: str):
    async def _do(conn):
        existing = await conn.fetchval(
            'SELECT id FROM source_records WHERE canonical_title = $1', title)
        if existing:
            return 'exists'

        existing2 = await conn.fetchval(
            'SELECT id FROM raw_objects WHERE external_id = $1', ext_id)
        if existing2:
            return 'exists'

        checksum = hashlib.sha256(text.encode()).hexdigest()
        byte_size = len(text.encode('utf-8'))
        r2_key = f'gutenberg/{ext_id}.txt'

        async with conn.transaction():
            ro_id = await conn.fetchval("""
                INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                         content_type, checksum, byte_size, r2_key, fetched_at)
                VALUES (gen_random_uuid(), $1, $2, $3, 'text/plain', $4, $5, $6, NOW())
                RETURNING id
            """, TS_ID, ext_id, url, checksum, byte_size, r2_key)

            sr_id = await conn.fetchval("""
                INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                            culture, source_category, provenance_status, record_status,
                                            created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, 'public_domain_library',
                        'verified', 'published', NOW(), NOW())
                RETURNING id
            """, ro_id, TS_ID, title, culture)

            await conn.execute("""
                INSERT INTO source_versions (id, source_record_id, version_type, language,
                                             is_preferred, text_extracted, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, 'translation', 'English', true, $2, NOW(), NOW())
            """, sr_id, text)

        return 'inserted'

    return await db_op_with_retry(pool, _do)


async def update_fts(pool: asyncpg.Pool):
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
    await db_op_with_retry(pool, _do)


def infer_culture(book: dict) -> str:
    subjects = (book.get('subjects', '') + ' ' + book.get('authors', '')).lower()
    if any(k in subjects for k in ['greek', 'greece', 'hellenic', 'athen', 'sparta']):
        return 'Greek'
    if any(k in subjects for k in ['roman', 'rome', 'latin', 'caesar']):
        return 'Roman'
    if any(k in subjects for k in ['egypt', 'egyptian', 'pharaoh']):
        return 'Egyptian'
    if any(k in subjects for k in ['babylonia', 'assyria', 'mesopotamia', 'sumerian', 'akkad']):
        return 'Mesopotamian'
    if any(k in subjects for k in ['india', 'vedic', 'hindu', 'buddhist', 'sanskrit']):
        return 'Indic'
    if any(k in subjects for k in ['norse', 'viking', 'scandinavian', 'iceland', 'teutonic']):
        return 'Norse'
    if any(k in subjects for k in ['celtic', 'irish', 'gaelic', 'druid', 'welsh']):
        return 'Celtic'
    if any(k in subjects for k in ['persian', 'zoroastr', 'avesta']):
        return 'Persian'
    if any(k in subjects for k in ['chinese', 'china', 'confucian', 'taoist']):
        return 'Chinese'
    if any(k in subjects for k in ['jewish', 'hebrew', 'talmud', 'biblical', 'israelite']):
        return 'Jewish/Hebrew'
    if any(k in subjects for k in ['byzantine', 'ottoman']):
        return 'Byzantine'
    return 'Ancient'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offset', type=int, default=0, help='Skip first N books')
    parser.add_argument('--limit', type=int, default=600, help='Max books to process')
    parser.add_argument('--dry-run', action='store_true', help='Fetch but do not insert')
    args = parser.parse_args()

    catalog_path = Path(__file__).parent / 'gutenberg_ancient_list.json'
    if not catalog_path.exists():
        log.error(f"Catalog not found: {catalog_path}")
        sys.exit(1)

    with open(catalog_path) as f:
        books = json.load(f)

    books = books[args.offset:args.offset + args.limit]
    log.info(f"Processing {len(books)} books (offset={args.offset}, limit={args.limit})")

    pool = await asyncpg.create_pool(
        DB_URL,
        min_size=1, max_size=3,
        command_timeout=120,
        server_settings={'statement_timeout': '120000'},
    )

    async with httpx.AsyncClient(timeout=90) as client:
        inserted = 0
        skipped = 0
        failed = 0

        for i, book in enumerate(books, 1):
            gid = book['gutenberg_id']
            raw_title = book['title'][:200]

            if re.search(
                r'\b(Plato|Aristotle|Cicero|Caesar|Virgil|Homer|Herodotus|Thucydides|'
                r'Xenophon|Pliny|Plutarch|Tacitus|Suetonius|Livy|Ovid|Horace|Seneca|'
                r'Aeschylus|Sophocles|Euripides)\b',
                book.get('authors', ''), re.IGNORECASE
            ):
                m = re.search(r'^([^,]+)', book['authors'])
                title = f"{m.group(1).strip()} - {raw_title}" if m else raw_title
            else:
                title = raw_title

            ext_id = f'pg-{gid}'
            culture = infer_culture(book)

            log.info(f"[{i}/{len(books)}] #{gid}: {title[:80]}")

            try:
                async def _check_exists(conn):
                    r1 = await conn.fetchval(
                        'SELECT id FROM source_records WHERE canonical_title = $1', title)
                    if r1:
                        return True
                    r2 = await conn.fetchval(
                        'SELECT id FROM raw_objects WHERE external_id = $1', ext_id)
                    return bool(r2)
                if await db_op_with_retry(pool, _check_exists):
                    log.info(f"  SKIP (already in DB)")
                    skipped += 1
                    continue
            except Exception as e:
                log.warning(f"  Existence check failed: {e}")

            if args.dry_run:
                log.info(f"  DRY RUN")
                continue

            try:
                text = await fetch_text(client, book)
            except Exception as e:
                log.warning(f"  FETCH ERROR: {e}")
                text = None

            if not text or len(text) < 300:
                log.warning(f"  FAIL (too short or empty)")
                failed += 1
                await asyncio.sleep(SLEEP_BETWEEN)
                continue

            try:
                result = await insert_record(
                    pool, title, culture,
                    book.get('fetched_url', book.get('txt_url', '')),
                    ext_id, text
                )
                if result == 'inserted':
                    log.info(f"  OK ({len(text):,} chars)")
                    inserted += 1
                else:
                    log.info(f"  SKIP (exists after fetch)")
                    skipped += 1
            except Exception as e:
                log.error(f"  INSERT ERROR: {e}")
                failed += 1

            await asyncio.sleep(SLEEP_BETWEEN)

            if i % 25 == 0:
                try:
                    await update_fts(pool)
                    log.info(f"  --- FTS updated, {inserted} inserted so far ---")
                except Exception as e:
                    log.warning(f"  FTS update failed (non-fatal): {e}")

    try:
        await update_fts(pool)
    except Exception as e:
        log.warning(f"Final FTS update failed: {e}")

    await pool.close()
    log.info(f"\n=== Done: {inserted} inserted, {skipped} skipped, {failed} failed ===")


asyncio.run(main())
