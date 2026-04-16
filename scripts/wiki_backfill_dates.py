"""
Backfill dates into metadata_jsonb for already-imported wiki articles.

Reads article text from source_versions, extracts dates,
updates metadata_jsonb on source_records.
Uses connection pool with retry for resilience.
"""
import asyncio
import json
import logging
import re
import sys

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

DB_URL = 'postgresql://eden:eden@127.0.0.1:5432/eden'
MAX_RETRIES = 5
RETRY_BACKOFF = 3

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
BC_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+century\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)
AD_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+century\s+(?:AD|CE|A\.D\.?|C\.E\.?)',
    re.IGNORECASE
)
BC_MILLENNIUM_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+millennium\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)


def extract_dates(text: str) -> dict:
    sample = text[:3000]
    bc_years = []
    ad_years = []

    for ym in BC_YEAR_RE.finditer(sample):
        bc_years.append(int(ym.group(1)))
    for ym in AD_YEAR_RE.finditer(sample):
        ad_years.append(int(ym.group(1)))
    for cm in BC_CENTURY_RE.finditer(sample):
        bc_years.append(int(cm.group(1)) * 100)
    for cm in AD_CENTURY_RE.finditer(sample):
        ad_years.append((int(cm.group(1)) - 1) * 100 + 50)
    for mm in BC_MILLENNIUM_RE.finditer(sample):
        bc_years.append(int(mm.group(1)) * 1000)

    bc_years = [y for y in bc_years if 1 <= y <= 10000]
    ad_years = [y for y in ad_years if 1 <= y <= 800]
    all_years = [-y for y in bc_years] + ad_years

    if not all_years:
        return {}

    date_start = min(all_years)
    date_end = max(all_years)

    parts = []
    if bc_years:
        parts.append(f"{max(bc_years)} BC")
    if ad_years:
        parts.append(f"{min(ad_years)} AD")
    date_text = " – ".join(parts) if len(parts) > 1 else parts[0] if parts else ""

    return {"date_start": date_start, "date_end": date_end, "date_text": date_text}


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


async def main():
    pool = await asyncpg.create_pool(
        DB_URL, min_size=1, max_size=3,
        command_timeout=120,
        server_settings={'statement_timeout': '120000'},
    )

    # First, clear any previously-extracted (possibly bad) dates
    async def _reset_dates(conn):
        return await conn.execute("""
            UPDATE source_records SET metadata_jsonb = NULL
            WHERE id IN (
                SELECT sr.id FROM source_records sr
                JOIN raw_objects ro ON ro.id = sr.raw_object_id
                WHERE ro.external_id LIKE 'wiki-page-%%'
            )
        """)
    await db_op(pool, _reset_dates)
    log.info("Cleared existing metadata_jsonb for wiki articles")

    async def _fetch_rows(conn):
        return await conn.fetch("""
            SELECT sr.id AS sr_id, sv.text_extracted
            FROM source_records sr
            JOIN raw_objects ro ON ro.id = sr.raw_object_id
            JOIN source_versions sv ON sv.source_record_id = sr.id
            WHERE ro.external_id LIKE 'wiki-page-%%'
              AND sv.text_extracted IS NOT NULL
              AND sv.text_extracted != ''
        """)

    rows = await db_op(pool, _fetch_rows)
    log.info(f"Found {len(rows):,} wiki articles needing date backfill")

    updated = 0
    no_dates = 0
    modern = 0
    errors = 0

    BATCH_SIZE = 100
    batch_updates = []

    for i, row in enumerate(rows):
        dates = extract_dates(row['text_extracted'])
        if not dates:
            no_dates += 1
            continue

        if dates.get('date_start', 0) >= 700:
            modern += 1

        batch_updates.append((json.dumps(dates), row['sr_id']))

        if len(batch_updates) >= BATCH_SIZE:
            async def _update_batch(conn, updates=batch_updates):
                for meta_json, sr_id in updates:
                    await conn.execute(
                        "UPDATE source_records SET metadata_jsonb = $1::jsonb WHERE id = $2",
                        meta_json, sr_id
                    )
                return len(updates)

            try:
                n = await db_op(pool, _update_batch)
                updated += n
            except Exception as e:
                log.warning(f"Batch update failed: {e}")
                errors += len(batch_updates)
            batch_updates = []

        if (i + 1) % 5000 == 0:
            log.info(f"  Progress: {i+1:,}/{len(rows):,} | Updated: {updated:,} | No dates: {no_dates:,} | Modern(>=700CE): {modern:,} | Errors: {errors:,}")

    if batch_updates:
        async def _update_final(conn, updates=batch_updates):
            for meta_json, sr_id in updates:
                await conn.execute(
                    "UPDATE source_records SET metadata_jsonb = $1::jsonb WHERE id = $2",
                    meta_json, sr_id
                )
            return len(updates)

        try:
            n = await db_op(pool, _update_final)
            updated += n
        except Exception as e:
            log.warning(f"Final batch update failed: {e}")
            errors += len(batch_updates)

    await pool.close()
    log.info(f"DONE: Updated {updated:,} | No dates: {no_dates:,} | Modern(>=700CE): {modern:,} | Errors: {errors:,} | Total: {len(rows):,}")


asyncio.run(main())
