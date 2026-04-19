"""Link restored CDLI object_images to their R2 keys."""
import asyncio
import os

import asyncpg
import boto3


async def main():
    print("Connecting to database...", flush=True)
    conn = await asyncpg.connect(
        host="postgres", port=5432, user="eden", password="eden", database="eden"
    )

    rows = await conn.fetch(
        "SELECT oi.id, oi.image_order, ro.external_id "
        "FROM object_images oi "
        "JOIN raw_objects ro ON ro.id = oi.raw_object_id "
        "WHERE oi.trusted_source_id = "
        "(SELECT id FROM trusted_sources WHERE slug='cdli') "
        "AND oi.r2_key IS NULL"
    )
    print(f"object_images without r2_key: {len(rows)}", flush=True)

    r2 = boto3.client(
        "s3",
        endpoint_url=os.environ["EDEN_R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["EDEN_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["EDEN_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ["EDEN_R2_BUCKET_NAME"]

    print("Scanning R2 for CDLI images...", flush=True)
    r2_lookup: dict[str, dict[int, tuple[str, int]]] = {}
    paginator = r2.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix="images/cdli/", MaxKeys=1000):
        for obj in page.get("Contents", []):
            parts = obj["Key"].split("/")
            if len(parts) >= 7:
                eid = parts[5]
                fname = parts[-1]
                try:
                    order = int(fname.split("_")[1].split(".")[0])
                except (IndexError, ValueError):
                    continue
                if eid not in r2_lookup:
                    r2_lookup[eid] = {}
                r2_lookup[eid][order] = (obj["Key"], obj["Size"])
                count += 1

    print(f"R2 lookup built: {len(r2_lookup)} eids, {count} images", flush=True)

    matched = 0
    unmatched = 0
    unmatched_eids: set[str] = set()
    for row in rows:
        eid = row["external_id"]
        order = row["image_order"]
        if eid in r2_lookup and order in r2_lookup[eid]:
            r2_key, byte_size = r2_lookup[eid][order]
            await conn.execute(
                "UPDATE object_images SET r2_key = $1, byte_size = $2 WHERE id = $3",
                r2_key,
                byte_size,
                row["id"],
            )
            matched += 1
            if matched % 500 == 0:
                print(f"  Updated {matched} so far...", flush=True)
        else:
            unmatched += 1
            unmatched_eids.add(eid)

    print(f"Matched and updated: {matched}", flush=True)
    print(
        f"Unmatched (no R2 image): {unmatched} across {len(unmatched_eids)} records",
        flush=True,
    )
    if unmatched_eids:
        samples = sorted(list(unmatched_eids))[:10]
        print(f"  Sample unmatched eids: {samples}", flush=True)
    await conn.close()
    print("Done!", flush=True)


asyncio.run(main())
