"""Quick test: parse catlinks as bytes, find subcats of Ancient_Egypt (pid=722461)."""
import gzip
import re
import sys

CATLINKS = "/opt/wiki-dump/categorylinks.sql.gz"
TARGET_PID = 722461  # Ancient_Egypt

TAIL_RE = re.compile(
    rb"'(page|subcat|file)'"
    rb",(\d+)"
    rb",(\d+)\)"
)
HEAD_RE = re.compile(rb"\((\d+),")

subcats = []
pages = 0

with gzip.open(CATLINKS, 'rb') as f:
    line_count = 0
    for raw_line in f:
        if not raw_line.startswith(b"INSERT"):
            continue
        line_count += 1

        for tm in TAIL_RE.finditer(raw_line):
            cl_type = tm.group(1)
            cl_target_id = int(tm.group(3))
            
            if cl_target_id != TARGET_PID:
                continue
            
            search_start = max(0, tm.start() - 500)
            chunk = raw_line[search_start:tm.start()]
            last_head = None
            for hm in HEAD_RE.finditer(chunk):
                last_head = hm
            
            if last_head:
                cl_from = int(last_head.group(1))
                if cl_type == b'subcat':
                    subcats.append(cl_from)
                    if len(subcats) <= 20:
                        print(f"  SUBCAT cl_from={cl_from} -> {TARGET_PID}")
                elif cl_type == b'page':
                    pages += 1

        if line_count % 5000 == 0:
            print(f"... line {line_count}: {len(subcats)} subcats, {pages} pages", file=sys.stderr, flush=True)

print(f"\nTotal: {len(subcats)} subcats, {pages} pages for pid={TARGET_PID}")
if subcats:
    print(f"First 20 subcat cl_from values: {subcats[:20]}")
