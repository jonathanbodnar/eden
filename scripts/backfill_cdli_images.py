"""Download missing CDLI images from cdli.earth and store in R2."""
import asyncio
import logging
import os

import asyncpg
import boto3
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
USER_AGENT = "EdenIngestion/1.0 (https://projectedin.com; eden@projectedin.com)"
CONCURRENCY = 8  # parallel downloads


async def download_one(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    r2,
    bucket: str,
    conn,
    source_id: str,
    raw_id: str,
    external_id: str,
    image_urls: list[str],
) -> int:
    async with sem:
        stored = 0
        for order, url in enumerate(image_urls[:2]):  # photo + lineart
            if not url.startswith("http"):
                continue
            try:
                resp = await client.get(url, timeout=30.0)
                if resp.status_code == 404:
                    continue
                if resp.status_code != 200:
                    logger.debug("HTTP %d for %s", resp.status_code, url)
                    continue
                img_data = resp.content
                if len(img_data) < 500:
                    continue
                if len(img_data) > MAX_IMAGE_SIZE:
                    continue

                ct = resp.headers.get("content-type", "image/jpeg")
                ext = "jpg"
                if "png" in ct:
                    ext = "png"
                elif "gif" in ct:
                    ext = "gif"

                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                r2_key = (
                    f"images/cdli/{now.year}/{now.month:02d}/{now.day:02d}"
                    f"/{external_id}/img_{order:03d}.{ext}"
                )

                r2.put_object(Bucket=bucket, Key=r2_key, Body=img_data, ContentType=ct)

                await conn.execute(
                    """
                    INSERT INTO object_images
                      (raw_object_id, trusted_source_id, image_url, r2_key,
                       content_type, byte_size, image_order)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT DO NOTHING
                    """,
                    raw_id, source_id, url, r2_key, ct, len(img_data), order,
                )
                stored += 1

            except Exception as exc:
                logger.debug("Failed %s: %s", url, exc)

        return stored


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

    source_id = await conn.fetchval(
        "SELECT id FROM trusted_sources WHERE slug = 'cdli'"
    )

    rows = await conn.fetch(
        """
        SELECT ro.id as raw_id, ro.external_id,
               ro.raw_metadata_jsonb->'image_urls' as image_urls_json
        FROM raw_objects ro
        WHERE ro.trusted_source_id = $1
        AND ro.raw_metadata_jsonb->'image_urls' IS NOT NULL
        AND jsonb_array_length(ro.raw_metadata_jsonb->'image_urls') > 0
        AND ro.id NOT IN (
            SELECT DISTINCT raw_object_id FROM object_images
            WHERE raw_object_id IS NOT NULL
        )
        ORDER BY ro.external_id
        """,
        source_id,
    )

    logger.info("Found %d CDLI raw_objects missing images", len(rows))

    stored_total = 0
    failed_total = 0
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    ) as client:
        import json

        tasks = []
        for row in rows:
            image_urls = json.loads(row["image_urls_json"])
            tasks.append(
                download_one(
                    sem, client, r2, bucket, conn,
                    str(source_id), str(row["raw_id"]),
                    row["external_id"], image_urls,
                )
            )

        for i, coro in enumerate(asyncio.as_completed(tasks)):
            try:
                stored = await coro
                stored_total += stored
                if stored == 0:
                    failed_total += 1
            except Exception as exc:
                failed_total += 1
                logger.debug("Task error: %s", exc)

            if (i + 1) % 500 == 0:
                logger.info(
                    "Progress: %d/%d records processed, %d images stored, %d no-image",
                    i + 1, len(rows), stored_total, failed_total,
                )

    logger.info(
        "Done. stored=%d images across records, no-image=%d",
        stored_total, failed_total,
    )
    await conn.close()


asyncio.run(main())
