"""Debug: find subcategories of Ancient_Egypt (page_id=722461) in categorylinks dump."""
import gzip
import sys

TARGET = "722461"
CATLINKS = "/opt/wiki-dump/categorylinks.sql.gz"

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


subcats = 0
pages = 0
total_lines = 0

with gzip.open(CATLINKS, 'rt', encoding='utf-8', errors='replace') as f:
    for line in f:
        if not line.startswith("INSERT"):
            continue
        total_lines += 1
        for fields in parse_sql_values(line):
            if len(fields) < 7:
                continue
            cl_target = fields[6]
            if cl_target != TARGET:
                continue
            cl_from = fields[0]
            cl_type = fields[4]
            if cl_type == 'subcat':
                subcats += 1
                if subcats <= 10:
                    print(f"  SUBCAT cl_from={cl_from}")
            elif cl_type == 'page':
                pages += 1
        if total_lines % 2000 == 0:
            print(f"  ... scanned {total_lines} lines, {subcats} subcats, {pages} pages for target", file=sys.stderr)
        if subcats > 10 and pages > 10:
            break

print(f"\nResults for cl_target_id={TARGET}: {subcats} subcats, {pages} pages")
