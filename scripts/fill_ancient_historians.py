"""Fill gaps in ancient historian texts using Project Gutenberg and other
public domain sources. Insert into source_records + source_versions."""

import asyncio
import hashlib
import uuid
import logging
import re
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('historians')

DATABASE_URL = 'postgresql+asyncpg://eden:eden@127.0.0.1:5432/eden'
engine = create_async_engine(DATABASE_URL, pool_size=5)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    return resp.text


def extract_html_text(html: str) -> str:
    """Extract readable text from an HTML page, removing boilerplate."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe', 'noscript']):
        tag.decompose()
    body = soup.find('body') or soup
    text_content = body.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
    clean = '\n'.join(lines)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    return clean


def extract_plain_text(raw: str) -> str:
    """Clean up a plain text file from Gutenberg."""
    start_markers = ['*** START OF', '***START OF']
    end_markers = ['*** END OF', '***END OF', 'End of the Project Gutenberg', 'End of Project Gutenberg']
    start_idx = 0
    for m in start_markers:
        idx = raw.find(m)
        if idx != -1:
            nl = raw.find('\n', idx)
            start_idx = nl + 1 if nl != -1 else idx + len(m)
            break
    end_idx = len(raw)
    for m in end_markers:
        idx = raw.find(m)
        if idx != -1:
            end_idx = min(end_idx, idx)
    text = raw[start_idx:end_idx].strip()
    return text


# =============================================================================
# JOSEPHUS: Fetch complete works from Project Gutenberg as single texts,
# then split by book and update existing source_records
# =============================================================================

JOSEPHUS_ANTIQUITIES_URL = "https://www.gutenberg.org/files/2848/2848-0.txt"
JOSEPHUS_WARS_URL = "https://www.gutenberg.org/cache/epub/2850/pg2850.txt"

ROMAN_NUMS = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX',
              'X', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII',
              'XVIII', 'XIX', 'XX', 'XXI']

JOSEPHUS_EXT_MAP = {
    "st-jud-josephus-ant-pref": ("ant", "PREFACE", "Josephus - Antiquities of the Jews, Preface"),
    "st-jud-josephus-ant-1":    ("ant", "I", "Josephus - Antiquities of the Jews, Book I"),
    "st-jud-josephus-ant-2":    ("ant", "II", "Josephus - Antiquities of the Jews, Book II"),
    "st-jud-josephus-ant-3":    ("ant", "III", "Josephus - Antiquities of the Jews, Book III"),
    "st-jud-josephus-ant-10":   ("ant", "X", "Josephus - Antiquities of the Jews, Book X"),
    "st-jud-josephus-ant-12":   ("ant", "XII", "Josephus - Antiquities of the Jews, Book XII"),
    "st-jud-josephus-ant-13":   ("ant", "XIII", "Josephus - Antiquities of the Jews, Book XIII"),
    "st-jud-josephus-ant-14":   ("ant", "XIV", "Josephus - Antiquities of the Jews, Book XIV"),
    "st-jud-josephus-ant-18":   ("ant", "XVIII", "Josephus - Antiquities of the Jews, Book XVIII"),
    "st-jud-josephus-ant-20":   ("ant", "XX", "Josephus - Antiquities of the Jews, Book XX"),
    "st-jud-josephus-war-2":    ("war", "II", "Josephus - The Jewish War, Book II"),
    "st-jud-josephus-war-3":    ("war", "III", "Josephus - The Jewish War, Book III"),
    "st-jud-josephus-war-4":    ("war", "IV", "Josephus - The Jewish War, Book IV"),
    "st-jud-josephus-war-6":    ("war", "VI", "Josephus - The Jewish War, Book VI"),
    "st-jud-josephus-autobiog": ("ant", "AUTOBIOG", "Josephus - Autobiography (Life of Flavius Josephus)"),
    "st-jud-josephus-index":    (None, None, None),
}


def find_book_positions(full_text: str) -> list[tuple[str, int]]:
    """Find all real book boundaries. The Gutenberg texts have a TOC with
    'BOOK I. Containing...' entries early on, then the same headers again
    for the actual text. We deduplicate by keeping the LAST occurrence of
    each book number."""
    all_matches = []
    for m in re.finditer(r'BOOK ([IVX]+)\.\s+Containing', full_text):
        all_matches.append((m.group(1), m.start()))

    # Keep last occurrence of each book (the real text, not TOC)
    last_pos = {}
    for num, pos in all_matches:
        last_pos[num] = pos
    positions = sorted(last_pos.items(), key=lambda x: x[1])

    # Also find the preface (take last occurrence too)
    pref_matches = list(re.finditer(r'(?:^|\n)\s*PREFACE\b', full_text, re.IGNORECASE))
    if pref_matches:
        positions.insert(0, ("PREFACE", pref_matches[-1].start()))
    positions.sort(key=lambda x: x[1])
    return positions


def extract_book_section(full_text: str, positions: list[tuple[str, int]], book_num: str) -> str:
    """Extract a single book's text from the full text given pre-computed positions."""
    for i, (num, start) in enumerate(positions):
        if num == book_num:
            end = positions[i + 1][1] if i + 1 < len(positions) else len(full_text)
            section = full_text[start:end].strip()
            return section[:200000]
    return ""


async def handle_josephus(session: AsyncSession, client: httpx.AsyncClient):
    """Fetch Josephus texts from Gutenberg and populate existing records."""
    # First delete bad short extracts from first run
    await session.execute(text("""
        DELETE FROM source_versions
        WHERE source_record_id IN (
            SELECT sr.id FROM source_records sr
            JOIN raw_objects ro ON ro.id = sr.raw_object_id
            WHERE ro.external_id LIKE 'st-jud-josephus%'
        )
        AND LENGTH(text_extracted) < 5000
    """))
    await session.commit()
    log.info("Cleaned up short Josephus extracts from previous run")

    result = await session.execute(text("""
        SELECT sr.id, sr.canonical_title, ro.external_id
        FROM source_records sr
        JOIN raw_objects ro ON ro.id = sr.raw_object_id
        WHERE ro.external_id LIKE 'st-jud-josephus%'
        AND NOT EXISTS (
            SELECT 1 FROM source_versions sv
            WHERE sv.source_record_id = sr.id AND sv.text_extracted IS NOT NULL AND sv.text_extracted != ''
        )
    """))
    records = {row[2]: (row[0], row[1]) for row in result.fetchall()}
    log.info(f"Found {len(records)} Josephus records needing text")
    if not records:
        return

    log.info("Fetching Antiquities of the Jews from Project Gutenberg...")
    ant_text = ""
    try:
        ant_raw = await fetch_page(client, JOSEPHUS_ANTIQUITIES_URL)
        ant_text = extract_plain_text(ant_raw)
        log.info(f"  Antiquities: {len(ant_text):,} chars")
    except Exception as e:
        log.error(f"  Failed to fetch Antiquities: {e}")

    log.info("Fetching The Jewish War from Project Gutenberg...")
    war_text = ""
    try:
        war_raw = await fetch_page(client, JOSEPHUS_WARS_URL)
        war_text = extract_plain_text(war_raw)
        log.info(f"  Wars: {len(war_text):,} chars")
    except Exception as e:
        log.error(f"  Failed to fetch Wars: {e}")

    ant_positions = find_book_positions(ant_text) if ant_text else []
    war_positions = find_book_positions(war_text) if war_text else []
    log.info(f"  Antiquities books found: {[p[0] for p in ant_positions]}")
    log.info(f"  Wars books found: {[p[0] for p in war_positions]}")

    for ext_id, (sr_id, old_title) in records.items():
        mapping = JOSEPHUS_EXT_MAP.get(ext_id)
        if not mapping:
            continue
        work, book_num, nice_title = mapping
        if nice_title is None:
            log.info(f"  Skipping: {ext_id}")
            continue

        if work == "ant" and book_num == "AUTOBIOG":
            auto_match = re.search(r'(?i)THE LIFE OF FLAVIUS JOSEPHUS', ant_text)
            if auto_match:
                extracted = ant_text[auto_match.start():auto_match.start()+200000].strip()
            else:
                log.warning(f"  Could not find autobiography section")
                continue
        elif work == "ant":
            extracted = extract_book_section(ant_text, ant_positions, book_num)
        elif work == "war":
            extracted = extract_book_section(war_text, war_positions, book_num)
        else:
            continue

        if len(extracted) < 500:
            log.warning(f"  Too short for {ext_id}: {len(extracted)} chars")
            continue

        await session.execute(text("""
            INSERT INTO source_versions (id, source_record_id, version_type, language, is_preferred, text_extracted, created_at, updated_at)
            VALUES (:id, :sr_id, 'original', 'English', true, :text, NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "sr_id": str(sr_id), "text": extracted})

        await session.execute(text("""
            UPDATE source_records SET canonical_title = :title, culture = 'Jewish/Roman' WHERE id = :sr_id
        """), {"title": nice_title, "sr_id": str(sr_id)})

        log.info(f"  {ext_id} -> {nice_title}: {len(extracted):,} chars")

    await session.commit()
    log.info("Josephus records updated")


# =============================================================================
# NEW TEXTS: Historians missing or with thin coverage
# =============================================================================

NEW_TEXTS = [
    # --- Thucydides (Greek, 5th c BCE) ---
    {"title": "Thucydides - History of the Peloponnesian War (Complete)",
     "culture": "Greek", "author": "Thucydides",
     "url": "https://www.gutenberg.org/files/7142/7142-h/7142-h.htm",
     "format": "html"},

    # --- Polybius (Greek, 2nd c BCE) ---
    {"title": "Polybius - The Histories, Vol. I",
     "culture": "Greek", "author": "Polybius",
     "url": "https://www.gutenberg.org/files/44125/44125-h/44125-h.htm",
     "format": "html"},
    {"title": "Polybius - The Histories, Vol. II",
     "culture": "Greek", "author": "Polybius",
     "url": "https://www.gutenberg.org/files/44126/44126-h/44126-h.htm",
     "format": "html"},

    # --- Cassius Dio (Roman, 2nd-3rd c CE) ---
    {"title": "Cassius Dio - Roman History, Vol. 1",
     "culture": "Roman", "author": "Cassius Dio",
     "url": "https://www.gutenberg.org/cache/epub/18047/pg18047-images.html",
     "format": "html"},
    {"title": "Cassius Dio - Roman History, Vol. 2",
     "culture": "Roman", "author": "Cassius Dio",
     "url": "https://www.gutenberg.org/cache/epub/11607/pg11607-images.html",
     "format": "html"},
    {"title": "Cassius Dio - Roman History, Vol. 3",
     "culture": "Roman", "author": "Cassius Dio",
     "url": "https://www.gutenberg.org/cache/epub/10162/pg10162-images.html",
     "format": "html"},

    # --- Suetonius (Roman, 1st-2nd c CE) ---
    {"title": "Suetonius - The Lives of the Twelve Caesars (Complete)",
     "culture": "Roman", "author": "Suetonius",
     "url": "https://www.gutenberg.org/files/6400/6400-h/6400-h.htm",
     "format": "html"},

    # --- Livy (Roman, 1st c BCE) ---
    {"title": "Livy - The History of Rome, Books 1-8",
     "culture": "Roman", "author": "Livy",
     "url": "https://www.gutenberg.org/files/19725/19725-h/19725-h.htm",
     "format": "html"},
    {"title": "Livy - The History of Rome, Books 9-26",
     "culture": "Roman", "author": "Livy",
     "url": "https://www.gutenberg.org/cache/epub/10907/pg10907-images.html",
     "format": "html"},

    # --- Arrian (Greek, 2nd c CE) ---
    {"title": "Arrian - Anabasis of Alexander (Complete)",
     "culture": "Greek", "author": "Arrian",
     "url": "https://www.gutenberg.org/files/46976/46976-h/46976-h.htm",
     "format": "html"},

    # --- Appian (Roman/Greek, 2nd c CE) ---
    {"title": "Appian - The Civil Wars, Book I",
     "culture": "Roman", "author": "Appian",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Appian/Civil_Wars/1*.html",
     "format": "html"},
    {"title": "Appian - The Civil Wars, Book II",
     "culture": "Roman", "author": "Appian",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Appian/Civil_Wars/2*.html",
     "format": "html"},

    # --- Ammianus Marcellinus (Roman, 4th c CE) ---
    {"title": "Ammianus Marcellinus - Roman History (Complete)",
     "culture": "Roman", "author": "Ammianus Marcellinus",
     "url": "https://www.gutenberg.org/files/28587/28587-h/28587-h.htm",
     "format": "html"},

    # --- Manetho (Egyptian, 3rd c BCE) - fragments via LacusCurtius ---
    {"title": "Manetho - Aegyptiaca, Book I (History of Egypt)",
     "culture": "Egyptian", "author": "Manetho",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/1*.html",
     "format": "html"},
    {"title": "Manetho - Aegyptiaca, Book II (History of Egypt)",
     "culture": "Egyptian", "author": "Manetho",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/2*.html",
     "format": "html"},
    {"title": "Manetho - Aegyptiaca, Book III (History of Egypt)",
     "culture": "Egyptian", "author": "Manetho",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/3*.html",
     "format": "html"},

    # --- Plutarch - Moralia (Greek, 1st-2nd c CE) ---
    {"title": "Plutarch - Moralia: On Isis and Osiris",
     "culture": "Greek/Egyptian", "author": "Plutarch",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Plutarch/Moralia/Isis_and_Osiris*/A.html",
     "format": "html"},
    {"title": "Plutarch - Moralia (Shilleto translation, complete)",
     "culture": "Greek", "author": "Plutarch",
     "url": "https://www.gutenberg.org/files/23639/23639-h/23639-h.htm",
     "format": "html"},

    # --- Cicero - De Republica (Roman, 1st c BCE) ---
    {"title": "Cicero - De Republica (On the Republic)",
     "culture": "Roman", "author": "Cicero",
     "url": "https://www.gutenberg.org/files/54161/54161-h/54161-h.htm",
     "format": "html"},

    # --- Aulus Gellius (Roman, 2nd c CE) ---
    {"title": "Aulus Gellius - Attic Nights, Book I",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/1*.html",
     "format": "html"},
    {"title": "Aulus Gellius - Attic Nights, Book II",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/2*.html",
     "format": "html"},
    {"title": "Aulus Gellius - Attic Nights, Book III",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/3*.html",
     "format": "html"},
    {"title": "Aulus Gellius - Attic Nights, Book V",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/5*.html",
     "format": "html"},
    {"title": "Aulus Gellius - Attic Nights, Book VII",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/7*.html",
     "format": "html"},
    {"title": "Aulus Gellius - Attic Nights, Book IX",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/9*.html",
     "format": "html"},
    {"title": "Aulus Gellius - Attic Nights, Book X",
     "culture": "Roman", "author": "Aulus Gellius",
     "url": "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/10*.html",
     "format": "html"},

    # --- Denkard (Zoroastrian, 9th c CE compilation) ---
    {"title": "Denkard - Book V: Writings of Adar Frobag (Zoroastrian)",
     "culture": "Zoroastrian/Persian", "author": "Unknown (Zoroastrian priests)",
     "url": "https://www.avesta.org/denkard/dk5s.html",
     "format": "html"},
    {"title": "Denkard - Book IX: Ancient Canon Nasks (Zoroastrian)",
     "culture": "Zoroastrian/Persian", "author": "Unknown (Zoroastrian priests)",
     "url": "https://www.avesta.org/denkard/dk9sbe.html",
     "format": "html"},
]


async def get_or_create_trusted_source(session: AsyncSession) -> str:
    """Get an existing trusted source for public domain texts, or fall back
    to any available one."""
    result = await session.execute(text(
        "SELECT id FROM trusted_sources WHERE name = 'Eden Research (Manual)'"
    ))
    row = result.fetchone()
    if row:
        return str(row[0])

    result = await session.execute(text(
        "SELECT id FROM trusted_sources WHERE source_category = 'public_domain_library' AND active = true LIMIT 1"
    ))
    row = result.fetchone()
    if row:
        return str(row[0])

    result = await session.execute(text("SELECT id FROM trusted_sources WHERE active = true LIMIT 1"))
    row = result.fetchone()
    return str(row[0]) if row else None


async def add_new_text(session: AsyncSession, client: httpx.AsyncClient, entry: dict, ts_id: str):
    """Fetch a text and create source_record + source_version.
    Uses a savepoint so failures don't poison the whole transaction."""
    title = entry["title"]

    existing = await session.execute(text(
        "SELECT id FROM source_records WHERE canonical_title = :title"
    ), {"title": title})
    if existing.fetchone():
        log.info(f"  Already exists: {title}")
        return

    try:
        html = await fetch_page(client, entry["url"])
        extracted = extract_html_text(html)

        if len(extracted) < 200:
            log.warning(f"  Too short for {title}: {len(extracted)} chars, skipping")
            return

        if len(extracted) > 500000:
            extracted = extracted[:500000]
            log.info(f"  Truncated {title} to 500k chars")

        ext_id = 'eden-hist-' + hashlib.md5(title.encode()).hexdigest()[:12]
        checksum = hashlib.sha256(extracted.encode()).hexdigest()
        byte_size = len(extracted.encode('utf-8'))
        r2_key = f'manual/{ext_id}.html'
        ro_id = str(uuid.uuid4())
        sr_id = str(uuid.uuid4())
        sv_id = str(uuid.uuid4())

        async with session.begin_nested():
            await session.execute(text("""
                INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url, content_type, checksum, byte_size, r2_key, fetched_at)
                VALUES (:ro_id, :ts_id, :ext_id, :url, 'text/html', :checksum, :byte_size, :r2_key, NOW())
            """), {"ro_id": ro_id, "ts_id": ts_id, "ext_id": ext_id, "url": entry["url"],
                   "checksum": checksum, "byte_size": byte_size, "r2_key": r2_key})

            await session.execute(text("""
                INSERT INTO source_records (id, raw_object_id, canonical_title, culture, source_category, created_at, updated_at)
                VALUES (:sr_id, :ro_id, :title, :culture, 'public_domain_library', NOW(), NOW())
            """), {"sr_id": sr_id, "ro_id": ro_id, "title": title, "culture": entry["culture"]})

            await session.execute(text("""
                INSERT INTO source_versions (id, source_record_id, version_type, language, is_preferred, text_extracted, created_at, updated_at)
                VALUES (:sv_id, :sr_id, 'original', 'English', true, :text, NOW(), NOW())
            """), {"sv_id": sv_id, "sr_id": sr_id, "text": extracted})

        log.info(f"  Added {title}: {len(extracted):,} chars")
    except Exception as e:
        log.error(f"  Failed {title}: {e}")
        try:
            await session.rollback()
        except Exception:
            pass


async def update_fts(session: AsyncSession):
    """Update FTS tsvector columns for new/updated records."""
    await session.execute(text("""
        UPDATE source_records SET tsv = to_tsvector('english',
            COALESCE(canonical_title, '') || ' ' || COALESCE(culture, '') || ' ' || COALESCE(origin_place_name, ''))
        WHERE tsv IS NULL
    """))
    await session.execute(text("""
        UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
        WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL
    """))
    await session.commit()
    log.info("FTS indexes updated for new records")


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        async with Session() as session:
            log.info("=" * 60)
            log.info("Phase 1: Josephus - Sacred Texts records from Gutenberg")
            log.info("=" * 60)
            await handle_josephus(session, client)

            log.info("=" * 60)
            log.info("Phase 2: New historian texts")
            log.info("=" * 60)
            ts_id = await get_or_create_trusted_source(session)

            for i, entry in enumerate(NEW_TEXTS):
                log.info(f"[{i+1}/{len(NEW_TEXTS)}] {entry['title']}")
                await add_new_text(session, client, entry, ts_id)
                await asyncio.sleep(2)
            await session.commit()

            log.info("=" * 60)
            log.info("Phase 3: Update FTS")
            log.info("=" * 60)
            await update_fts(session)

    log.info("All done!")


asyncio.run(main())
