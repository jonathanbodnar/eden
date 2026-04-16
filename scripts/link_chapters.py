"""Link undated chapters to source records based on tradition/culture matching."""
import asyncio
import re
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('linker')

DATABASE_URL = 'postgresql+asyncpg://eden:eden@localhost:5432/eden'

engine = create_async_engine(DATABASE_URL, pool_size=5)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def extract_tradition(title: str) -> str | None:
    m = re.search(r':\s*(.+?)(?:\s+Tradition)?$', title)
    if m:
        trad = m.group(1).strip()
        trad = re.sub(r'\s+Tradition$', '', trad)
        if len(trad) > 2:
            return trad
    return None


def tradition_to_search_terms(trad: str) -> list[str]:
    terms = [trad]
    for sep in ['/', ',', ' and ']:
        if sep in trad:
            parts = [p.strip() for p in trad.split(sep) if len(p.strip()) > 2]
            terms.extend(parts)
    cleaned = re.sub(r'\s*\([^)]+\)\s*', ' ', trad).strip()
    if cleaned != trad and len(cleaned) > 2:
        terms.append(cleaned)
    return list(set(terms))


async def main():
    async with Session() as session:
        result = await session.execute(text(
            "SELECT ch.id, ch.title FROM canonical_chapters ch "
            "WHERE ch.is_current = true "
            "AND NOT EXISTS (SELECT 1 FROM chapter_source_sets css WHERE css.chapter_id = ch.id) "
            "ORDER BY ch.title"
        ))
        chapters = result.fetchall()
        log.info(f'Found {len(chapters)} chapters without sources')

        total_linked = 0

        for idx, (ch_id, ch_title) in enumerate(chapters):
            trad = extract_tradition(ch_title)
            if not trad:
                continue

            terms = tradition_to_search_terms(trad)

            conditions = []
            params = {'ch_id': str(ch_id)}
            for i, term in enumerate(terms):
                pk = f'term_{i}'
                params[pk] = f'%{term}%'
                conditions.append(f"sr.culture ILIKE :{pk}")
                conditions.append(f"sr.canonical_title ILIKE :{pk}")

            where_clause = ' OR '.join(conditions)

            result = await session.execute(text(
                f"INSERT INTO chapter_source_sets "
                f"(id, chapter_id, source_record_id, title, relevance_weight, source_type, created_at, updated_at) "
                f"SELECT gen_random_uuid(), :ch_id, sr.id, sr.canonical_title, 1.0, "
                f"sr.source_category::text, NOW(), NOW() "
                f"FROM source_records sr "
                f"WHERE ({where_clause}) "
                f"AND NOT EXISTS (SELECT 1 FROM chapter_source_sets ex "
                f"WHERE ex.chapter_id = :ch_id::uuid AND ex.source_record_id = sr.id) "
                f"LIMIT 200"
            ), params)

            linked = result.rowcount
            total_linked += linked

            if (idx + 1) % 100 == 0:
                await session.commit()
                log.info(f'Processed {idx+1}/{len(chapters)} chapters, {total_linked} links total')

        await session.commit()
        log.info(f'Done! Total: {total_linked} new links across {len(chapters)} chapters')


asyncio.run(main())
