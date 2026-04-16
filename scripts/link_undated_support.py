"""
Link undated wiki/gutenberg articles as supplementary evidence to existing canonical entities.

Uses a single SQL query to batch-match undated article titles against canonical entity names,
then bulk-inserts canon_support_links.
"""
import asyncio
import logging
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


async def match_and_link(pool, entity_table: str, entity_type: str, name_col: str):
    """Match undated source_records to canonical entities by exact title match on entity name."""
    log.info(f"  Matching against {entity_table}...")

    async def _do_match(conn):
        return await conn.fetch(f"""
            WITH undated AS (
                SELECT sr.id, sr.canonical_title
                FROM source_records sr
                JOIN raw_objects ro ON ro.id = sr.raw_object_id
                WHERE (ro.external_id LIKE 'wiki-page-%%' OR ro.external_id LIKE 'gutenberg-%%')
                  AND (sr.metadata_jsonb IS NULL OR sr.metadata_jsonb->>'date_start' IS NULL)
                  AND sr.id NOT IN (SELECT source_record_id FROM source_dates)
                  AND sr.canonical_title IS NOT NULL
                  AND length(sr.canonical_title) > 2
            )
            SELECT DISTINCT u.id as sr_id, e.id as entity_id
            FROM undated u
            JOIN {entity_table} e ON lower(e.{name_col}) = lower(u.canonical_title)
            WHERE e.is_current = true
            LIMIT 50000
        """)

    matches = await db_op(pool, _do_match)
    log.info(f"    Found {len(matches):,} exact matches for {entity_type}")

    if not matches:
        return 0

    total = 0
    BATCH = 500
    for i in range(0, len(matches), BATCH):
        batch = matches[i:i+BATCH]

        async def _insert(conn, _batch=batch, _etype=entity_type):
            inserted = 0
            for row in _batch:
                try:
                    await conn.execute("""
                        INSERT INTO canon_support_links
                            (id, canonical_type, canonical_id, archive_object_type,
                             archive_object_id, support_type, weight, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1::canonical_type, $2,
                                'source_record'::archive_object_type, $3,
                                'secondary_context'::support_type, 0.3, NOW(), NOW())
                        ON CONFLICT DO NOTHING
                    """, _etype, row['entity_id'], row['sr_id'])
                    inserted += 1
                except Exception:
                    pass
            return inserted

        try:
            n = await db_op(pool, _insert)
            total += n
        except Exception as e:
            log.warning(f"    Batch insert failed: {e}")

        if (i // BATCH) % 10 == 0 and i > 0:
            log.info(f"    Inserted {total:,} links so far...")

    return total


async def fuzzy_match_and_link(pool, entity_table: str, entity_type: str, name_col: str):
    """Use word-overlap matching for titles that contain the entity name."""
    log.info(f"  Fuzzy matching against {entity_table}...")

    async def _do_match(conn):
        return await conn.fetch(f"""
            WITH undated AS (
                SELECT sr.id, lower(sr.canonical_title) as title
                FROM source_records sr
                JOIN raw_objects ro ON ro.id = sr.raw_object_id
                WHERE (ro.external_id LIKE 'wiki-page-%%' OR ro.external_id LIKE 'gutenberg-%%')
                  AND (sr.metadata_jsonb IS NULL OR sr.metadata_jsonb->>'date_start' IS NULL)
                  AND sr.id NOT IN (SELECT source_record_id FROM source_dates)
                  AND sr.canonical_title IS NOT NULL
                  AND length(sr.canonical_title) >= 4
            ),
            entities AS (
                SELECT id, lower({name_col}) as name
                FROM {entity_table}
                WHERE is_current = true
                  AND length({name_col}) >= 4
            )
            SELECT DISTINCT u.id as sr_id, e.id as entity_id
            FROM undated u
            JOIN entities e ON u.title LIKE '%%' || e.name || '%%'
              OR e.name LIKE '%%' || u.title || '%%'
            WHERE u.id NOT IN (
                SELECT archive_object_id FROM canon_support_links
                WHERE canonical_id = e.id AND support_type = 'secondary_context'
            )
            LIMIT 30000
        """)

    try:
        matches = await db_op(pool, _do_match)
    except Exception as e:
        log.warning(f"    Fuzzy match query failed for {entity_type}: {e}")
        return 0

    log.info(f"    Found {len(matches):,} fuzzy matches for {entity_type}")

    if not matches:
        return 0

    total = 0
    BATCH = 500
    for i in range(0, len(matches), BATCH):
        batch = matches[i:i+BATCH]

        async def _insert(conn, _batch=batch, _etype=entity_type):
            inserted = 0
            for row in _batch:
                try:
                    await conn.execute("""
                        INSERT INTO canon_support_links
                            (id, canonical_type, canonical_id, archive_object_type,
                             archive_object_id, support_type, weight, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1::canonical_type, $2,
                                'source_record'::archive_object_type, $3,
                                'secondary_context'::support_type, 0.25, NOW(), NOW())
                        ON CONFLICT DO NOTHING
                    """, _etype, row['entity_id'], row['sr_id'])
                    inserted += 1
                except Exception:
                    pass
            return inserted

        try:
            n = await db_op(pool, _insert)
            total += n
        except Exception as e:
            log.warning(f"    Batch insert failed: {e}")

    return total


async def main():
    pool = await asyncpg.create_pool(
        DB_URL, min_size=1, max_size=3,
        command_timeout=300,
        server_settings={'statement_timeout': '300000'},
    )

    total = 0

    # Exact title matches
    total += await match_and_link(pool, 'canonical_actors', 'actor', 'canonical_name')
    total += await match_and_link(pool, 'canonical_events', 'event', 'canonical_name')
    total += await match_and_link(pool, 'canonical_places', 'place', 'canonical_name')

    # Fuzzy containment matches
    total += await fuzzy_match_and_link(pool, 'canonical_actors', 'actor', 'canonical_name')
    total += await fuzzy_match_and_link(pool, 'canonical_events', 'event', 'canonical_name')
    total += await fuzzy_match_and_link(pool, 'canonical_places', 'place', 'canonical_name')

    await pool.close()
    log.info(f"\n{'='*60}")
    log.info(f"DONE: Created {total:,} supplementary support links")
    log.info(f"{'='*60}")


asyncio.run(main())
