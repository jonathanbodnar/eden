"""Insert ancient historian texts directly using asyncpg (no ORM overhead).
Fetches from Project Gutenberg / LacusCurtius, inserts into Eden DB."""

import asyncio
import hashlib
import re
import uuid
import logging
import httpx
import asyncpg
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://eden:eden@127.0.0.1:5432/eden'
TS_ID = uuid.UUID('bb45f74d-163b-4ee8-9eb6-52fba63e9360')  # Wikipedia Ancient World / public domain

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0'}


def clean_html(html: str, max_chars: int = 500000) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'noscript']):
        tag.decompose()
    body = soup.find('body') or soup
    text = body.get_text(separator='\n', strip=True)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines)[:max_chars]


async def fetch(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=60)
    r.raise_for_status()
    return r.text


async def insert_record(conn: asyncpg.Connection, title: str, culture: str,
                        url: str, ext_id: str, text: str):
    existing = await conn.fetchval(
        'SELECT id FROM source_records WHERE canonical_title = $1', title)
    if existing:
        log.info(f'  SKIP (exists): {title}')
        return

    checksum = hashlib.sha256(text.encode()).hexdigest()
    byte_size = len(text.encode('utf-8'))
    r2_key = f'manual/{ext_id}.txt'

    async with conn.transaction():
        ro_id = await conn.fetchval("""
            INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                     content_type, checksum, byte_size, r2_key, fetched_at)
            VALUES (gen_random_uuid(), $1, $2, $3, 'text/html', $4, $5, $6, NOW())
            RETURNING id
        """, TS_ID, ext_id, url, checksum, byte_size, r2_key)

        sr_id = await conn.fetchval("""
            INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                        culture, source_category, provenance_status, record_status,
                                        created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, 'public_domain_library',
                    'verified', 'published', NOW(), NOW())
            RETURNING id
        """, ro_id, TS_ID, title, culture)

        await conn.execute("""
            INSERT INTO source_versions (id, source_record_id, version_type, language,
                                         is_preferred, text_extracted, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, 'original', 'English', true, $2, NOW(), NOW())
        """, sr_id, text)

    log.info(f'  OK ({len(text):,} chars): {title}')


TEXTS = [
    # --- THUCYDIDES ---
    {"title": "Thucydides - History of the Peloponnesian War (Complete)",
     "culture": "Greek",
     "url": "https://www.gutenberg.org/files/7142/7142-h/7142-h.htm",
     "ext_id": "pg-7142-thucydides"},

    # --- POLYBIUS ---
    {"title": "Polybius - The Histories, Vol. I",
     "culture": "Greek",
     "url": "https://www.gutenberg.org/files/44125/44125-h/44125-h.htm",
     "ext_id": "pg-44125-polybius-1"},
    {"title": "Polybius - The Histories, Vol. II",
     "culture": "Greek",
     "url": "https://www.gutenberg.org/files/44126/44126-h/44126-h.htm",
     "ext_id": "pg-44126-polybius-2"},

    # --- CASSIUS DIO ---
    {"title": "Cassius Dio - Roman History, Vol. 1 (Books 1-17)",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/cache/epub/18047/pg18047-images.html",
     "ext_id": "pg-18047-cassius-dio-1"},
    {"title": "Cassius Dio - Roman History, Vol. 2 (Books 18-35)",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/cache/epub/11607/pg11607-images.html",
     "ext_id": "pg-11607-cassius-dio-2"},
    {"title": "Cassius Dio - Roman History, Vol. 3 (Books 36-54)",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/cache/epub/10162/pg10162-images.html",
     "ext_id": "pg-10162-cassius-dio-3"},

    # --- SUETONIUS ---
    {"title": "Suetonius - Lives of the Twelve Caesars (Complete)",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/files/6400/6400-h/6400-h.htm",
     "ext_id": "pg-6400-suetonius"},

    # --- LIVY ---
    {"title": "Livy - History of Rome, Books 1-8",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/files/19725/19725-h/19725-h.htm",
     "ext_id": "pg-19725-livy-1-8"},
    {"title": "Livy - History of Rome, Books 9-26",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/cache/epub/10907/pg10907-images.html",
     "ext_id": "pg-10907-livy-9-26"},

    # --- ARRIAN ---
    {"title": "Arrian - Anabasis of Alexander (Complete)",
     "culture": "Greek",
     "url": "https://www.gutenberg.org/files/46976/46976-h/46976-h.htm",
     "ext_id": "pg-46976-arrian"},

    # --- APPIAN ---
    {"title": "Appian - The Civil Wars, Book I",
     "culture": "Roman",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Appian/Civil_Wars/1*.html",
     "ext_id": "lacus-appian-cw-1"},
    {"title": "Appian - The Civil Wars, Book II",
     "culture": "Roman",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Appian/Civil_Wars/2*.html",
     "ext_id": "lacus-appian-cw-2"},

    # --- AMMIANUS MARCELLINUS ---
    {"title": "Ammianus Marcellinus - Roman History (Complete)",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/files/28587/28587-h/28587-h.htm",
     "ext_id": "pg-28587-ammianus"},

    # --- MANETHO ---
    {"title": "Manetho - Aegyptiaca, Book I (Fragments)",
     "culture": "Egyptian",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/1*.html",
     "ext_id": "lacus-manetho-1"},
    {"title": "Manetho - Aegyptiaca, Book II (Fragments)",
     "culture": "Egyptian",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/2*.html",
     "ext_id": "lacus-manetho-2"},
    {"title": "Manetho - Aegyptiaca, Book III (Fragments)",
     "culture": "Egyptian",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/3*.html",
     "ext_id": "lacus-manetho-3"},

    # --- PLUTARCH - MORALIA ---
    {"title": "Plutarch - Moralia: On Isis and Osiris",
     "culture": "Greek/Egyptian",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Plutarch/Moralia/Isis_and_Osiris*/A.html",
     "ext_id": "lacus-plutarch-isis-osiris"},
    {"title": "Plutarch - Moralia (Complete, Shilleto translation)",
     "culture": "Greek",
     "url": "https://www.gutenberg.org/files/23639/23639-h/23639-h.htm",
     "ext_id": "pg-23639-plutarch-moralia"},

    # --- CICERO - DE REPUBLICA ---
    {"title": "Cicero - De Republica (On the Republic)",
     "culture": "Roman",
     "url": "https://www.gutenberg.org/files/54161/54161-h/54161-h.htm",
     "ext_id": "pg-54161-cicero-republica"},

    # --- AULUS GELLIUS ---
    {"title": "Aulus Gellius - Attic Nights, Books I-II",
     "culture": "Roman",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/1*.html",
     "ext_id": "lacus-gellius-1"},
    {"title": "Aulus Gellius - Attic Nights, Books V-VII",
     "culture": "Roman",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/5*.html",
     "ext_id": "lacus-gellius-5"},
    {"title": "Aulus Gellius - Attic Nights, Books IX-X",
     "culture": "Roman",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/9*.html",
     "ext_id": "lacus-gellius-9"},

    # --- DENKARD (ZOROASTRIAN) ---
    {"title": "Denkard - Book V: Writings of Adar Frobag (Zoroastrian)",
     "culture": "Zoroastrian/Persian",
     "url": "https://www.avesta.org/denkard/dk5s.html",
     "ext_id": "avesta-denkard-5"},
    {"title": "Denkard - Book IX: Ancient Canon Nasks (Zoroastrian)",
     "culture": "Zoroastrian/Persian",
     "url": "https://www.avesta.org/denkard/dk9sbe.html",
     "ext_id": "avesta-denkard-9"},
]


async def main():
    conn = await asyncpg.connect(DB_URL)
    async with httpx.AsyncClient(timeout=60) as client:
        for i, entry in enumerate(TEXTS, 1):
            log.info(f"[{i}/{len(TEXTS)}] {entry['title']}")
            try:
                html = await fetch(client, entry['url'])
                text = clean_html(html)
                if len(text) < 300:
                    log.warning(f'  Too short ({len(text)} chars), skipping')
                    continue
                await insert_record(conn, entry['title'], entry['culture'],
                                    entry['url'], entry['ext_id'], text)
            except Exception as e:
                log.error(f'  FAILED: {e}')
            await asyncio.sleep(1)

    log.info("Updating FTS indexes...")
    await conn.execute("""
        UPDATE source_records SET tsv = to_tsvector('english',
            COALESCE(canonical_title,'') || ' ' || COALESCE(culture,'') || ' ' || COALESCE(origin_place_name,''))
        WHERE tsv IS NULL
    """)
    await conn.execute("""
        UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
        WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL
    """)
    await conn.close()
    log.info("Done!")


asyncio.run(main())
