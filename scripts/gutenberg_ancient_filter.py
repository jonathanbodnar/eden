"""
Download Gutenberg catalog, filter for ancient/classical texts pre-500CE,
and generate a list of books to ingest into Eden.

The catalog CSV has columns: Text#, Type, Issued, Title, Language, Authors,
Subjects, LoCC, Bookshelves

Run locally -- outputs a JSON file of ancient books to fetch.
"""

import csv
import gzip
import json
import re
import ssl
import urllib.request
import io
from pathlib import Path

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"

# Exact subject strings that must match (case-insensitive substring match)
ANCIENT_SUBJECTS_STRONG = {
    'History, Ancient',
    'Classical literature',
    'Epic poetry, Greek',
    'Epic poetry, Latin',
    'Mythology, Greek',
    'Mythology, Roman',
    'Mythology, Egyptian',
    'Mythology, Babylonian',
    'Mythology, Assyrian',
    'Mythology, Norse',
    'Mythology, Celtic',
    'Mythology, Indic',
    'Mythology, Persian',
    'Mythology, Chinese',
    'Mythology, Japanese',
    'Mythology, Aztec',
    'Mythology, Maya',
    'Mythology, Sumerian',
    'Cosmogony',
    'Creation myths',
    'Civilization, Ancient',
    'Civilization, Classical',
    'Egypt -- History -- To 640',
    'Greece -- History',
    'Rome -- History',
    'Philosophy, Ancient',
    'Vedic literature',
    'Zoroastrianism',
    'Babylonia',
    'Assyria',
    'Sumerians',
    'Cuneiform inscriptions',
}

# Named ancient authors (these are reliable signals)
ANCIENT_AUTHORS = [
    'Homer', 'Hesiod', 'Thucydides', 'Herodotus', 'Xenophon', 'Polybius',
    'Livy', 'Tacitus', 'Suetonius', 'Plutarch', 'Josephus', 'Strabo',
    'Pausanias', 'Appian', 'Arrian', 'Cassius Dio', 'Ammianus Marcellinus',
    'Diodorus Siculus', 'Diogenes Laertius', 'Aelian', 'Athenaeus', 'Pliny the Elder',
    'Pliny the Younger', 'Cicero', 'Julius Caesar', 'Sallust', 'Virgil',
    'Ovid', 'Horace', 'Juvenal', 'Seneca', 'Plautus', 'Terence',
    'Aeschylus', 'Sophocles', 'Euripides', 'Aristophanes',
    'Plato', 'Aristotle', 'Pindar', 'Theocritus', 'Apollonius of Rhodes',
    'Lucian of Samosata', 'Porphyry', 'Iamblichus', 'Proclus', 'Plotinus',
    'Manetho', 'Philo', 'Origen', 'Tertullian', 'Augustine', 'Eusebius',
    'Aulus Gellius', 'Varro', 'Columella', 'Quintilian', 'Frontinus',
    'Vitruvius', 'Vegetius', 'Macrobius', 'Boethius', 'Epictetus',
    'Marcus Aurelius', 'Dio Chrysostom', 'Velleius Paterculus', 'Florus',
    'Eutropius', 'Pompeius Trogus', 'Justin (historian)',
    'Valerius Maximus', 'Quintus Curtius', 'Quintus of Smyrna',
    'Claudian', 'Statius', 'Silius Italicus', 'Lucan',
    'Nonnus', 'Oppian', 'Dionysius of Halicarnassus',
]

# Only match English texts
WANTED_LANGUAGES = {'en', 'en_US', 'en_GB'}


def is_ancient(row: dict) -> bool:
    """Strict filter: only genuine ancient/classical texts in English translation."""
    subjects = row.get('Subjects', '')
    authors = row.get('Authors', '')
    title = row.get('Title', '')
    lang = row.get('Language', 'en')
    bookshelves = row.get('Bookshelves', '')

    # Language filter
    if lang not in WANTED_LANGUAGES:
        return False

    subjects_lower = subjects.lower()
    authors_lower = authors.lower()
    title_lower = title.lower()
    bookshelves_lower = bookshelves.lower()

    # Hard exclude modern genres
    modern_subjects = [
        'detective', 'mystery', 'science fiction', 'adventure stories',
        'sea stories', 'western stories', 'humor', 'juvenile fiction',
        'children', 'love stories', 'american fiction', 'english fiction',
        'short stories', 'fairy tales', 'ghost stories', 'horror tales',
    ]
    for ms in modern_subjects:
        if ms in subjects_lower:
            return False

    # Hard exclude modern authors (using birth year patterns after 1600)
    # Gutenberg format: "Author, Name, YYYY-YYYY" -- exclude birth after 1500
    birth_match = re.search(r', (\d{4})-', authors)
    if birth_match:
        birth_year = int(birth_match.group(1))
        if birth_year > 650:  # post-classical period (after ~650 CE)
            # But allow if it has strong ancient subject tag
            has_strong_subject = any(s.lower() in subjects_lower for s in ANCIENT_SUBJECTS_STRONG)
            if not has_strong_subject:
                return False

    # Check strong ancient subjects (very reliable)
    for s in ANCIENT_SUBJECTS_STRONG:
        if s.lower() in subjects_lower:
            return True

    # Check known ancient authors (must be an actual name match, not substring catch-alls)
    for a in ANCIENT_AUTHORS:
        # Match as whole word / significant part of author field
        if re.search(rf'\b{re.escape(a)}\b', authors, re.IGNORECASE):
            return True

    # Classical bookshelves
    classical_shelves = ['classical antiquity', 'ancient history', 'ancient greece',
                         'ancient rome', 'ancient egypt', 'ancient texts',
                         'classical literature', 'greek mythology', 'roman mythology',
                         'norse mythology', 'celtic mythology', 'vedic texts',
                         'sacred texts of the east']
    for s in classical_shelves:
        if s in bookshelves_lower:
            return True

    return False


def main():
    print(f"Downloading Gutenberg catalog from {CATALOG_URL}...")
    with urllib.request.urlopen(CATALOG_URL, context=ssl_ctx) as response:
        gz_data = response.read()

    print("Parsing catalog...")
    with gzip.open(io.BytesIO(gz_data), 'rt', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    print(f"Total books in catalog: {len(all_rows):,}")

    ancient = [r for r in all_rows if is_ancient(r)]
    print(f"Ancient/classical texts found: {len(ancient):,}")

    # Sort by subject relevance
    ancient.sort(key=lambda r: r.get('Title', ''))

    # Build output with download URLs
    output = []
    for r in ancient:
        num = r.get('Text#', '').strip()
        if not num or not num.isdigit():
            continue
        output.append({
            "gutenberg_id": int(num),
            "title": r.get('Title', '').strip(),
            "authors": r.get('Authors', '').strip(),
            "language": r.get('Language', 'en'),
            "subjects": r.get('Subjects', '').strip(),
            "bookshelves": r.get('Bookshelves', '').strip(),
            "issued": r.get('Issued', '').strip(),
            "txt_url": f"https://www.gutenberg.org/files/{num}/{num}-0.txt",
            "html_url": f"https://www.gutenberg.org/files/{num}/{num}-h/{num}-h.htm",
        })

    # Save to file
    out_path = Path(__file__).parent / 'gutenberg_ancient_list.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved {len(output)} books to {out_path}")
    print("\nTop 50 ancient texts found:")
    for book in output[:50]:
        print(f"  [{book['gutenberg_id']:>6}] {book['title'][:60]} | {book['authors'][:40]}")

    # Summary by subject category
    print("\nSubject breakdown (top 20):")
    from collections import Counter
    all_subjects = []
    for r in ancient:
        for s in r.get('Subjects', '').split(';'):
            s = s.strip()
            if s:
                all_subjects.append(s)
    for s, c in Counter(all_subjects).most_common(20):
        print(f"  {c:>5}x  {s}")


if __name__ == '__main__':
    main()
