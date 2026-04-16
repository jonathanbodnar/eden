#!/usr/bin/env python3
"""Clean non-ancient Wikipedia discovered records using title-based filtering."""
import asyncio
import re
import os

MODERN_PATTERNS = [
    "football", "soccer", "rugby", "cricket", "basketball", "baseball",
    "hockey", "tennis", "golf", "boxing", "wrestling", "swimming",
    "olympics 19", "olympics 20", "world cup", "premier league",
    "championship 19", "championship 20", "season 19", "season 20",
    "league 19", "league 20", "tournament 19", "tournament 20",
    "election", "politician", "governor", "senator", "congressman",
    "president of", "prime minister", "mayor of",
    "television", "tv series", "tv show", "sitcom", "anime",
    "film)", "movie)", "album)", "song)", "single)",
    "video game", "software", "app)", "website",
    "company)", "corporation", "airline", "railway",
    "school)", "university)", "college)",
    "municipality", "district)", "village)",
    "magazine", "newspaper", "radio station",
    "(band)", "(singer)", "(rapper)", "(actress)", "(actor)",
    "south park", "simpsons", "star trek", "star wars",
]

_YEAR_RANGE_RE = re.compile(r'\b(1[5-9]\d\d|20\d\d)[\-\u2013]')
_BORN_RE = re.compile(r'\(born \d{4}\)')

async def main():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL", "postgresql://eden:eden@postgres:5432/eden")
    conn = await asyncpg.connect(dsn)

    rows = await conn.fetch("""
        SELECT id, title_hint FROM discovered_records
        WHERE trusted_source_id = 'bb45f74d-163b-4ee8-9eb6-52fba63e9360'
        AND status = 'new'
    """)
    
    to_delete = []
    for row in rows:
        title = (row['title_hint'] or "").lower()
        is_modern = False
        for p in MODERN_PATTERNS:
            if p in title:
                is_modern = True
                break
        if not is_modern and _YEAR_RANGE_RE.search(title):
            is_modern = True
        if not is_modern and _BORN_RE.search(title):
            is_modern = True
        if is_modern:
            to_delete.append(row['id'])

    if to_delete:
        # Delete in batches
        batch_size = 1000
        for i in range(0, len(to_delete), batch_size):
            batch = to_delete[i:i+batch_size]
            await conn.execute(
                "DELETE FROM discovered_records WHERE id = ANY($1::uuid[])",
                batch
            )
        print(f"Deleted {len(to_delete)} obviously modern discovered records")
    else:
        print("No obviously modern records found")
    
    remaining = await conn.fetchval("""
        SELECT count(*) FROM discovered_records
        WHERE trusted_source_id = 'bb45f74d-163b-4ee8-9eb6-52fba63e9360'
        AND status = 'new'
    """)
    print(f"Remaining pending: {remaining}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
