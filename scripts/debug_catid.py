"""Check raw bytes for cl_target_id=48398 (Ancient_Egypt cat_id) in categorylinks."""
import gzip
import re

CATLINKS = "/opt/wiki-dump/categorylinks.sql.gz"
TARGET = b",48398)"

TAIL_RE = re.compile(
    rb"'(page|subcat|file)'"
    rb",(\d+)"
    rb",(\d+)\)"
)

# Simple raw search for the target bytes in the file
page_hits = 0
subcat_hits = 0
raw_hits = 0

with gzip.open(CATLINKS, 'rb') as f:
    line_count = 0
    for raw_line in f:
        if not raw_line.startswith(b"INSERT"):
            continue
        line_count += 1

        if TARGET not in raw_line:
            continue

        # Count raw byte occurrences of ,48398)
        occurrences = raw_line.count(TARGET)
        raw_hits += occurrences

        # Now check via regex
        for tm in TAIL_RE.finditer(raw_line):
            cl_target_id = int(tm.group(3))
            if cl_target_id == 48398:
                cl_type = tm.group(1).decode('ascii')
                if cl_type == 'subcat':
                    subcat_hits += 1
                    if subcat_hits <= 5:
                        # Show surrounding context
                        start = max(0, tm.start() - 30)
                        end = min(len(raw_line), tm.end() + 10)
                        print(f"SUBCAT match at offset {tm.start()}: {repr(raw_line[start:end])}")
                elif cl_type == 'page':
                    page_hits += 1

        if line_count % 5000 == 0:
            print(f"... line {line_count}: {raw_hits} raw, {subcat_hits} subcat, {page_hits} page", flush=True)

print(f"\nDone ({line_count} lines): raw_hits={raw_hits}, subcat={subcat_hits}, page={page_hits}")
