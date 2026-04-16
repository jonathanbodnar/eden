"""Build the ancient article filter from Wikipedia dump files (v3).

Key insight: cl_target_id = cat_id (from category table), NOT page_id.
For subcat links: cl_from = page_id of child category page (ns=14).
Must map page_id -> cat_title -> cat_id to traverse the tree.

categorylinks schema:
  (cl_from INT, cl_sortkey VARBINARY, cl_timestamp TIMESTAMP,
   cl_sortkey_prefix VARBINARY, cl_type ENUM, cl_collation_id SMALLINT,
   cl_target_id BIGINT)
where cl_target_id references category.cat_id
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

TAIL_RE = re.compile(
    rb"'(page|subcat|file)'"
    rb",(\d+)"
    rb",(\d+)\)"
)
HEAD_RE = re.compile(rb"\((\d+),")


def parse_catlinks_bytes(raw_line: bytes):
    """Parse catlinks INSERT line as raw bytes.
    Returns (cl_from, cl_type_str, cl_target_id) tuples."""
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


def parse_category_values(line):
    """Parse category.sql INSERT line. Fields: (cat_id, cat_title, ...)"""
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
    category_path = Path(DUMP_DIR) / "category.sql.gz"
    page_path = Path(DUMP_DIR) / "page.sql.gz"
    filter_path = Path(DUMP_DIR) / "ancient_page_ids.json"

    # ── Phase 1a: Parse category.sql -> cat_id <-> cat_title ──
    log.info("Phase 1a: Parsing category.sql.gz...")
    catid_to_name: dict[int, str] = {}
    name_to_catid: dict[str, int] = {}

    with gzip.open(str(category_path), 'rt', encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith("INSERT"):
                continue
            for fields in parse_category_values(line):
                if len(fields) >= 2:
                    try:
                        cat_id = int(fields[0])
                    except ValueError:
                        continue
                    cat_name = fields[1]
                    catid_to_name[cat_id] = cat_name
                    name_to_catid[cat_name] = cat_id

    log.info(f"  Loaded {len(catid_to_name):,} categories")

    seed_cat_ids: set[int] = set()
    for name in SEED_CATEGORIES:
        cid = name_to_catid.get(name)
        if cid:
            seed_cat_ids.add(cid)
        else:
            log.warning(f"  Seed not found: {name}")

    log.info(f"  {len(seed_cat_ids)} seed cat_ids matched")

    # Sanity
    for name in ["Ancient_Egypt", "Mesopotamia", "Mythology"]:
        cid = name_to_catid.get(name)
        if cid:
            log.info(f"  {name} -> cat_id={cid}")

    # ── Phase 1b: Parse page.sql.gz -> ns0 page_ids and page_id -> cat_title for ns=14 ──
    log.info("Phase 1b: Parsing page.sql.gz...")
    ns0_page_ids: set[int] = set()
    pageid_to_cattitle: dict[int, str] = {}  # for ns=14 category pages

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
                if ns == 0:
                    ns0_page_ids.add(pid)
                elif ns == 14:
                    pageid_to_cattitle[pid] = fields[2]
            line_count += 1
            if line_count % 100 == 0:
                log.info(f"  page.sql: {line_count} lines, {len(ns0_page_ids):,} articles, {len(pageid_to_cattitle):,} cat pages")

    log.info(f"  Total: {len(ns0_page_ids):,} articles, {len(pageid_to_cattitle):,} cat pages")

    # ── Phase 2: Parse categorylinks (byte-level) -> build subcat tree on cat_ids ──
    # For subcat entries: cl_target_id is parent cat_id, cl_from is child page_id
    # Map child page_id -> cat_title -> cat_id to get the child cat_id
    log.info("Phase 2: Building subcat tree from categorylinks...")
    parent_catid_to_children: dict[int, set[int]] = {}

    with gzip.open(str(catlinks_path), 'rb') as f:
        line_count = 0
        subcat_total = 0
        mapped = 0
        unmapped = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1

            for cl_from, cl_type, cl_target_id in parse_catlinks_bytes(raw_line):
                if cl_type != 'subcat':
                    continue
                subcat_total += 1

                # cl_target_id = parent cat_id (already what we want)
                parent_cat_id = cl_target_id

                # cl_from = page_id of child category page
                child_title = pageid_to_cattitle.get(cl_from)
                if child_title is None:
                    unmapped += 1
                    continue
                child_cat_id = name_to_catid.get(child_title)
                if child_cat_id is None:
                    unmapped += 1
                    continue

                parent_catid_to_children.setdefault(parent_cat_id, set()).add(child_cat_id)
                mapped += 1

            if line_count % 500 == 0:
                log.info(f"  catlinks: {line_count} lines, {subcat_total:,} subcats, {mapped:,} mapped, {unmapped:,} unmapped")

    log.info(f"  {len(parent_catid_to_children):,} parents, {mapped:,} mapped subcat links ({unmapped:,} unmapped)")

    # Sanity checks
    for name in ["Ancient_Egypt", "Mesopotamia", "Mythology", "Ancient_Greece"]:
        cid = name_to_catid.get(name)
        if cid:
            children = parent_catid_to_children.get(cid, set())
            child_names = [catid_to_name.get(c, f'?{c}') for c in list(children)[:8]]
            log.info(f"  Sanity: {name} (cat_id={cid}) -> {len(children)} subcats: {child_names}")

    # Free large lookups
    del pageid_to_cattitle, name_to_catid

    # ── Phase 3: BFS expand on cat_ids ──
    log.info(f"Phase 3: BFS expanding from {len(seed_cat_ids)} seeds (max depth {MAX_DEPTH})...")
    target_cat_ids: set[int] = set()
    queue = deque([(cid, 0) for cid in seed_cat_ids])

    while queue:
        cid, depth = queue.popleft()
        if cid in target_cat_ids:
            continue
        target_cat_ids.add(cid)
        if depth < MAX_DEPTH:
            for child_cid in parent_catid_to_children.get(cid, set()):
                if child_cid not in target_cat_ids:
                    queue.append((child_cid, depth + 1))

    del parent_catid_to_children
    log.info(f"  Expanded to {len(target_cat_ids):,} target categories")

    sample = sorted([catid_to_name.get(c, '?') for c in list(target_cat_ids)[:30]])
    log.info(f"  Sample: {sample}")

    # ── Phase 4: Find articles in target categories ──
    log.info("Phase 4: Finding articles in target categories...")
    target_article_ids: set[int] = set()

    with gzip.open(str(catlinks_path), 'rb') as f:
        line_count = 0
        for raw_line in f:
            if not raw_line.startswith(b"INSERT"):
                continue
            line_count += 1

            for cl_from, cl_type, cl_target_id in parse_catlinks_bytes(raw_line):
                if cl_type == 'page' and cl_target_id in target_cat_ids and cl_from in ns0_page_ids:
                    target_article_ids.add(cl_from)

            if line_count % 500 == 0:
                log.info(f"  catlinks pass 2: {line_count} lines, {len(target_article_ids):,} articles")

    log.info(f"  Found {len(target_article_ids):,} articles")

    # ── Phase 5: Get titles for matched articles ──
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
    sample_cats = sorted([catid_to_name.get(c, '?') for c in list(target_cat_ids)[:300]])
    result = {
        "page_ids": sorted(target_article_ids),
        "page_titles": {str(pid): page_titles.get(pid, '') for pid in target_article_ids},
        "category_count": len(target_cat_ids),
        "article_count": len(target_article_ids),
        "sample_categories": sample_cats,
    }

    with open(str(filter_path), 'w') as f:
        json.dump(result, f)

    log.info(f"DONE: {len(target_article_ids):,} articles from {len(target_cat_ids):,} categories")
    log.info(f"Saved to {filter_path}")


if __name__ == '__main__':
    main()
