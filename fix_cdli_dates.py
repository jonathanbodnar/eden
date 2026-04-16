#!/usr/bin/env python3
"""Assign ancient dates to undated CDLI records based on period metadata."""
import asyncio
import re
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CDLI_PERIOD_MAP = {
    "Middle Hittite": (-1400, -1180, "Middle Hittite"),
    "Ebla": (-2500, -2250, "Ebla"),
    "Uruk III (ca. 3200-3000 BC)": (-3200, -3000, "Uruk III"),
    "Uruk IV (ca. 3350-3200 BC)": (-3350, -3200, "Uruk IV"),
    "ED I-II": (-2900, -2600, "Early Dynastic I-II"),
    "Neo-Elamite": (-770, -539, "Neo-Elamite"),
    "Middle Elamite": (-1500, -1100, "Middle Elamite"),
    "Pre-Writing (ca. 8500-3500 BC)": (-8500, -3500, "Pre-Writing"),
    "Uruk V (ca. 3500-3350 BC)": (-3500, -3350, "Uruk V"),
    "Egyptian 0": (-3500, -3100, "Predynastic Egypt"),
    "Sassanian": (224, 651, "Sassanian"),
    "Linear Elamite": (-2300, -2100, "Linear Elamite"),
    "Proto-Elamite": (-3100, -2700, "Proto-Elamite"),
    "Early Neo-Babylonian": (-1000, -626, "Early Neo-Babylonian"),
    "Old Elamite": (-2700, -1500, "Old Elamite"),
    "Harappan": (-3300, -1300, "Harappan"),
    "Neo-Babylonian": (-626, -539, "Neo-Babylonian"),
    "Neo-Assyrian": (-911, -609, "Neo-Assyrian"),
    "Old Akkadian": (-2334, -2154, "Old Akkadian"),
    "ED IIIa": (-2600, -2500, "Early Dynastic IIIa"),
    "ED IIIb": (-2500, -2340, "Early Dynastic IIIb"),
    "Old Babylonian": (-2000, -1600, "Old Babylonian"),
    "Ur III": (-2112, -2004, "Ur III"),
    "Old Assyrian": (-2025, -1750, "Old Assyrian"),
    "Middle Assyrian": (-1392, -934, "Middle Assyrian"),
    "Achaemenid": (-550, -330, "Achaemenid"),
    "Seleucid": (-312, -63, "Seleucid"),
    "Lagash II": (-2144, -2124, "Lagash II"),
    "Middle Babylonian": (-1595, -1000, "Middle Babylonian"),
}

DEFAULT_CUNEIFORM = (-3400, -75, "Cuneiform Era")


async def main():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL", "postgresql://eden:eden@postgres:5432/eden")
    conn = await asyncpg.connect(dsn)

    cdli_id = 'bb45f74d-163b-4ee8-9eb6-52fba63e9360'
    cdli_id_result = await conn.fetchval(
        "SELECT id FROM trusted_sources WHERE slug = 'cdli'"
    )

    batch_size = 1000
    offset = 0
    total_dated = 0
    total_modern_removed = 0

    while True:
        rows = await conn.fetch("""
            SELECT sr.id, sr.metadata_jsonb->>'period' as period
            FROM source_records sr
            WHERE sr.trusted_source_id = $1
            AND NOT EXISTS (SELECT 1 FROM source_dates sd WHERE sd.source_record_id = sr.id)
            ORDER BY sr.id
            LIMIT $2 OFFSET $3
        """, cdli_id_result, batch_size, offset)

        if not rows:
            break

        for row in rows:
            period = (row['period'] or "").strip()

            if period.lower() == "modern":
                total_modern_removed += 1
                continue

            if period in CDLI_PERIOD_MAP:
                start, end, label = CDLI_PERIOD_MAP[period]
            elif period:
                m = re.search(r'(\d{3,5})\s*[-–]\s*(\d{3,5})\s*BC', period)
                if m:
                    start = -int(m.group(1))
                    end = -int(m.group(2))
                    label = period.split('(')[0].strip()
                else:
                    start, end, label = DEFAULT_CUNEIFORM
            else:
                start, end, label = DEFAULT_CUNEIFORM

            await conn.execute("""
                INSERT INTO source_dates (id, source_record_id, date_type, date_start, date_end, date_label, dating_confidence)
                VALUES (gen_random_uuid(), $1, 'composition', $2, $3, $4, 'approximate')
            """, row['id'], start, end, f"ca. {label}")
            total_dated += 1

        offset += batch_size
        if offset % 10000 == 0:
            logger.info("Processed %d: %d dated, %d modern", offset, total_dated, total_modern_removed)

    logger.info("DONE: %d given dates, %d modern skipped", total_dated, total_modern_removed)
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
