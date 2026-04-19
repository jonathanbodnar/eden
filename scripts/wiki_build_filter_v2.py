"""Build the ancient article filter from Wikipedia dump files (v2).

Fixed: The binary cl_sortkey field in categorylinks breaks naive SQL parsers and regex.
Solution: Read as raw bytes, split tuples at the known tail pattern
  '(page|subcat|file)',<num>,<num>)
Each tuple reliably ends with this pattern.
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
MAX_DEPTH = 4

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


# Byte-level patterns for the TAIL of each categorylinks tuple.
# Each tuple ends with: '<cl_type>',<collation_id>,<cl_target_id>)
# We read binary and match these byte patterns.
TAIL_RE = re.compile(
    rb"'(page|subcat|file)'"   # cl_type
    rb",(\d+)"                 # cl_collation_id
    rb",(\d+)\)"               # cl_target_id
)

# Pattern to find cl_from at the start of a tuple: (<cl_from>,
HEAD_RE = re.compile(rb"\((\d+),")


def parse_catlinks_bytes(raw_line: bytes):
    """Parse a single INSERT line from categorylinks.sql.gz as raw bytes.
    
    Strategy: find all tail matches (cl_type, collation_id, cl_target_id),
    then walk backwards from each tail to find the corresponding cl_from.
    
    We find tail matches in reverse order and pair each with the nearest
    preceding opening parenthesis + number."""
    
    results = []
    
    # Find all tail matches
    tail_matches = list(TAIL_RE.finditer(raw_line))
    
    for tm in tail_matches:
        cl_type = tm.group(1).decode('ascii')
        cl_target_id = int(tm.group(3))
        
        # Walk backwards from this tail match to find the opening ( with cl_from
        # The tuple starts with (cl_from, so find the last ( before this tail
        search_start = max(0, tm.start() - 500)  # sortkey can be up to 230 bytes
        chunk = raw_line[search_start:tm.start()]
        
        # Find the last opening paren followed by a number
        last_head = None
        for hm in HEAD_RE.finditer(chunk):
            last_head = hm
        
        if last_head:
            cl_from = int(last_head.group(1))
            results.append((cl_from, cl_type, cl_target_id))
    
    return results


def parse_page_values(line):
    """Parse page.sql INSERT line."""
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
    log.info("Phase 1: Parsing page.sql.gz...")
    cat_title_to_pageid: dict[str, int] = {}
    ns0_page_ids: set[int] = set()

    with gzip.open(str(page_path), 'rt', encoding='utf-8', errors='replace') as f:
        line_count = 0
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_page_values(line):
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
            if line_count % 100 == 0:
                log.info(f"  page.sql: {line_count} lines, {len(ns0_page_ids):,} articles, {len(cat_title_to_pageid):,} cats")

    log.info(f"  Total: {len(ns0_page_ids):,} articles, {len(cat_title_to_pageid):,} category pages")

    seed_page_ids: set[int] = set()
    for cat_name in SEED_CATEGORIES:
        pid = cat_title_to_pageid.get(cat_name)
        if pid:
            seed_page_ids.add(pid)
        else:
            log.warning(f"  Seed not found: {cat_name}")

    log.info(f"  {len(seed_page_ids)} seed categories matched")

    pageid_to_cat_title: dict[int, str] = {v: k for k, v in cat_title_to_pageid.items()}
    del cat_title_to_pageid

    # ── Phase 2: Parse categorylinks as RAW BYTES to handle binary sortkey ──
    log.info("Phase 2: Building subcat tree from categorylinks (byte-level parser)...")
    parent_to_children: dict[int, set[int]] = {}

    with gzip.open(str(catlinks_path), 'rb') as f:
        line_count = 0
        subcat_total = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1

            for cl_from, cl_type, cl_target_id in parse_catlinks_bytes(raw_line):
                if cl_type == 'subcat':
                    parent_to_children.setdefault(cl_target_id, set()).add(cl_from)
                    subcat_total += 1

            if line_count % 500 == 0:
                log.info(f"  catlinks: {line_count} lines, {len(parent_to_children):,} parents, {subcat_total:,} subcat links")

    log.info(f"  {len(parent_to_children):,} parents, {subcat_total:,} total subcat links")

    # Sanity checks on known categories
    for test_name in ["Ancient_Egypt", "Mesopotamia", "Ancient_Greece", "Mythology"]:
        test_pid = None
        for pid, name in pageid_to_cat_title.items():
            if name == test_name:
                test_pid = pid
                break
        if test_pid:
            children = parent_to_children.get(test_pid, set())
            child_names = [pageid_to_cat_title.get(c, f'pid={c}') for c in list(children)[:5]]
            log.info(f"  Sanity: {test_name} (pid={test_pid}) -> {len(children)} subcats, sample: {child_names}")

    # ── Phase 3: BFS expand ──
    log.info(f"Phase 3: BFS expanding from {len(seed_page_ids)} seeds (max depth {MAX_DEPTH})...")
    target_cat_pids: set[int] = set()
    queue = deque([(pid, 0) for pid in seed_page_ids])

    while queue:
        pid, depth = queue.popleft()
        if pid in target_cat_pids:
            continue
        target_cat_pids.add(pid)
        if depth < MAX_DEPTH:
            for child_pid in parent_to_children.get(pid, set()):
                if child_pid not in target_cat_pids:
                    queue.append((child_pid, depth + 1))

    del parent_to_children
    log.info(f"  Expanded to {len(target_cat_pids):,} target categories")

    # ── Phase 4: Find articles in target categories (byte-level parser) ──
    log.info("Phase 4: Finding articles in target categories...")
    target_article_ids: set[int] = set()

    with gzip.open(str(catlinks_path), 'rb') as f:
        line_count = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1

            for cl_from, cl_type, cl_target_id in parse_catlinks_bytes(raw_line):
                if cl_type == 'page' and cl_target_id in target_cat_pids and cl_from in ns0_page_ids:
                    target_article_ids.add(cl_from)

            if line_count % 500 == 0:
                log.info(f"  catlinks pass 2: {line_count} lines, {len(target_article_ids):,} articles")

    log.info(f"  Found {len(target_article_ids):,} articles")

    # ── Phase 5: Get titles ──
    log.info("Phase 5: Getting titles for matched articles...")
    page_titles: dict[int, str] = {}

    with gzip.open(str(page_path), 'rt', encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_page_values(line):
                if len(fields) >= 3:
                    try:
                        pid = int(fields[0])
                    except ValueError:
                        continue
                    if pid in target_article_ids:
                        page_titles[pid] = fields[2]

    log.info(f"  Got titles for {len(page_titles):,} articles")

    # ── Save ──
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
