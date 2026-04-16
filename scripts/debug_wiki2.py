"""Debug: Check why BFS only found 137 categories.
Parse categorylinks and look for subcat entries targeting Ancient_Egypt (page_id=722461)."""
import gzip
import sys

CATLINKS = "/opt/wiki-dump/categorylinks.sql.gz"
TARGETS = {722461, 853146}  # Ancient_Egypt and Ancient_Egyptians page_ids


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


subcat_count = 0
page_count = 0
all_subcats_from = []

with gzip.open(CATLINKS, 'rt', encoding='utf-8', errors='replace') as f:
    line_count = 0
    for line in f:
        if not line.startswith("INSERT"):
            continue
        line_count += 1
        for fields in parse_sql_values(line):
            if len(fields) < 7:
                continue
            try:
                cl_target_id = int(fields[6])
            except ValueError:
                continue
            if cl_target_id not in TARGETS:
                continue
            cl_type = fields[4]
            cl_from = fields[0]
            if cl_type == 'subcat':
                subcat_count += 1
                all_subcats_from.append(cl_from)
                if subcat_count <= 15:
                    print(f"SUBCAT: cl_from={cl_from} -> target={cl_target_id}")
            elif cl_type == 'page':
                page_count += 1
        
        if line_count % 5000 == 0:
            print(f"... line {line_count}: {subcat_count} subcats, {page_count} pages", file=sys.stderr, flush=True)

print(f"\nTotal for targets {TARGETS}: {subcat_count} subcats, {page_count} pages")
print(f"All subcat cl_from values: {all_subcats_from[:30]}")
