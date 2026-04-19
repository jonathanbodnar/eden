"""
Assign dated source_records to canonical epochs and create chapter_source_sets.

For each dated source_record (via source_dates or metadata_jsonb):
1. Determine which epoch it belongs to by date range
2. Find or create a chapter in that epoch for the record's culture/time-slice
3. Create chapter_source_set links

Uses asyncpg with connection pool and retry for resilience.
"""
import asyncio
import json
import logging
import sys
import uuid
from collections import defaultdict

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

EPOCHS = [
    # (epoch_id, title, time_start, time_end)
    ("de92c596-fa7c-4c7d-a61f-bbabe76dfadf", "Dawn of Civilization", -12000, -5000),
    ("a0fa0b4c-2a1f-4100-baa1-defb83d314e2", "Rise of the First Cities", -5000, -3000),
    ("6bc14b2f-7cf9-4702-9f70-bc8ee8954dd5", "Age of Empires", -3000, -2000),
    ("3da54d89-d636-437f-9fbc-5547dbf39fcc", "Age of Heroes", -2000, -1200),
    ("5a5f3709-6f35-45e7-a10b-df4fdb31cc5b", "Age of Iron and Prophets", -1200, -500),
    ("8cd6d5af-e3e3-47f1-99e7-0206177f4ff9", "The Classical World", -500, 100),
]

CULTURE_NORMALIZE = {
    'egyptian': 'Egyptian',
    'greek': 'Greek',
    'roman': 'Roman',
    'mesopotamian': 'Mesopotamian',
    'indic': 'Indic',
    'chinese': 'Chinese',
    'persian': 'Persian',
    'norse': 'Norse',
    'celtic': 'Celtic',
    'mesoamerican': 'Mesoamerican',
    'jewish/hebrew': 'Jewish/Hebrew',
    'phoenician': 'Phoenician',
    'ancient': 'General',
}


def normalize_culture(raw: str) -> str:
    low = raw.lower().strip()
    for key, label in CULTURE_NORMALIZE.items():
        if key in low:
            return label
    if len(raw) > 40:
        return 'General'
    return raw[:40]


def find_epoch(date_start: int) -> tuple[str, str] | None:
    for eid, title, ts, te in EPOCHS:
        if ts <= date_start < te:
            return (eid, title)
    if date_start < -12000:
        return (EPOCHS[0][0], EPOCHS[0][1])
    if date_start >= 100:
        return None
    return None


def get_slice_size(epoch_start: int) -> int:
    if epoch_start <= -5000:
        return 2000
    if epoch_start <= -2000:
        return 500
    return 250


def make_time_slice(date_start: int, epoch_start: int, epoch_end: int) -> tuple[int, int, str]:
    sz = get_slice_size(epoch_start)
    slice_start = max(epoch_start, (date_start // sz) * sz)
    slice_end = min(epoch_end, slice_start + sz)
    if slice_start < 0 and slice_end <= 0:
        label = f"{abs(slice_start)}-{abs(slice_end)} BCE"
    elif slice_start < 0:
        label = f"{abs(slice_start)} BCE - {slice_end} CE"
    else:
        label = f"{slice_start}-{slice_end} CE"
    return slice_start, slice_end, label


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

    # Phase 1: Collect all dated source_records
    log.info("Phase 1: Collecting dated source_records...")

    async def _get_metadata_dated(conn):
        return await conn.fetch("""
            SELECT sr.id, sr.canonical_title, sr.culture,
                   (sr.metadata_jsonb->>'date_start')::int as date_start,
                   (sr.metadata_jsonb->>'date_end')::int as date_end
            FROM source_records sr
            WHERE sr.metadata_jsonb IS NOT NULL
              AND sr.metadata_jsonb->>'date_start' IS NOT NULL
        """)

    meta_rows = await db_op(pool, _get_metadata_dated)
    log.info(f"  metadata_jsonb dated: {len(meta_rows):,}")

    # source_dates — fetch in batches to avoid crashing
    async def _get_source_dated(conn):
        return await conn.fetch("""
            SELECT DISTINCT ON (sd.source_record_id)
                   sd.source_record_id as id,
                   sr.canonical_title, sr.culture,
                   sd.date_start, sd.date_end
            FROM source_dates sd
            JOIN source_records sr ON sr.id = sd.source_record_id
            WHERE sd.date_start IS NOT NULL
            ORDER BY sd.source_record_id, sd.date_start ASC
            LIMIT 200000
        """)

    sd_rows = await db_op(pool, _get_source_dated)
    log.info(f"  source_dates dated: {len(sd_rows):,}")

    # Merge (metadata_jsonb takes precedence for wiki articles)
    all_dated = {}
    for row in sd_rows:
        rid = row['id']
        all_dated[rid] = {
            'id': rid,
            'title': row['canonical_title'],
            'culture': row['culture'] or 'Ancient',
            'date_start': row['date_start'],
            'date_end': row['date_end'] or row['date_start'],
        }
    for row in meta_rows:
        rid = row['id']
        all_dated[rid] = {
            'id': rid,
            'title': row['canonical_title'],
            'culture': row['culture'] or 'Ancient',
            'date_start': row['date_start'],
            'date_end': row['date_end'] or row['date_start'],
        }

    log.info(f"  Total unique dated records: {len(all_dated):,}")

    # Phase 2: Assign to epochs
    log.info("Phase 2: Assigning to epochs...")
    epoch_buckets = defaultdict(list)  # epoch_id -> list of records
    unassigned = 0

    for rec in all_dated.values():
        result = find_epoch(rec['date_start'])
        if result:
            epoch_id, _ = result
            epoch_buckets[epoch_id].append(rec)
        else:
            unassigned += 1

    for eid, title, ts, te in EPOCHS:
        count = len(epoch_buckets[eid])
        log.info(f"  {title}: {count:,} records")
    log.info(f"  Unassigned (post-100 CE): {unassigned:,}")

    # Phase 3: Get existing chapters and chapter_source_sets
    log.info("Phase 3: Loading existing chapters and links...")

    async def _get_existing_chapters(conn):
        return await conn.fetch("""
            SELECT id, epoch_id, title, time_start, time_end, chapter_order
            FROM canonical_chapters
            WHERE is_current = true
        """)

    existing_chapters = await db_op(pool, _get_existing_chapters)
    chapter_by_epoch = defaultdict(list)
    for ch in existing_chapters:
        chapter_by_epoch[ch['epoch_id']].append(ch)

    async def _get_existing_links(conn):
        return await conn.fetch("""
            SELECT chapter_id, source_record_id FROM chapter_source_sets
        """)

    existing_links = await db_op(pool, _get_existing_links)
    existing_link_set = {(r['chapter_id'], r['source_record_id']) for r in existing_links}
    log.info(f"  Existing chapters: {len(existing_chapters):,}, existing links: {len(existing_link_set):,}")

    # Phase 4: Create chapters and links per epoch
    log.info("Phase 4: Creating chapters and source links...")
    total_chapters_created = 0
    total_links_created = 0

    for eid, epoch_title, epoch_start, epoch_end in EPOCHS:
        records = epoch_buckets[eid]
        if not records:
            continue

        log.info(f"  Processing {epoch_title} ({len(records):,} records)...")

        groups = defaultdict(list)
        for rec in records:
            culture = normalize_culture(rec['culture'])
            slice_start, slice_end, time_label = make_time_slice(rec['date_start'], epoch_start, epoch_end)
            key = (culture, time_label, slice_start, slice_end)
            groups[key].append(rec)

        epoch_uuid = uuid.UUID(eid)

        for (culture, time_label, slice_start, slice_end), group_records in groups.items():
            chapter_title = f"{culture} — {time_label}"

            # Check if a chapter already exists for this culture+timeslice
            existing_ch = None
            for ch in chapter_by_epoch[epoch_uuid]:
                if (ch['time_start'] and ch['time_end'] and
                    ch['time_start'] == slice_start and ch['time_end'] == slice_end and
                    culture.lower() in (ch['title'] or '').lower()):
                    existing_ch = ch
                    break

            if existing_ch:
                ch_id = existing_ch['id']
            else:
                max_order = max([ch['chapter_order'] for ch in chapter_by_epoch[epoch_uuid]], default=0)
                new_order = max_order + 1

                async def _create_chapter(conn, _eid=epoch_uuid, _title=chapter_title,
                                          _ts=slice_start, _te=slice_end, _order=new_order):
                    return await conn.fetchval("""
                        INSERT INTO canonical_chapters
                            (id, epoch_id, title, time_start, time_end, chapter_order,
                             version, is_current, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5,
                                1, true, NOW(), NOW())
                        RETURNING id
                    """, _eid, _title, _ts, _te, _order)

                try:
                    ch_id = await db_op(pool, _create_chapter)
                    total_chapters_created += 1
                    chapter_by_epoch[epoch_uuid].append({
                        'id': ch_id, 'epoch_id': epoch_uuid,
                        'title': chapter_title, 'time_start': slice_start,
                        'time_end': slice_end, 'chapter_order': new_order,
                    })
                except Exception as e:
                    log.warning(f"    Failed to create chapter '{chapter_title}': {e}")
                    continue

            # Create chapter_source_sets links
            links_batch = []
            for rec in group_records:
                if (ch_id, rec['id']) not in existing_link_set:
                    links_batch.append((ch_id, rec['id'], rec['title'][:500] if rec['title'] else None))
                    existing_link_set.add((ch_id, rec['id']))

            if links_batch:
                LINK_BATCH = 200
                for i in range(0, len(links_batch), LINK_BATCH):
                    batch = links_batch[i:i+LINK_BATCH]

                    async def _insert_links(conn, _batch=batch):
                        for ch, sr, title in _batch:
                            await conn.execute("""
                                INSERT INTO chapter_source_sets
                                    (id, chapter_id, source_record_id, title, relevance_weight,
                                     source_type, created_at, updated_at)
                                VALUES (gen_random_uuid(), $1, $2, $3, 0.5, 'primary', NOW(), NOW())
                                ON CONFLICT DO NOTHING
                            """, ch, sr, title)
                        return len(_batch)

                    try:
                        n = await db_op(pool, _insert_links)
                        total_links_created += n
                    except Exception as e:
                        log.warning(f"    Link insert failed: {e}")

        log.info(f"    {epoch_title}: done")

    log.info(f"\n{'='*60}")
    log.info(f"DONE: {total_chapters_created:,} chapters created, {total_links_created:,} source links created")
    log.info(f"{'='*60}")

    # Show final chapter counts
    async def _final_counts(conn):
        return await conn.fetch("""
            SELECT ce.title, COUNT(cc.id) as ch_count
            FROM canonical_epochs ce
            LEFT JOIN canonical_chapters cc ON cc.epoch_id = ce.id AND cc.is_current = true
            WHERE ce.is_current = true
            GROUP BY ce.title, ce.epoch_order
            ORDER BY ce.epoch_order
        """)

    final = await db_op(pool, _final_counts)
    for row in final:
        log.info(f"  {row['title']}: {row['ch_count']} chapters")

    await pool.close()


asyncio.run(main())
