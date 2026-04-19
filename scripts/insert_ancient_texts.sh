#!/usr/bin/env bash
# Insert ancient historian texts directly into the DB via psql.
# Uses curl to fetch, then psql to insert -- no Python/ORM required.

set -e

PSQL="docker exec -i deploy-postgres-1 psql -U eden -d eden"
TS_ID="bb45f74d-163b-4ee8-9eb6-52fba63e9360"

insert_text() {
  local TITLE="$1"
  local CULTURE="$2"
  local URL="$3"
  local EXT_ID="$4"

  # Check if already inserted
  EXISTS=$($PSQL -At -c "SELECT id FROM source_records WHERE canonical_title = '$TITLE' LIMIT 1")
  if [ -n "$EXISTS" ]; then
    echo "  SKIP (exists): $TITLE"
    return
  fi

  echo "  Fetching: $URL"
  RAW=$(curl -sL --max-time 60 -A "Mozilla/5.0" "$URL" 2>/dev/null)
  if [ -z "$RAW" ]; then
    echo "  FAIL (empty response): $TITLE"
    return
  fi

  # Strip HTML tags using sed, clean up whitespace
  CLEAN=$(echo "$RAW" | sed 's/<[^>]*>//g' | sed 's/&amp;/\&/g; s/&lt;/</g; s/&gt;/>/g; s/&nbsp;/ /g; s/&#[0-9]*;//g' | tr '\r' '\n' | sed '/^[[:space:]]*$/d' | head -c 400000)
  CHARCOUNT=${#CLEAN}

  if [ "$CHARCOUNT" -lt 500 ]; then
    echo "  FAIL (too short: $CHARCOUNT chars): $TITLE"
    return
  fi

  CHECKSUM=$(echo "$CLEAN" | sha256sum | cut -d' ' -f1)
  BYTESIZE=$CHARCOUNT
  R2KEY="manual/${EXT_ID}.txt"

  # Escape single quotes for SQL by doubling them
  TITLE_ESC="${TITLE//\'/\'\'}"
  CULTURE_ESC="${CULTURE//\'/\'\'}"

  # Insert raw_object, source_record, source_version in one transaction
  $PSQL <<ENDSQL
BEGIN;
WITH ro AS (
  INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url, content_type, checksum, byte_size, r2_key, fetched_at)
  VALUES (gen_random_uuid(), '$TS_ID', '$EXT_ID', '$URL', 'text/html', '$CHECKSUM', $BYTESIZE, '$R2KEY', NOW())
  RETURNING id
),
sr AS (
  INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title, culture, source_category, provenance_status, record_status, created_at, updated_at)
  SELECT gen_random_uuid(), ro.id, '$TS_ID', '$TITLE_ESC', '$CULTURE_ESC', 'public_domain_library', 'established', 'published', NOW(), NOW()
  FROM ro
  RETURNING id
)
INSERT INTO source_versions (id, source_record_id, version_type, language, is_preferred, text_extracted, created_at, updated_at)
SELECT gen_random_uuid(), sr.id, 'original', 'English', true, \$TEXT\$$CLEAN\$TEXT\$, NOW(), NOW()
FROM sr;
COMMIT;
ENDSQL

  if [ $? -eq 0 ]; then
    echo "  OK ($CHARCOUNT chars): $TITLE"
  else
    echo "  FAIL (sql error): $TITLE"
  fi
}

echo "=== Inserting Ancient Historian Texts ==="

# --- THUCYDIDES ---
insert_text "Thucydides - History of the Peloponnesian War (Complete)" \
  "Greek" \
  "https://www.gutenberg.org/files/7142/7142-h/7142-h.htm" \
  "pg-7142-thucydides"

# --- POLYBIUS ---
insert_text "Polybius - The Histories, Vol. I" \
  "Greek" \
  "https://www.gutenberg.org/files/44125/44125-h/44125-h.htm" \
  "pg-44125-polybius-1"

insert_text "Polybius - The Histories, Vol. II" \
  "Greek" \
  "https://www.gutenberg.org/files/44126/44126-h/44126-h.htm" \
  "pg-44126-polybius-2"

# --- CASSIUS DIO ---
insert_text "Cassius Dio - Roman History (Dio's Rome), Vol. 1" \
  "Roman" \
  "https://www.gutenberg.org/cache/epub/18047/pg18047-images.html" \
  "pg-18047-cassius-dio-1"

insert_text "Cassius Dio - Roman History (Dio's Rome), Vol. 2" \
  "Roman" \
  "https://www.gutenberg.org/cache/epub/11607/pg11607-images.html" \
  "pg-11607-cassius-dio-2"

insert_text "Cassius Dio - Roman History (Dio's Rome), Vol. 3" \
  "Roman" \
  "https://www.gutenberg.org/cache/epub/10162/pg10162-images.html" \
  "pg-10162-cassius-dio-3"

# --- SUETONIUS ---
insert_text "Suetonius - The Lives of the Twelve Caesars (Complete)" \
  "Roman" \
  "https://www.gutenberg.org/files/6400/6400-h/6400-h.htm" \
  "pg-6400-suetonius"

# --- LIVY ---
insert_text "Livy - The History of Rome, Books 1-8" \
  "Roman" \
  "https://www.gutenberg.org/files/19725/19725-h/19725-h.htm" \
  "pg-19725-livy-1-8"

insert_text "Livy - The History of Rome, Books 9-26" \
  "Roman" \
  "https://www.gutenberg.org/cache/epub/10907/pg10907-images.html" \
  "pg-10907-livy-9-26"

# --- ARRIAN ---
insert_text "Arrian - Anabasis of Alexander (Complete)" \
  "Greek" \
  "https://www.gutenberg.org/files/46976/46976-h/46976-h.htm" \
  "pg-46976-arrian"

# --- APPIAN ---
insert_text "Appian - The Civil Wars, Book I" \
  "Roman" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Appian/Civil_Wars/1*.html" \
  "lacus-appian-cw-1"

insert_text "Appian - The Civil Wars, Book II" \
  "Roman" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Appian/Civil_Wars/2*.html" \
  "lacus-appian-cw-2"

# --- AMMIANUS MARCELLINUS ---
insert_text "Ammianus Marcellinus - Roman History (Complete)" \
  "Roman" \
  "https://www.gutenberg.org/files/28587/28587-h/28587-h.htm" \
  "pg-28587-ammianus"

# --- MANETHO ---
insert_text "Manetho - Aegyptiaca, Book I (History of Egypt, Fragments)" \
  "Egyptian" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/1*.html" \
  "lacus-manetho-1"

insert_text "Manetho - Aegyptiaca, Book II (History of Egypt, Fragments)" \
  "Egyptian" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/2*.html" \
  "lacus-manetho-2"

insert_text "Manetho - Aegyptiaca, Book III (History of Egypt, Fragments)" \
  "Egyptian" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Manetho/History_of_Egypt/3*.html" \
  "lacus-manetho-3"

# --- PLUTARCH - MORALIA ---
insert_text "Plutarch - Moralia: On Isis and Osiris" \
  "Greek/Egyptian" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Plutarch/Moralia/Isis_and_Osiris*/A.html" \
  "lacus-plutarch-isis-osiris"

insert_text "Plutarch - Moralia (Complete, Shilleto translation)" \
  "Greek" \
  "https://www.gutenberg.org/files/23639/23639-h/23639-h.htm" \
  "pg-23639-plutarch-moralia"

# --- CICERO - DE REPUBLICA ---
insert_text "Cicero - De Republica (On the Republic)" \
  "Roman" \
  "https://www.gutenberg.org/files/54161/54161-h/54161-h.htm" \
  "pg-54161-cicero-republica"

# --- AULUS GELLIUS ---
insert_text "Aulus Gellius - Attic Nights, Books I-III" \
  "Roman" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/1*.html" \
  "lacus-gellius-1"

insert_text "Aulus Gellius - Attic Nights, Books V, VII" \
  "Roman" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/5*.html" \
  "lacus-gellius-5"

insert_text "Aulus Gellius - Attic Nights, Books IX-X" \
  "Roman" \
  "https://penelope.uchicago.edu/Thayer/E/Roman/Texts/Gellius/9*.html" \
  "lacus-gellius-9"

# --- DENKARD (ZOROASTRIAN) ---
insert_text "Denkard - Book V: Writings of Adar Frobag (Zoroastrian)" \
  "Zoroastrian/Persian" \
  "https://www.avesta.org/denkard/dk5s.html" \
  "avesta-denkard-5"

insert_text "Denkard - Book IX: Ancient Canon Nasks (Zoroastrian)" \
  "Zoroastrian/Persian" \
  "https://www.avesta.org/denkard/dk9sbe.html" \
  "avesta-denkard-9"

echo ""
echo "=== Updating FTS indexes ==="
docker exec deploy-postgres-1 psql -U eden -d eden -c "
UPDATE source_records SET tsv = to_tsvector('english',
    COALESCE(canonical_title, '') || ' ' || COALESCE(culture, '') || ' ' || COALESCE(origin_place_name, ''))
WHERE tsv IS NULL;
UPDATE source_versions SET tsv = to_tsvector('english', LEFT(text_extracted, 10000))
WHERE text_extracted IS NOT NULL AND text_extracted != '' AND tsv IS NULL;
"

echo "=== Done ==="
