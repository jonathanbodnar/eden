"""Build the ancient article filter from Wikipedia dump files (v5 - TIGHT).

Changes from v4:
- BFS depth reduced from 4 to 2
- Massive exclusion list to block modern/irrelevant category branches
- Only keeps articles that are genuinely ancient-world content
"""
import gzip
import json
import re
import sys
import logging
from pathlib import Path
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DUMP_DIR = "/opt/wiki-dump"
MAX_DEPTH = 2

SEED_CATEGORIES = {
    "Ancient_civilizations", "Ancient_history", "Ancient_peoples",
    "Ancient_Near_East", "Mesopotamia", "Sumer", "Akkadian_Empire",
    "Babylonia", "Assyria", "Elam", "Hittites", "Hurrians",
    "Ancient_Egypt", "Pharaohs", "Ancient_Egyptian_religion",
    "Ancient_Greece", "Ancient_Greek_religion", "Ancient_Greek_cities",
    "Ancient_Rome", "Roman_Republic", "Roman_Empire",
    "Ancient_India", "Vedic_period",
    "Ancient_China", "Shang_dynasty", "Zhou_dynasty",
    "Ancient_Persia", "Achaemenid_Empire",
    "Phoenicia", "Canaan", "Ancient_Levant",
    "Nubia", "Kingdom_of_Kush", "Axum",
    "Minoan_civilization", "Mycenaean_Greece",
    "Etruscans",
    "Pre-Columbian_era", "Maya_civilization", "Olmec",
    "Ancient_Korea", "Ancient_Japan",
    "Scythians", "Thracians",
    "Bronze_Age", "Iron_Age", "Neolithic", "Chalcolithic",
    "Stone_Age", "Paleolithic", "Mesolithic",
    "Classical_antiquity", "Late_antiquity",
    "Prehistory",
    "3rd_millennium_BC", "4th_millennium_BC", "5th_millennium_BC",
    "2nd_millennium_BC", "1st_millennium_BC",
    "Mesopotamian_mythology", "Sumerian_mythology",
    "Egyptian_mythology", "Greek_mythology", "Roman_mythology",
    "Hindu_mythology", "Norse_mythology", "Celtic_mythology",
    "Chinese_mythology", "Japanese_mythology",
    "Mesoamerican_mythology", "Zoroastrianism",
    "Ancient_Egyptian_texts",
    "Creation_myths", "Flood_myths",
    "Archaeological_sites", "Archaeological_artifacts",
    "Ancient_cities",
    "Cuneiform", "Hieroglyphs",
    "Clay_tablets", "Inscriptions",
    "Megalithic_monuments",
    "Göbekli_Tepe", "Çatalhöyük", "Jericho",
    "Mohenjo-daro", "Harappa",
    "Ur", "Uruk", "Nineveh",
    "Troy", "Knossos", "Mycenae",
    "Persepolis", "Pompeii",
    "Epic_of_Gilgamesh", "Dead_Sea_Scrolls",
    "Nag_Hammadi_library", "Mahabharata", "Ramayana",
    "Vedas", "Upanishads",
    "Ancient_Greek_literature", "Latin_literature",
    "Ancient_Egyptian_literature", "Akkadian_literature",
    "Sumerian_literature", "Sanskrit_literature",
}

# Categories to NEVER enter during BFS (blocks entire subtree)
EXCLUDE_CATEGORIES = {
    # Modern content
    "Living_people", "21st-century_people", "20th-century_people",
    "19th-century_people", "18th-century_people",
    "Possibly_living_people",
    # Entertainment / fiction
    "Fictional_characters", "Fiction", "Novels", "Films", "Television",
    "Video_games", "Comics", "Anime", "Manga",
    "Science_fiction", "Fantasy", "Horror_fiction",
    "Mythological_characters_in_popular_culture",
    "Greek_mythology_in_popular_culture",
    "Roman_mythology_in_popular_culture",
    "Egyptian_mythology_in_popular_culture",
    "Norse_mythology_in_popular_culture",
    "Mythology_in_popular_culture",
    "Ancient_Greece_in_popular_culture",
    "Ancient_Rome_in_popular_culture",
    "Ancient_Egypt_in_popular_culture",
    "Cultural_depictions",
    "Operas", "Ballets", "Musicals", "Plays_(theatre)",
    # Modern scholarship / meta
    "Historiography", "Academic_journals",
    "Historians", "Archaeologists", "Egyptologists",
    "Classical_scholars", "Classicists",
    "History_education", "Archaeological_organizations",
    # Modern geography / politics
    "Countries", "Subdivisions", "Populated_places",
    "Modern_states", "Sovereign_states",
    "Politics", "Political_parties",
    "Elections", "Governments",
    # Modern religion
    "Christianity", "Islam", "Modern_paganism",
    "New_religious_movements",
    # Sports / games
    "Sports", "Athletes", "Olympic_Games",
    "Football", "Baseball", "Basketball", "Cricket",
    "Board_games", "Card_games",
    # Music
    "Musical_groups", "Musicians", "Albums", "Songs",
    "Musical_compositions", "Composers",
    # Science / technology (modern)
    "Science", "Technology", "Computing", "Software",
    "Astronomy", "Physics", "Chemistry", "Biology",
    "Mathematics", "Engineering",
    "Inventions", "Discoveries",
    # Military (modern)
    "World_War_I", "World_War_II",
    "20th-century_conflicts", "21st-century_conflicts",
    "Cold_War", "Nuclear_weapons",
    # Wikipedia meta
    "Wikipedia_categories", "WikiProject",
    "Wikipedia_articles", "Stub_categories",
    "All_stub_articles", "Articles_needing",
    # Disambiguation
    "Disambiguation_pages", "Set_index_articles",
    "Human_name_disambiguation_pages",
    # Modern arts
    "Contemporary_art", "Modern_art",
    "Photography", "Painting", "Sculpture",
    # Cuisine / food
    "Cuisine", "Beverages", "Food_and_drink",
    # Language (modern)
    "Modern_languages", "English_language",
    "French_language", "German_language",
    # Economics / business
    "Companies", "Brands", "Economics",
    "Businesspeople", "Entrepreneurs",
    # Law
    "Law", "Courts", "Legal_terms",
    # Education
    "Universities", "Schools", "Educational_institutions",
    # Transport
    "Airports", "Railways", "Roads", "Ships",
    "Automobiles", "Aviation",
    # Buildings (modern)
    "Skyscrapers", "Bridges", "Dams",
    # Demographics
    "Ethnic_groups", "Demographics",
    # Health / medicine (modern)
    "Diseases", "Medical_terminology",
    "Hospitals", "Pharmaceuticals",
}

# Patterns in category names to exclude
EXCLUDE_PATTERNS = [
    r"^\d{4}_", r"^\d{4}s_",  # Year-based categories (1990s_, 2020_, etc.)
    r"_by_country$", r"_by_nationality$",
    r"_stubs$",
    r"_in_popular_culture$",
    r"_in_fiction$",
    r"_in_film$",
    r"_in_television$",
    r"_in_video_games$",
    r"_in_comics$",
    r"_in_anime$",
    r"_in_music$",
    r"_in_art$",
    r"_organizations$",
    r"_awards$",
    r"_competitions$",
    r"_magazines$",
    r"_newspapers$",
    r"_websites$",
    r"_podcasts$",
    r"_TV_series$",
    r"_films$",
    r"_novels$",
    r"_books$",
    r"_songs$",
    r"_albums$",
    r"-Class_",  # Wikipedia assessment classes
    r"^All_articles_",
    r"^Articles_",
    r"^Pages_",
    r"^Use_",
    r"^Webarchive_",
    r"^CS1_",
    r"^Short_description",
]
EXCLUDE_RE = re.compile('|'.join(EXCLUDE_PATTERNS))


TAIL_RE = re.compile(
    rb"'(page|subcat|file)'"
    rb",(\d+)"
    rb",(\d+)\)"
)
HEAD_RE = re.compile(rb"\((\d+),")

LT_RE = re.compile(rb"\((\d+),14,'([^']*(?:\\.[^']*)*?)'\)")


def parse_catlinks_bytes(raw_line: bytes):
    results = []
    for tm in TAIL_RE.finditer(raw_line):
        cl_type = tm.group(1).decode('ascii')
        cl_target_id = int(tm.group(3))
        search_start = max(0, tm.start() - 500)
        chunk = raw_line[search_start:tm.start()]
        last_head = None
        for hm in HEAD_RE.finditer(chunk):
            last_head = hm
        if last_head:
            cl_from = int(last_head.group(1))
            results.append((cl_from, cl_type, cl_target_id))
    return results


def parse_sql_values(line):
    idx = line.find("VALUES ")
    if idx < 0:
        return
    rest = line[idx + 7:]
    i = 0
    n = len(rest)
    while i < n:
        if rest[i] != '(':
            i += 1
            continue
        i += 1
        fields = []
        while i < n and rest[i] != ')':
            if rest[i] == "'":
                i += 1
                val_chars = []
                while i < n:
                    if rest[i] == '\\' and i + 1 < n:
                        val_chars.append(rest[i + 1])
                        i += 2
                    elif rest[i] == "'":
                        i += 1
                        break
                    else:
                        val_chars.append(rest[i])
                        i += 1
                fields.append(''.join(val_chars))
            elif rest[i] == ',':
                i += 1
            else:
                val_chars = []
                while i < n and rest[i] not in (',', ')'):
                    val_chars.append(rest[i])
                    i += 1
                fields.append(''.join(val_chars))
        if rest[i:i+1] == ')':
            i += 1
        yield fields


def should_exclude(cat_name: str) -> bool:
    if cat_name in EXCLUDE_CATEGORIES:
        return True
    if EXCLUDE_RE.search(cat_name):
        return True
    return False


def main():
    linktarget_path = Path(DUMP_DIR) / "linktarget.sql.gz"
    catlinks_path = Path(DUMP_DIR) / "categorylinks.sql.gz"
    page_path = Path(DUMP_DIR) / "page.sql.gz"
    filter_path = Path(DUMP_DIR) / "ancient_page_ids_v5.json"

    # ── Phase 1: Parse linktarget.sql.gz ──
    log.info("Phase 1: Parsing linktarget.sql.gz...")
    ltid_to_catname: dict[int, str] = {}
    catname_to_ltid: dict[str, int] = {}

    with gzip.open(str(linktarget_path), 'rb') as f:
        line_count = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1
            for m in LT_RE.finditer(raw_line):
                lt_id = int(m.group(1))
                try:
                    lt_title = m.group(2).decode('utf-8', errors='replace')
                except Exception:
                    continue
                lt_title = lt_title.replace("\\'", "'")
                ltid_to_catname[lt_id] = lt_title
                catname_to_ltid[lt_title] = lt_id
            if line_count % 200 == 0:
                log.info(f"  linktarget: {line_count} lines, {len(ltid_to_catname):,} cat entries")

    log.info(f"  Total: {len(ltid_to_catname):,} category linktargets")

    seed_lt_ids: set[int] = set()
    for name in SEED_CATEGORIES:
        lt_id = catname_to_ltid.get(name)
        if lt_id:
            seed_lt_ids.add(lt_id)
        else:
            log.warning(f"  Seed not found: {name}")
    log.info(f"  {len(seed_lt_ids)} seed categories matched")

    # ── Phase 2: Parse page.sql.gz ──
    log.info("Phase 2: Parsing page.sql.gz...")
    ns0_page_ids: set[int] = set()
    catpage_to_title: dict[int, str] = {}

    with gzip.open(str(page_path), 'rt', encoding='utf-8', errors='replace') as f:
        line_count = 0
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_sql_values(line):
                if len(fields) < 3:
                    continue
                try:
                    pid = int(fields[0])
                    ns = int(fields[1])
                except (ValueError, IndexError):
                    continue
                if ns == 0:
                    ns0_page_ids.add(pid)
                elif ns == 14:
                    catpage_to_title[pid] = fields[2]
            line_count += 1
            if line_count % 200 == 0:
                log.info(f"  page.sql: {line_count} lines, {len(ns0_page_ids):,} articles, {len(catpage_to_title):,} cats")

    log.info(f"  Total: {len(ns0_page_ids):,} articles, {len(catpage_to_title):,} cat pages")

    # ── Phase 3: Build subcat tree from categorylinks ──
    log.info("Phase 3: Building subcat tree from categorylinks...")
    parent_ltid_to_children: dict[int, set[int]] = {}

    with gzip.open(str(catlinks_path), 'rb') as f:
        line_count = 0
        subcat_total = 0
        mapped = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1
            for cl_from, cl_type, cl_target_id in parse_catlinks_bytes(raw_line):
                if cl_type != 'subcat':
                    continue
                subcat_total += 1
                child_title = catpage_to_title.get(cl_from)
                if child_title is None:
                    continue
                child_lt_id = catname_to_ltid.get(child_title)
                if child_lt_id is None:
                    continue
                parent_ltid_to_children.setdefault(cl_target_id, set()).add(child_lt_id)
                mapped += 1
            if line_count % 500 == 0:
                log.info(f"  catlinks: {line_count} lines, {mapped:,} mapped subcats")

    log.info(f"  {len(parent_ltid_to_children):,} parents, {mapped:,} mapped subcat links")
    del catpage_to_title

    # ── Phase 4: BFS expand with exclusions ──
    log.info(f"Phase 4: BFS from {len(seed_lt_ids)} seeds (depth {MAX_DEPTH}, with exclusions)...")
    target_lt_ids: set[int] = set()
    excluded_count = 0
    queue = deque([(lt_id, 0) for lt_id in seed_lt_ids])

    while queue:
        lt_id, depth = queue.popleft()
        if lt_id in target_lt_ids:
            continue

        cat_name = ltid_to_catname.get(lt_id, '')
        if should_exclude(cat_name):
            excluded_count += 1
            continue

        target_lt_ids.add(lt_id)
        if depth < MAX_DEPTH:
            for child_lt_id in parent_ltid_to_children.get(lt_id, set()):
                if child_lt_id not in target_lt_ids:
                    queue.append((child_lt_id, depth + 1))

    del parent_ltid_to_children
    log.info(f"  Expanded to {len(target_lt_ids):,} target categories ({excluded_count:,} excluded)")

    sample = sorted([ltid_to_catname.get(lt, '?') for lt in list(target_lt_ids)[:40]])
    log.info(f"  Sample: {sample}")

    # ── Phase 5: Find articles ──
    log.info("Phase 5: Finding articles in target categories...")
    target_article_ids: set[int] = set()

    with gzip.open(str(catlinks_path), 'rb') as f:
        line_count = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1
            for cl_from, cl_type, cl_target_id in parse_catlinks_bytes(raw_line):
                if cl_type == 'page' and cl_target_id in target_lt_ids and cl_from in ns0_page_ids:
                    target_article_ids.add(cl_from)
            if line_count % 500 == 0:
                log.info(f"  catlinks pass 2: {line_count} lines, {len(target_article_ids):,} articles")

    log.info(f"  Found {len(target_article_ids):,} articles")

    # ── Phase 6: Get titles ──
    log.info("Phase 6: Getting titles...")
    page_titles: dict[int, str] = {}
    with gzip.open(str(page_path), 'rt', encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_sql_values(line):
                if len(fields) >= 3:
                    try:
                        pid = int(fields[0])
                    except ValueError:
                        continue
                    if pid in target_article_ids:
                        page_titles[pid] = fields[2]

    log.info(f"  Got titles for {len(page_titles):,} articles")

    # ── Save ──
    sample_cats = sorted([ltid_to_catname.get(lt, '?') for lt in list(target_lt_ids)[:300]])
    result = {
        "page_ids": sorted(target_article_ids),
        "page_titles": {str(pid): page_titles.get(pid, '') for pid in target_article_ids},
        "category_count": len(target_lt_ids),
        "article_count": len(target_article_ids),
        "sample_categories": sample_cats,
    }

    with open(str(filter_path), 'w') as f:
        json.dump(result, f)

    log.info(f"DONE: {len(target_article_ids):,} articles from {len(target_lt_ids):,} categories")
    log.info(f"Saved to {filter_path}")


if __name__ == '__main__':
    main()
