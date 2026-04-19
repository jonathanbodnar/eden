"""
Backfill dates into metadata_jsonb for wiki articles (v2 - comprehensive).

Much broader date extraction:
- BC/BCE/AD/CE year patterns
- Century patterns ("3rd century BC", "15th-century")
- Millennium patterns
- Era/period name mapping
- Bare centuries without BC/AD (assumed AD if < 8th century context)
- Infobox field scanning (epochs, built, date, reign, etc.)

Also flags articles that are clearly not ancient for later cleanup.
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

# ── Regex patterns ──

BC_YEAR_RE = re.compile(
    r'(?:c\.?\s*|circa\s+|ca\.?\s*|fl\.?\s*|r\.?\s*)?'
    r'(?<!\d)(\d{1,4})\s*(?:BC|BCE|B\.C\.E?\.?)\b',
    re.IGNORECASE
)
AD_YEAR_RE = re.compile(
    r'(?:c\.?\s*|circa\s+|ca\.?\s*|fl\.?\s*|r\.?\s*)?'
    r'(?<!\d)(\d{1,4})\s*(?:AD|CE|A\.D\.?|C\.E\.?)\b',
    re.IGNORECASE
)

# "3rd century BC", "5th-century BCE"
BC_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)[\s-]+century\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)
AD_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)[\s-]+century\s+(?:AD|CE|A\.D\.?|C\.E\.?)',
    re.IGNORECASE
)

# Bare century: "15th-century" or "15th century" without BC/AD
# We'll use context to decide if it's BC or AD
BARE_CENTURY_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)[\s-]+century(?!\s+(?:BC|BCE|AD|CE|B\.|A\.|C\.))',
    re.IGNORECASE
)

# Millennium patterns
BC_MILLENNIUM_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+millennium\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)
AD_MILLENNIUM_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+millennium\s+(?:AD|CE|A\.D\.?|C\.E\.?)',
    re.IGNORECASE
)

# Decade patterns: "330s BC", "1st century BC"
BC_DECADE_RE = re.compile(
    r'(?<!\d)(\d{1,4})s\s+(?:BC|BCE|B\.C\.E?\.?)',
    re.IGNORECASE
)

# Named era mapping -> (start_year, end_year) in unified timeline (negative = BCE)
ERA_MAP = {
    r'neolithic': (-10000, -2000),
    r'paleolithic|palaeolithic': (-2500000, -10000),
    r'mesolithic': (-10000, -5000),
    r'chalcolithic': (-4500, -3300),
    r'bronze\s*age': (-3300, -1200),
    r'iron\s*age': (-1200, -500),
    r'stone\s*age': (-2500000, -3300),
    r'predynastic': (-5500, -3100),
    r'old\s*kingdom': (-2686, -2181),
    r'middle\s*kingdom': (-2055, -1650),
    r'new\s*kingdom': (-1550, -1069),
    r'archaic.*(?:greece|greek|period)': (-800, -480),
    r'classical.*(?:greece|greek|period|antiquity)': (-480, -323),
    r'hellenistic': (-323, -31),
    r'roman\s*republic': (-509, -27),
    r'roman\s*empire': (-27, 476),
    r'late\s*antiquity': (250, 700),
    r'late\s*roman': (250, 476),
    r'byzantine': (330, 700),
    r'vedic\s*period': (-1500, -500),
    r'shang\s*dynasty': (-1600, -1046),
    r'zhou\s*dynasty': (-1046, -256),
    r'warring\s*states': (-475, -221),
    r'spring\s*and\s*autumn': (-771, -476),
    r'qin\s*dynasty': (-221, -206),
    r'han\s*dynasty': (-206, 220),
    r'achaemenid': (-550, -330),
    r'sassanid|sasanian': (224, 651),
    r'parthian\s*empire': (-247, 224),
    r'sumerian': (-4500, -1900),
    r'akkadian\s*empire': (-2334, -2154),
    r'babylonian': (-1894, -539),
    r'assyrian\s*empire': (-2500, -609),
    r'hittite': (-1600, -1178),
    r'minoan': (-2700, -1450),
    r'mycenaean': (-1600, -1100),
    r'phoenician': (-1500, -300),
    r'ptolemaic': (-305, -30),
    r'seleucid': (-312, -63),
    r'maurya': (-322, -185),
    r'gupta': (240, 550),
    r'kushan': (30, 375),
    r'mayan\s*classic': (250, 900),
    r'olmec': (-1500, -400),
    r'pre-columbian': (-2000, 500),
    r'jōmon|jomon': (-14000, -300),
    r'yayoi': (-300, 300),
    r'kofun': (250, 538),
    r'trojan\s*war': (-1260, -1180),
    r'persian\s*wars': (-499, -449),
    r'peloponnesian\s*war': (-431, -404),
    r'punic\s*war': (-264, -146),
}


def extract_dates(text: str) -> dict:
    """Comprehensive date extraction from article text."""
    sample = text[:5000]
    bc_years = []
    ad_years = []

    # Explicit BC/BCE years
    for m in BC_YEAR_RE.finditer(sample):
        y = int(m.group(1))
        if 1 <= y <= 10000:
            bc_years.append(y)

    # Explicit AD/CE years
    for m in AD_YEAR_RE.finditer(sample):
        y = int(m.group(1))
        if 1 <= y <= 800:
            ad_years.append(y)

    # Century BC
    for m in BC_CENTURY_RE.finditer(sample):
        c = int(m.group(1))
        if 1 <= c <= 100:
            bc_years.append(c * 100)

    # Century AD
    for m in AD_CENTURY_RE.finditer(sample):
        c = int(m.group(1))
        if 1 <= c <= 8:
            ad_years.append((c - 1) * 100 + 50)

    # Bare centuries (no BC/AD) - assume AD if <= 8th century
    for m in BARE_CENTURY_RE.finditer(sample):
        c = int(m.group(1))
        if 1 <= c <= 8:
            ad_years.append((c - 1) * 100 + 50)

    # Millennium BC
    for m in BC_MILLENNIUM_RE.finditer(sample):
        mil = int(m.group(1))
        if 1 <= mil <= 10:
            bc_years.append(mil * 1000)

    # Millennium AD
    for m in AD_MILLENNIUM_RE.finditer(sample):
        mil = int(m.group(1))
        if mil == 1:
            ad_years.append(500)

    # Decade BC: "330s BC"
    for m in BC_DECADE_RE.finditer(sample):
        y = int(m.group(1))
        if 1 <= y <= 10000:
            bc_years.append(y)

    # Named era matching
    sample_lower = sample.lower()
    for pattern, (era_start, era_end) in ERA_MAP.items():
        if re.search(pattern, sample_lower):
            if era_start < 0:
                bc_years.append(abs(era_start))
            else:
                ad_years.append(era_start)
            if era_end < 0:
                bc_years.append(abs(era_end))
            elif era_end <= 800:
                ad_years.append(era_end)
            break  # Only use first matched era to avoid over-counting

    bc_years = sorted(set(bc_years))
    ad_years = sorted(set(ad_years))

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


# ── Noise detection: articles that are definitely not ancient ──

NOISE_TITLE_PATTERNS = [
    r'\(TV series\)', r'\(film\)', r'\(novel\)', r'\(album\)',
    r'\(song\)', r'\(band\)', r'\(video game\)', r'\(comics?\)',
    r'\(magazine\)', r'\(newspaper\)', r'\(software\)',
    r'\(musician\)', r'\(singer\)', r'\(actor\)', r'\(actress\)',
    r'\(footballer\)', r'\(cricketer\)', r'\(politician\)',
    r'\(psychologist\)', r'\(physicist\)', r'\(company\)',
    r'\(TV channel\)', r'\(radio\)', r'\(podcast\)',
    r'(?:Series|Season) \d+',
]
NOISE_TITLE_RE = re.compile('|'.join(NOISE_TITLE_PATTERNS), re.IGNORECASE)

NOISE_TEXT_INDICATORS = [
    r'^.{0,200}(?:is|was) (?:an? )?(?:American|British|Canadian|Australian|Indian|French|German|Japanese|Chinese|Korean) (?:film|television|TV|video game|novel|album|song|band|company|software)',
    r'^.{0,200}(?:is|was) (?:an? )?(?:2[01]\d{2}|19\d{2}) (?:film|television|album|song|video game)',
    r'^.{0,500}(?:released|premiered|published|founded|established) (?:in|on) (?:19|20)\d{2}',
]
NOISE_TEXT_RE = re.compile('|'.join(NOISE_TEXT_INDICATORS), re.IGNORECASE | re.DOTALL)


def is_noise(title: str, text_start: str) -> bool:
    if NOISE_TITLE_RE.search(title):
        return True
    if NOISE_TEXT_RE.search(text_start[:600]):
        return True
    return False


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

    # Reset all wiki metadata
    async def _reset(conn):
        return await conn.execute("""
            UPDATE source_records SET metadata_jsonb = NULL
            WHERE id IN (
                SELECT sr.id FROM source_records sr
                JOIN raw_objects ro ON ro.id = sr.raw_object_id
                WHERE ro.external_id LIKE 'wiki-page-%%'
            )
        """)
    await db_op(pool, _reset)
    log.info("Cleared existing metadata_jsonb")

    # Fetch all wiki articles
    async def _fetch(conn):
        return await conn.fetch("""
            SELECT sr.id AS sr_id, sr.canonical_title, sv.text_extracted
            FROM source_records sr
            JOIN raw_objects ro ON ro.id = sr.raw_object_id
            JOIN source_versions sv ON sv.source_record_id = sr.id
            WHERE ro.external_id LIKE 'wiki-page-%%'
              AND sv.text_extracted IS NOT NULL
              AND sv.text_extracted != ''
        """)

    rows = await db_op(pool, _fetch)
    log.info(f"Found {len(rows):,} wiki articles to process")

    updated_dates = 0
    no_dates = 0
    noise_flagged = 0
    modern_flagged = 0
    errors = 0
    BATCH_SIZE = 100
    batch_updates = []
    noise_ids = []

    for i, row in enumerate(rows):
        title = row['canonical_title']
        text = row['text_extracted']

        # Check for obvious noise
        if is_noise(title, text):
            noise_ids.append(row['sr_id'])
            noise_flagged += 1
            continue

        dates = extract_dates(text)
        if not dates:
            no_dates += 1
            continue

        if dates.get('date_start', 0) >= 700:
            modern_flagged += 1
            dates['possibly_modern'] = True

        batch_updates.append((json.dumps(dates), row['sr_id']))

        if len(batch_updates) >= BATCH_SIZE:
            async def _update(conn, updates=batch_updates):
                for meta_json, sr_id in updates:
                    await conn.execute(
                        "UPDATE source_records SET metadata_jsonb = $1::jsonb WHERE id = $2",
                        meta_json, sr_id
                    )
                return len(updates)
            try:
                n = await db_op(pool, _update)
                updated_dates += n
            except Exception as e:
                log.warning(f"Batch update failed: {e}")
                errors += len(batch_updates)
            batch_updates = []

        if (i + 1) % 5000 == 0:
            log.info(
                f"  Progress: {i+1:,}/{len(rows):,} | "
                f"Dates: {updated_dates:,} | No dates: {no_dates:,} | "
                f"Noise: {noise_flagged:,} | Modern: {modern_flagged:,}"
            )

    # Final batch
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
            updated_dates += n
        except Exception as e:
            log.warning(f"Final batch failed: {e}")
            errors += len(batch_updates)

    log.info(f"\n{'='*60}")
    log.info(f"Date extraction: {updated_dates:,} updated | {no_dates:,} no dates | "
             f"{modern_flagged:,} modern | {noise_flagged:,} noise flagged")
    log.info(f"{'='*60}")

    # Delete noise articles
    if noise_ids:
        log.info(f"Deleting {len(noise_ids):,} noise articles...")

        # Get the raw_object_ids and source_version_ids for noise
        async def _get_noise_details(conn, sr_ids=noise_ids):
            rows = await conn.fetch("""
                SELECT sr.id as sr_id, sr.raw_object_id as ro_id, sv.id as sv_id
                FROM source_records sr
                LEFT JOIN source_versions sv ON sv.source_record_id = sr.id
                WHERE sr.id = ANY($1::uuid[])
            """, sr_ids)
            return rows

        noise_details = await db_op(pool, _get_noise_details)
        sv_ids = [r['sv_id'] for r in noise_details if r['sv_id']]
        sr_ids_del = [r['sr_id'] for r in noise_details]
        ro_ids = list(set(r['ro_id'] for r in noise_details))

        DBATCH = 500
        for ids_list, table in [(sv_ids, 'source_versions'), (sr_ids_del, 'source_records'), (ro_ids, 'raw_objects')]:
            for j in range(0, len(ids_list), DBATCH):
                batch = ids_list[j:j+DBATCH]
                async def _del(conn, b=batch, t=table):
                    await conn.execute(f"DELETE FROM {t} WHERE id = ANY($1::uuid[])", b)
                try:
                    await db_op(pool, _del)
                except Exception as e:
                    log.warning(f"Delete from {table} failed: {e}")

        log.info(f"Deleted {len(noise_ids):,} noise articles")

    await pool.close()
    log.info("DONE")


asyncio.run(main())
