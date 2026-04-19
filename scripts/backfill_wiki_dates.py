#!/usr/bin/env python3
"""
Backfill source_dates for Wikipedia records by extracting BCE dates from text.

Looks for patterns like:
  "3200 BCE", "ca. 2500 BC", "circa 1200–800 BCE", "around 500 BC"
  "fl. 450 BC", "died 323 BC", "born c. 384 BC"
  "the Xth century BC", "4th millennium BC"

Inserts the earliest and latest BCE years found as a single source_date range.
"""
import asyncio
import asyncpg
import re
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_DSN = "postgresql://eden:eden@postgres:5432/eden"

# Match individual BCE years like "3200 BC", "ca. 450 BCE", "c.1200 BC"
BCE_YEAR_RE = re.compile(
    r"(?:ca\.?|c\.?|circa|around|approximately|fl\.?|died?|born?|d\.?|b\.?)?"
    r"\s*(\d{1,4})\s*(?:–|-|to|or)\s*(\d{1,4})\s*B\.?C\.?E?\.?\b"  # range: 3200–2800 BC
    r"|"
    r"(?:ca\.?|c\.?|circa|around|approximately|fl\.?|died?|born?|d\.?|b\.?)?"
    r"\s*(\d{1,4})\s*B\.?C\.?E?\.?\b",  # single: 3200 BC
    re.IGNORECASE,
)

# Match "Nth century BC" -> convert to year range
CENTURY_BCE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)\s+century\s+B\.?C\.?E?\.?\b",
    re.IGNORECASE,
)

# Match "Nth millennium BC" -> convert to year range
MILLENNIUM_BCE_RE = re.compile(
    r"(\d)\s+(?:st|nd|rd|th)\s+millennium\s+B\.?C\.?E?\.?\b",
    re.IGNORECASE,
)


def extract_bce_years(text: str) -> list[int]:
    """Return all BCE year values found in text as negative integers (e.g. -450 for 450 BC)."""
    if not text:
        return []

    years: list[int] = []
    check = text[:5000]  # only scan first 5000 chars

    for m in BCE_YEAR_RE.finditer(check):
        if m.group(1) and m.group(2):
            # range match
            y1, y2 = int(m.group(1)), int(m.group(2))
            if 1 <= y1 <= 10000 and 1 <= y2 <= 10000:
                years.extend([-y1, -y2])
        elif m.group(3):
            y = int(m.group(3))
            if 1 <= y <= 10000:
                years.append(-y)

    for m in CENTURY_BCE_RE.finditer(check):
        c = int(m.group(1))
        if 1 <= c <= 100:
            years.extend([-(c * 100), -((c - 1) * 100 + 1)])

    for m in MILLENNIUM_BCE_RE.finditer(check):
        mil = int(m.group(1))
        if 1 <= mil <= 10:
            years.extend([-(mil * 1000), -((mil - 1) * 1000 + 1)])

    return years


async def main():
    conn = await asyncpg.connect(DB_DSN)
    log.info("Connected to DB")

    rows = await conn.fetch("""
        SELECT sr.id, LEFT(sv.text_extracted, 5000) as text
        FROM source_records sr
        JOIN trusted_sources ts ON ts.id = sr.trusted_source_id
        LEFT JOIN source_versions sv ON sv.source_record_id = sr.id
        LEFT JOIN source_dates sd ON sd.source_record_id = sr.id
        WHERE ts.slug = 'wikipedia-ancient'
        AND sv.text_extracted IS NOT NULL
        AND sd.id IS NULL
    """)
    log.info(f"Processing {len(rows)} wiki records without dates")

    inserts = []
    for row in rows:
        years = extract_bce_years(row["text"] or "")
        if not years:
            continue
        start = min(years)  # earliest (most negative = oldest)
        end = max(years)    # latest (least negative = most recent)
        inserts.append((row["id"], start, end))

    log.info(f"Found extractable dates for {len(inserts)} records")

    # Batch insert
    batch_size = 500
    total = 0
    for i in range(0, len(inserts), batch_size):
        batch = inserts[i:i + batch_size]
        async with conn.transaction():
            await conn.executemany("""
                INSERT INTO source_dates
                  (source_record_id, date_type, date_start, date_end,
                   date_label, dating_method, dating_confidence)
                VALUES ($1, 'composition'::date_type, $2, $3,
                        'Extracted from article text', 'text_analysis', 'approximate'::dating_confidence)
                ON CONFLICT DO NOTHING
            """, batch)
        total += len(batch)
        if total % 2000 == 0:
            log.info(f"  Inserted {total} so far...")

    log.info(f"Done! Inserted dates for {total} wiki records")
    await conn.close()


asyncio.run(main())
