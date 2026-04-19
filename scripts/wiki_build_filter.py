"""Build the ancient article filter from Wikipedia dump files.

The key insight: categorylinks.cl_target_id references page.page_id (ns=14),
NOT category.cat_id. So we must map category names -> page_ids, not cat_ids.

Schema:
  category:      (cat_id, cat_title, cat_pages, cat_subcats, cat_files)
  page:          (page_id, page_namespace, page_title, ...)
  categorylinks: (cl_from, cl_sortkey, cl_timestamp, cl_sortkey_prefix,
                   cl_type, cl_collation_id, cl_target_id)

cl_target_id = page_id of the category page (ns=14)
cl_from = page_id of the page that belongs to that category
cl_type = 'page' | 'subcat' | 'file'
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
MAX_DEPTH = 4  # how deep to recurse subcategories

SEED_CATEGORIES = {
    "Ancient_civilizations", "Ancient_history", "Ancient_peoples",
    "Ancient_Near_East", "Mesopotamia", "Sumer", "Akkadian_Empire",
    "Babylonia", "Assyria", "Elam", "Hittites", "Hurrians",
    "Ancient_Egypt", "Pharaohs", "Ancient_Egyptian_religion",
    "Ancient_Greece", "Ancient_Greek_religion", "Ancient_Greek_cities",
    "Ancient_Rome", "Roman_Republic", "Roman_Empire",
    "Ancient_India", "Indus_Valley_civilisation", "Vedic_period",
    "Ancient_China", "Shang_dynasty", "Zhou_dynasty",
    "Ancient_Persia", "Achaemenid_Empire",
    "Phoenicia", "Canaan", "Ancient_Israel", "Ancient_Levant",
    "Nubia", "Kingdom_of_Kush", "Axum",
    "Minoan_civilization", "Mycenaean_Greece",
    "Ancient_Carthage", "Etruscans",
    "Pre-Columbian_era", "Maya_civilization", "Aztec", "Inca_Empire", "Olmec",
    "Ancient_Korea", "Ancient_Japan",
    "Scythians", "Thracians", "Celts", "Germanic_peoples",
    "Bronze_Age", "Iron_Age", "Neolithic", "Chalcolithic",
    "Stone_Age", "Paleolithic", "Mesolithic",
    "Classical_antiquity", "Late_antiquity",
    "Protohistory", "Prehistory",
    "3rd_millennium_BC", "4th_millennium_BC", "5th_millennium_BC",
    "2nd_millennium_BC", "1st_millennium_BC",
    "Ancient_religions", "Mythology", "Creation_myths",
    "Mesopotamian_mythology", "Sumerian_mythology",
    "Egyptian_mythology", "Greek_mythology", "Roman_mythology",
    "Hindu_mythology", "Norse_mythology", "Celtic_mythology",
    "Chinese_mythology", "Japanese_mythology",
    "Mesoamerican_mythology", "Zoroastrianism", "Manichaeism",
    "Ancient_Egyptian_texts", "Religious_texts",
    "Folklore", "Mythological_characters", "Deities",
    "Flood_myths",
    "Archaeological_sites", "Archaeological_artifacts",
    "Ancient_cities", "Ancient_buildings_and_structures",
    "Cuneiform", "Hieroglyphs",
    "Clay_tablets", "Inscriptions",
    "Megalithic_monuments", "Petroglyphs",
    "Göbekli_Tepe", "Çatalhöyük", "Jericho",
    "Mohenjo-daro", "Harappa",
    "Ur", "Uruk", "Babylon", "Nineveh",
    "Thebes,_Egypt", "Memphis,_Egypt", "Luxor",
    "Troy", "Knossos", "Mycenae",
    "Persepolis", "Susa", "Pompeii", "Herculaneum",
    "Epic_of_Gilgamesh", "Dead_Sea_Scrolls",
    "Nag_Hammadi_library", "Mahabharata", "Ramayana",
    "Vedas", "Upanishads", "Torah", "Quran",
    "Ancient_Greek_literature", "Latin_literature",
    "Ancient_Egyptian_literature", "Akkadian_literature",
    "Sumerian_literature", "Pali_literature", "Sanskrit_literature",
    "Epic_poetry",
}


def parse_sql_values(line: str):
    """Yield tuples of raw string values from a MySQL INSERT VALUES line.
    Handles binary sortkey fields gracefully."""
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


def main():
    catlinks_path = Path(DUMP_DIR) / "categorylinks.sql.gz"
    page_path = Path(DUMP_DIR) / "page.sql.gz"
    filter_path = Path(DUMP_DIR) / "ancient_page_ids.json"

    # ── Phase 1: Parse page.sql.gz ──
    # Build: cat_title -> page_id (for ns=14 category pages)
    # Build: set of ns=0 page_ids (articles)
    log.info("Phase 1: Parsing page.sql.gz...")
    cat_title_to_pageid: dict[str, int] = {}
    ns0_page_ids: set[int] = set()

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
                title = fields[2]
                if ns == 0:
                    ns0_page_ids.add(pid)
                elif ns == 14:
                    cat_title_to_pageid[title] = pid
            line_count += 1
            if line_count % 50 == 0:
                log.info(f"  page.sql: {line_count} lines, {len(ns0_page_ids):,} articles, {len(cat_title_to_pageid):,} cat pages")

    log.info(f"  Total: {len(ns0_page_ids):,} articles, {len(cat_title_to_pageid):,} category pages")

    # Map seed category names -> page_ids
    seed_page_ids: set[int] = set()
    for cat_name in SEED_CATEGORIES:
        pid = cat_title_to_pageid.get(cat_name)
        if pid:
            seed_page_ids.add(pid)
        else:
            log.warning(f"  Seed category not found: {cat_name}")

    log.info(f"  {len(seed_page_ids)} seed categories matched to page IDs")

    # Build reverse lookup: page_id -> cat_title (only for categories)
    pageid_to_cat_title: dict[int, str] = {v: k for k, v in cat_title_to_pageid.items()}

    # ── Phase 2: Parse categorylinks -- build subcat tree ──
    # cl_target_id is the page_id of the parent category
    # When cl_type='subcat', cl_from is the page_id of the child category page
    log.info("Phase 2: Building subcategory tree from categorylinks...")
    parent_pid_to_child_pids: dict[int, set[int]] = {}

    with gzip.open(str(catlinks_path), 'rt', encoding='utf-8', errors='replace') as f:
        line_count = 0
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_sql_values(line):
                if len(fields) < 7:
                    continue
                try:
                    cl_from = int(fields[0])
                    cl_type = fields[4]
                    cl_target_id = int(fields[6])
                except (ValueError, IndexError):
                    continue

                if cl_type == 'subcat':
                    parent_pid_to_child_pids.setdefault(cl_target_id, set()).add(cl_from)

            line_count += 1
            if line_count % 200 == 0:
                total_children = sum(len(v) for v in parent_pid_to_child_pids.values())
                log.info(f"  catlinks pass 1: {line_count} lines, {len(parent_pid_to_child_pids):,} parents, {total_children:,} subcat links")

    log.info(f"  {len(parent_pid_to_child_pids):,} parent categories with subcats")

    # ── Phase 3: BFS expand seed categories ──
    log.info(f"Phase 3: BFS expanding from {len(seed_page_ids)} seeds (max depth {MAX_DEPTH})...")
    target_cat_pids: set[int] = set()
    queue = deque([(pid, 0) for pid in seed_page_ids])

    while queue:
        pid, depth = queue.popleft()
        if pid in target_cat_pids:
            continue
        target_cat_pids.add(pid)
        if depth < MAX_DEPTH:
            for child_pid in parent_pid_to_child_pids.get(pid, set()):
                if child_pid not in target_cat_pids:
                    queue.append((child_pid, depth + 1))

    del parent_pid_to_child_pids
    log.info(f"  Expanded to {len(target_cat_pids):,} target categories")

    # ── Phase 4: Second pass of categorylinks -- find articles ──
    log.info("Phase 4: Finding articles in target categories (second catlinks pass)...")
    target_article_ids: set[int] = set()

    with gzip.open(str(catlinks_path), 'rt', encoding='utf-8', errors='replace') as f:
        line_count = 0
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_sql_values(line):
                if len(fields) < 7:
                    continue
                try:
                    cl_from = int(fields[0])
                    cl_type = fields[4]
                    cl_target_id = int(fields[6])
                except (ValueError, IndexError):
                    continue

                if cl_type == 'page' and cl_target_id in target_cat_pids and cl_from in ns0_page_ids:
                    target_article_ids.add(cl_from)

            line_count += 1
            if line_count % 200 == 0:
                log.info(f"  catlinks pass 2: {line_count} lines, {len(target_article_ids):,} matched articles")

    log.info(f"  Found {len(target_article_ids):,} articles in ancient categories")

    # ── Phase 5: Get titles for matched articles ──
    log.info("Phase 5: Getting titles for matched articles...")
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

    # ── Save filter ──
    sample_cats = sorted([pageid_to_cat_title.get(pid, '?') for pid in list(target_cat_pids)[:300]])
    result = {
        "page_ids": sorted(target_article_ids),
        "page_titles": {str(pid): page_titles.get(pid, '') for pid in target_article_ids},
        "category_count": len(target_cat_pids),
        "article_count": len(target_article_ids),
        "sample_categories": sample_cats,
    }

    with open(str(filter_path), 'w') as f:
        json.dump(result, f)

    log.info(f"DONE: {len(target_article_ids):,} articles from {len(target_cat_pids):,} categories")
    log.info(f"Saved to {filter_path}")


if __name__ == '__main__':
    main()
