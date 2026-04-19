#!/usr/bin/env python3
"""Apply period keyword dating to undated Wikipedia and OpenAlex records."""
import asyncio
import json
import re
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_BCE_RE = re.compile(r'\b(\d{1,5})\s*(?:BCE|B\.C\.E?\.?|bc)\b', re.IGNORECASE)
_CENTURY_RE = re.compile(
    r'\b(\d{1,2})(?:st|nd|rd|th)\s+century\s*(BCE|B\.C\.E?\.?|BC|CE|C\.E\.?|AD|A\.D\.?)?\b',
    re.IGNORECASE,
)

_PERIOD_KEYWORDS = {
    "predynastic": (-5000, -3100, "Predynastic Egypt"),
    "old kingdom": (-2686, -2181, "Old Kingdom Egypt"),
    "middle kingdom": (-2055, -1650, "Middle Kingdom Egypt"),
    "new kingdom": (-1550, -1069, "New Kingdom Egypt"),
    "bronze age": (-3300, -1200, "Bronze Age"),
    "iron age": (-1200, -550, "Iron Age"),
    "neolithic": (-10000, -3300, "Neolithic"),
    "chalcolithic": (-4500, -3300, "Chalcolithic"),
    "hellenistic": (-323, -31, "Hellenistic Period"),
    "roman empire": (-27, 476, "Roman Empire"),
    "roman period": (-27, 476, "Roman Period"),
    "ptolemaic": (-305, -30, "Ptolemaic Period"),
    "achaemenid": (-550, -330, "Achaemenid Period"),
    "sassanid": (224, 651, "Sassanid Period"),
    "sasanian": (224, 651, "Sasanian Period"),
    "sumerian": (-4500, -1900, "Sumerian Period"),
    "akkadian": (-2334, -2154, "Akkadian Period"),
    "old babylonian": (-2000, -1600, "Old Babylonian Period"),
    "neo-babylonian": (-626, -539, "Neo-Babylonian Period"),
    "neo-assyrian": (-911, -609, "Neo-Assyrian Period"),
    "old assyrian": (-2025, -1750, "Old Assyrian Period"),
    "middle assyrian": (-1392, -934, "Middle Assyrian Period"),
    "ur iii": (-2112, -2004, "Ur III Period"),
    "early dynastic": (-2900, -2350, "Early Dynastic Period"),
    "late period": (-664, -332, "Late Period Egypt"),
    "amarna": (-1353, -1336, "Amarna Period"),
    "minoan": (-2700, -1450, "Minoan Civilization"),
    "mycenaean": (-1600, -1100, "Mycenaean Period"),
    "archaic greece": (-800, -480, "Archaic Greece"),
    "classical greece": (-480, -323, "Classical Greece"),
    "classical period": (-480, -323, "Classical Period"),
    "vedic": (-1500, -500, "Vedic Period"),
    "maurya": (-322, -185, "Maurya Empire"),
    "gupta": (320, 550, "Gupta Empire"),
    "han dynasty": (-206, 220, "Han Dynasty"),
    "shang dynasty": (-1600, -1046, "Shang Dynasty"),
    "zhou dynasty": (-1046, -256, "Zhou Dynasty"),
    "qin dynasty": (-221, -206, "Qin Dynasty"),
    "warring states": (-475, -221, "Warring States Period"),
    "spring and autumn": (-771, -476, "Spring and Autumn Period"),
    "jomon": (-14000, -300, "Jomon Period"),
    "phoenician": (-1500, -300, "Phoenician Civilization"),
    "etruscan": (-900, -100, "Etruscan Civilization"),
    "mesoamerican": (-2000, 1521, "Mesoamerican Civilization"),
    "olmec": (-1500, -400, "Olmec Civilization"),
    "maya": (-2000, 1500, "Maya Civilization"),
    "zapotec": (-700, 1521, "Zapotec Civilization"),
    "hittite": (-1600, -1178, "Hittite Empire"),
    "urartu": (-860, -590, "Urartu Kingdom"),
    "elamite": (-2700, -539, "Elamite Civilization"),
    "nabataean": (-400, 106, "Nabataean Kingdom"),
    "punic": (-814, -146, "Punic Civilization"),
    "carthaginian": (-814, -146, "Carthaginian Civilization"),
    "persepolis": (-518, -330, "Persepolis"),
    "dead sea scrolls": (-250, 70, "Dead Sea Scrolls Era"),
    "ancient egypt": (-3100, -30, "Ancient Egypt"),
    "pharaonic": (-3100, -332, "Pharaonic Egypt"),
    "cuneiform": (-3400, -75, "Cuneiform Era"),
    "hieroglyphic": (-3200, -400, "Hieroglyphic Era"),
    "ancient greek": (-800, -31, "Ancient Greece"),
    "ancient roman": (-753, 476, "Ancient Rome"),
    "ancient rome": (-753, 476, "Ancient Rome"),
    "ancient mesopotamia": (-3500, -539, "Ancient Mesopotamia"),
    "ancient india": (-3000, 550, "Ancient India"),
    "ancient china": (-2100, 220, "Ancient China"),
    "ancient persia": (-550, -330, "Ancient Persia"),
    "ancient israel": (-1200, -63, "Ancient Israel"),
    "buddhist": (-500, 500, "Buddhist Period"),
    "pali canon": (-300, 100, "Pali Canon Era"),
    "torah": (-1200, -400, "Torah Period"),
    "talmud": (-200, 500, "Talmudic Period"),
}


def extract_dates(text, title, tags):
    check = (title or "") + " " + (text or "")[:5000]
    dates = []
    seen = set()
    for m in _BCE_RE.finditer(check):
        year = int(m.group(1))
        if year > 10000 or year == 0:
            continue
        key = f"bce-{year}"
        if key in seen:
            continue
        seen.add(key)
        dates.append((-year, -year, f"ca. {year} BCE"))
    for m in _CENTURY_RE.finditer(check):
        num = int(m.group(1))
        era = (m.group(2) or "").upper().replace(".", "")
        if num > 50:
            continue
        if era in ("BC", "BCE"):
            start, end = -(num * 100), -((num - 1) * 100)
            sfx = "st" if num == 1 else "nd" if num == 2 else "rd" if num == 3 else "th"
            label = f"{num}{sfx} century BCE"
        elif era in ("AD", "CE", ""):
            start, end = (num - 1) * 100, num * 100
            if end > 700:
                continue
            sfx = "st" if num == 1 else "nd" if num == 2 else "rd" if num == 3 else "th"
            label = f"{num}{sfx} century CE"
        else:
            continue
        key = f"cent-{start}-{end}"
        if key in seen:
            continue
        seen.add(key)
        dates.append((start, end, label))
    if dates:
        dates.sort(key=lambda d: d[0])
        return dates[0]

    combined = (title or "").lower() + " " + " ".join(t.lower() for t in (tags or [])) + " " + (text or "")[:2000].lower()
    best = None
    for keyword, (start, end, label) in _PERIOD_KEYWORDS.items():
        if keyword in combined:
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end, label)
    if best:
        return (best[0], best[1], f"ca. {best[2]}")
    return None


async def main():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL", "postgresql://eden:eden@postgres:5432/eden")
    conn = await asyncpg.connect(dsn)

    for source_slug in ['wikipedia-ancient', 'openalex', 'sacred-texts', 'tla-egyptian', 'suttacentral', 'met-museum']:
        source_id = await conn.fetchval(
            "SELECT id FROM trusted_sources WHERE slug = $1", source_slug
        )
        if not source_id:
            continue

        batch_size = 500
        offset = 0
        total_fixed = 0
        total_skip = 0

        while True:
            rows = await conn.fetch("""
                SELECT sr.id, sr.canonical_title,
                       sr.metadata_jsonb->>'text' as text_content,
                       sr.metadata_jsonb->'tags' as tags_json
                FROM source_records sr
                WHERE sr.trusted_source_id = $1
                AND NOT EXISTS (SELECT 1 FROM source_dates sd WHERE sd.source_record_id = sr.id)
                ORDER BY sr.id
                LIMIT $2 OFFSET $3
            """, source_id, batch_size, offset)

            if not rows:
                break

            for row in rows:
                tags = []
                if row['tags_json']:
                    try:
                        t = row['tags_json']
                        tags = json.loads(t) if isinstance(t, str) else t
                    except Exception:
                        pass

                result = extract_dates(row['text_content'], row['canonical_title'], tags)
                if result:
                    start, end, label = result
                    await conn.execute("""
                        INSERT INTO source_dates (id, source_record_id, date_type, date_start, date_end, date_label, dating_confidence)
                        VALUES (gen_random_uuid(), $1, 'composition', $2, $3, $4, 'approximate')
                    """, row['id'], start, end, label)
                    total_fixed += 1
                else:
                    total_skip += 1

            offset += batch_size
            if offset % 5000 == 0:
                logger.info("%s: processed %d, fixed %d, skip %d", source_slug, offset, total_fixed, total_skip)

        logger.info("%s DONE: %d dated, %d undatable", source_slug, total_fixed, total_skip)

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
