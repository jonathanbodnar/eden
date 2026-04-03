"""Backfill missing object_images for Wikipedia records that have image_urls in metadata."""
import asyncio
import logging
import os

import asyncpg
import httpx
import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
USER_AGENT = "EdenIngestion/1.0 (https://projectedin.com; eden@projectedin.com)"
CONCURRENCY = 4  # parallel downloads (Wikimedia allows ~4 req/s per client)

# Template images to skip (same list as fetch_worker)
SKIP_SUBSTRINGS = [
    ".svg", ".ogv", ".webm", ".ogg", "icon", "logo", "flag",
    "commons-logo", "wikidata", "question_book", "edit-clear",
    "ambox", "padlock", "globe", "portal", "wiki-", "wiktionary",
    "wikiquote", "wikisource", "symbol", "pictogram", "sign",
    "button", "arrow", "folder", "blue_pencil", "gnome", "nuvola",
    "crystal", "info_sign", "disambig", "stub", "red_pencil",
    "map_marker", "location_dot", "increase", "decrease",
    "pyramidi_aavikolla", "bible.malmesbury.arp",
    "the10commandments", "aleppo_codex_joshua",
    "046cupolaspietro", "cippus_-_louvre",
    "chaos_monster_and_sun_god", "adolf_behrman",
    "israel_relief_location_map", "near_east_non_political",
    "relief_location_map", "topographic_map",
]


def should_skip(url: str) -> bool:
    lower = url.lower()
    return any(s in lower for s in SKIP_SUBSTRINGS)


def ext_from_ct(ct: str) -> str:
    if "png" in ct:
        return "png"
    if "gif" in ct:
        return "gif"
    if "webp" in ct:
        return "webp"
    return "jpg"


async def main():
    conn = await asyncpg.connect(
        host="postgres", port=5432, user="eden", password="eden", database="eden"
    )

    r2 = boto3.client(
        "s3",
        endpoint_url=os.environ["EDEN_R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["EDEN_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["EDEN_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ["EDEN_R2_BUCKET_NAME"]

    # Get source id
    source_id = await conn.fetchval(
        "SELECT id FROM trusted_sources WHERE slug = 'wikipedia-ancient'"
    )

    # Find all raw_objects with image_urls but no object_images
    rows = await conn.fetch(
        """
        SELECT ro.id as raw_id, ro.external_id,
               ro.raw_metadata_jsonb->'image_urls' as image_urls_json
        FROM raw_objects ro
        WHERE ro.trusted_source_id = $1
        AND ro.raw_metadata_jsonb->'image_urls' IS NOT NULL
        AND jsonb_array_length(ro.raw_metadata_jsonb->'image_urls') > 0
        AND ro.id NOT IN (
            SELECT DISTINCT raw_object_id FROM object_images WHERE raw_object_id IS NOT NULL
        )
        ORDER BY ro.external_id
        """,
        source_id,
    )

    logger.info("Found %d raw_objects needing images", len(rows))

    stored_total = 0
    skipped_total = 0
    failed_total = 0

    import json
    # Pre-fetch dupe counts for all URLs to avoid per-URL DB roundtrips
    logger.info("Building dupe-count lookup...")
    dupe_rows = await conn.fetch(
        "SELECT image_url, COUNT(*) as cnt FROM object_images GROUP BY image_url HAVING COUNT(*) >= 3"
    )
    dupe_urls = {r["image_url"] for r in dupe_rows}
    logger.info("Template image blocklist: %d URLs", len(dupe_urls))

    sem = asyncio.Semaphore(CONCURRENCY)

    async def process_record(client, row, idx):
        nonlocal stored_total, skipped_total, failed_total
        async with sem:
            raw_id = row["raw_id"]
            external_id = row["external_id"]
            image_urls = json.loads(row["image_urls_json"])

            stored = 0
            for url in image_urls[:10]:
                if not url.startswith("http"):
                    continue
                if should_skip(url):
                    continue
                if url in dupe_urls:
                    continue

                try:
                    retries = 0
                    resp = None
                    while retries < 4:
                        resp = await client.get(url)
                        if resp.status_code == 429:
                            wait = float(resp.headers.get("retry-after", "15"))
                            wait = min(wait, 60)
                            logger.info("Rate limited, waiting %.0fs...", wait)
                            await asyncio.sleep(wait)
                            retries += 1
                            continue
                        break

                    if resp is None or resp.status_code != 200:
                        continue
                    img_data = resp.content
                    if len(img_data) < 500 or len(img_data) > MAX_IMAGE_SIZE:
                        continue

                    ct = resp.headers.get("content-type", "image/jpeg")
                    ext = ext_from_ct(ct)
                    r2_key = f"images/wikipedia-ancient/backfill/{external_id}/img_{stored:03d}.{ext}"

                    r2.put_object(Bucket=bucket, Key=r2_key, Body=img_data, ContentType=ct)

                    await conn.execute(
                        """
                        INSERT INTO object_images
                          (raw_object_id, trusted_source_id, image_url, r2_key,
                           content_type, byte_size, image_order)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT DO NOTHING
                        """,
                        raw_id, source_id, url, r2_key, ct, len(img_data), stored,
                    )
                    stored += 1
                    stored_total += 1
                    await asyncio.sleep(0.25)  # 4 concurrent * 0.25s = ~1 req/s per slot

                except Exception as exc:
                    failed_total += 1
                    logger.debug("Failed %s: %s", url, exc)

            if stored == 0:
                skipped_total += 1

            if (idx + 1) % 200 == 0:
                logger.info(
                    "Progress: %d/%d records, %d images stored, %d no-image, %d errors",
                    idx + 1, len(rows), stored_total, skipped_total, failed_total,
                )

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        tasks = [process_record(client, row, i) for i, row in enumerate(rows)]
        await asyncio.gather(*tasks)

    logger.info(
        "Done. stored=%d images, records_no_image=%d, errors=%d",
        stored_total, skipped_total, failed_total,
    )
    await conn.close()


asyncio.run(main())
