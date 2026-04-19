#!/usr/bin/env python3
"""Fix normalization worker to extract ancient dates instead of using publication years."""

filepath = '/opt/eden/src/ingestion/workers/normalization_worker.py'
with open(filepath, 'r') as f:
    content = f.read()

# 1. Add period keyword mapping before the NormalizationWorker class
old_marker = 'class NormalizationWorker(BaseWorker):'

period_mapping = '''
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
}


def _extract_period_from_keywords(title, tags, text):
    """Assign an ancient date range from known period keywords."""
    combined = (title or "").lower() + " " + " ".join(t.lower() for t in (tags or [])) + " " + (text or "")[:2000].lower()
    best = None
    for keyword, (start, end, label) in _PERIOD_KEYWORDS.items():
        if keyword in combined:
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end, label)
    if best:
        return [{"type": "composition", "start": best[0], "end": best[1], "label": "ca. " + best[2], "confidence": "approximate"}]
    return []


class NormalizationWorker(BaseWorker):'''

content = content.replace(old_marker, period_mapping)

# 2. Fix the date extraction logic
old_date_logic = """        date_entries = meta.get("dates", [])
        if not date_entries and meta.get("text"):
            date_entries = _extract_dates_from_text(
                meta.get("text", ""), meta.get("summary", "")
            )"""

new_date_logic = """        raw_dates = meta.get("dates", [])
        pub_dates = [d for d in raw_dates if d.get("type") == "publication"]
        ancient_dates = [d for d in raw_dates if d.get("type") != "publication"]

        if not ancient_dates:
            text_dates = _extract_dates_from_text(
                meta.get("text", ""), meta.get("summary", "")
            )
            if text_dates:
                ancient_dates = text_dates

        if not ancient_dates:
            title_dates = _extract_dates_from_text(title, "")
            if title_dates:
                ancient_dates = title_dates

        if not ancient_dates:
            tags = meta.get("tags", [])
            period_dates = _extract_period_from_keywords(title, tags, meta.get("text", ""))
            if period_dates:
                ancient_dates = period_dates

        date_entries = ancient_dates"""

content = content.replace(old_date_logic, new_date_logic)

with open(filepath, 'w') as f:
    f.write(content)
print('Done')
