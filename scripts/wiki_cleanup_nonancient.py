"""
Scan already-imported Wikipedia articles and remove non-ancient ones.

Loads the tight filter (v5) and compares against what's in the DB.
Any wiki-page-* record whose page_id is NOT in the tight filter gets deleted.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import asyncpg

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://eden:eden@127.0.0.1:5432/eden'
DUMP_DIR = '/opt/wiki-dump'


async def main():
    filter_path = Path(DUMP_DIR) / "ancient_page_ids_v5.json"
    if not filter_path.exists():
        log.error("ancient_page_ids_v5.json not found -- run v5 filter first")
        sys.exit(1)

    with open(str(filter_path)) as f:
        filter_data = json.load(f)

    allowed_ids = set(filter_data["page_ids"])
    log.info(f"Tight filter: {len(allowed_ids):,} allowed page IDs")

    conn = await asyncpg.connect(DB_URL)

    # Get all wiki-page-* external_ids from raw_objects
    rows = await conn.fetch("""
        SELECT ro.id AS ro_id, ro.external_id,
               sr.id AS sr_id, sv.id AS sv_id
        FROM raw_objects ro
        LEFT JOIN source_records sr ON sr.raw_object_id = ro.id
        LEFT JOIN source_versions sv ON sv.source_record_id = sr.id
        WHERE ro.external_id LIKE 'wiki-page-%'
    """)
    log.info(f"Found {len(rows):,} wiki-page records in DB")

    to_delete_ro = []
    to_delete_sr = []
    to_delete_sv = []
    kept = 0

    for row in rows:
        ext_id = row['external_id']
        # Extract page_id from "wiki-page-12345"
        try:
            page_id = int(ext_id.replace('wiki-page-', ''))
        except ValueError:
            continue

        if page_id in allowed_ids:
            kept += 1
        else:
            if row['sv_id']:
                to_delete_sv.append(row['sv_id'])
            if row['sr_id']:
                to_delete_sr.append(row['sr_id'])
            to_delete_ro.append(row['ro_id'])

    log.info(f"Keep: {kept:,} | Delete: {len(to_delete_ro):,}")

    if not to_delete_ro:
        log.info("Nothing to delete!")
        await conn.close()
        return

    # Delete in order: source_versions -> source_records -> raw_objects
    BATCH = 500
    log.info(f"Deleting {len(to_delete_sv):,} source_versions...")
    for i in range(0, len(to_delete_sv), BATCH):
        batch = to_delete_sv[i:i+BATCH]
        await conn.execute(
            "DELETE FROM source_versions WHERE id = ANY($1::uuid[])",
            batch
        )
        if (i // BATCH) % 20 == 0:
            log.info(f"  sv: {i+len(batch):,}/{len(to_delete_sv):,}")

    log.info(f"Deleting {len(to_delete_sr):,} source_records...")
    for i in range(0, len(to_delete_sr), BATCH):
        batch = to_delete_sr[i:i+BATCH]
        await conn.execute(
            "DELETE FROM source_records WHERE id = ANY($1::uuid[])",
            batch
        )
        if (i // BATCH) % 20 == 0:
            log.info(f"  sr: {i+len(batch):,}/{len(to_delete_sr):,}")

    log.info(f"Deleting {len(to_delete_ro):,} raw_objects...")
    for i in range(0, len(to_delete_ro), BATCH):
        batch = to_delete_ro[i:i+BATCH]
        await conn.execute(
            "DELETE FROM raw_objects WHERE id = ANY($1::uuid[])",
            batch
        )
        if (i // BATCH) % 20 == 0:
            log.info(f"  ro: {i+len(batch):,}/{len(to_delete_ro):,}")

    log.info(f"DONE: Deleted {len(to_delete_ro):,} non-ancient wiki records, kept {kept:,}")
    await conn.close()


asyncio.run(main())
