#!/usr/bin/env python3
"""Fix existing OpenAlex records: extract ancient dates from text/title/tags. Uses asyncpg directly."""
import asyncio
import json
import re
import logging
import os

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
}


def extract_bce_dates(text):
    check = (text or "")[:5000]
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
        dates.append({"type": "composition", "start": -year, "end": -year, "label": f"ca. {year} BCE", "confidence": "approximate"})
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
        dates.append({"type": "composition", "start": start, "end": end, "label": label, "confidence": "approximate"})
    if not dates:
        return []
    dates.sort(key=lambda d: d["start"])
    return [dates[0]] if len(dates) == 1 else [dates[0], dates[-1]]


def extract_period_dates(title, tags, text):
    combined = (title or "").lower() + " " + " ".join(t.lower() for t in (tags or [])) + " " + (text or "")[:2000].lower()
    best = None
    for keyword, (start, end, label) in _PERIOD_KEYWORDS.items():
        if keyword in combined:
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end, label)
    if best:
        return [{"type": "composition", "start": best[0], "end": best[1], "label": "ca. " + best[2], "confidence": "approximate"}]
    return []


async def main():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL", "postgresql://eden:eden@postgres:5432/eden")
    conn = await asyncpg.connect(dsn)

    batch_size = 500
    total_fixed = 0
    total_no_date = 0
    offset = 0

    while True:
        rows = await conn.fetch("""
            SELECT sr.id, sr.canonical_title,
                   sr.metadata_jsonb->>'text' as text_content,
                   sr.metadata_jsonb->'tags' as tags_json
            FROM source_records sr
            JOIN trusted_sources ts ON sr.trusted_source_id = ts.id
            WHERE ts.slug = 'openalex'
            AND NOT EXISTS (
                SELECT 1 FROM source_dates sd
                WHERE sd.source_record_id = sr.id AND sd.date_type != 'publication'
            )
            ORDER BY sr.id
            LIMIT $1 OFFSET $2
        """, batch_size, offset)

        if not rows:
            break

        for row in rows:
            sr_id = row['id']
            title = row['canonical_title'] or ""
            text_content = row['text_content'] or ""
            tags_raw = row['tags_json']
            tags = []
            if tags_raw:
                try:
                    tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                except Exception:
                    pass

            ancient_dates = extract_bce_dates(text_content)
            if not ancient_dates:
                ancient_dates = extract_bce_dates(title)
            if not ancient_dates:
                ancient_dates = extract_period_dates(title, tags, text_content)

            if ancient_dates:
                for d in ancient_dates:
                    await conn.execute("""
                        INSERT INTO source_dates (id, source_record_id, date_type, date_start, date_end, date_label, dating_confidence)
                        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)
                    """, sr_id, d["type"], d["start"], d["end"], d["label"], d["confidence"])
                total_fixed += 1
            else:
                total_no_date += 1

        offset += batch_size
        logger.info("Processed %d: %d fixed, %d no ancient date", offset, total_fixed, total_no_date)

    await conn.close()
    logger.info("DONE: %d given ancient dates, %d still undated", total_fixed, total_no_date)


if __name__ == "__main__":
    asyncio.run(main())
