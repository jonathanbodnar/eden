#!/usr/bin/env python3
"""
Speed up Wikipedia fetch:
1. Add title pre-filter to skip obviously non-ancient titles before API calls
2. Fetch summary first, check _wiki_is_ancient, only then fetch full data
3. Reduce sleep from 2.0 to 0.5 seconds
"""

filepath = '/opt/eden/src/ingestion/workers/fetch_worker.py'
with open(filepath, 'r') as f:
    content = f.read()

# 1. Add title pre-filter function after the _wiki_is_ancient function
old_extract = 'def _extract_image_urls(html: str, page_url: str) -> list[dict]:'

new_filter_and_extract = '''_MODERN_TITLE_PATTERNS = [
    "football", "soccer", "rugby", "cricket", "basketball", "baseball",
    "hockey", "tennis", "golf", "boxing", "wrestling", "swimming",
    "olympics 19", "olympics 20", "world cup", "premier league",
    "championship 19", "championship 20", "season 19", "season 20",
    "league 19", "league 20", "tournament 19", "tournament 20",
    "election", "politician", "governor", "senator", "congressman",
    "president of", "prime minister", "mayor of",
    "television", "tv series", "tv show", "sitcom", "anime",
    "film)", "movie)", "album)", "song)", "single)",
    "video game", "software", "app)", "website",
    "company)", "corporation", "airline", "railway",
    "school)", "university)", "college)",
    "municipality", "district)", "village)",
    "magazine", "newspaper", "radio station",
    "(band)", "(singer)", "(rapper)", "(actress)", "(actor)",
    "south park", "simpsons", "star trek", "star wars",
]

_MODERN_TITLE_EXACT = {
    "jacqueline de la vega", "mohamad hasan", "welsh-scottish league",
}


def _title_likely_modern(title: str) -> bool:
    """Fast check: reject titles that are obviously not ancient world content."""
    t = title.lower()
    for pattern in _MODERN_TITLE_PATTERNS:
        if pattern in t:
            return True
    # Year ranges like "2000-01" or "1987-88" in title
    import re
    if re.search(r'\\b(1[5-9]\\d\\d|20\\d\\d)[\\-\\u2013]', t):
        return True
    # Titles ending with birth/death years like "(born 1965)"
    if re.search(r'\\(born \\d{4}\\)', t):
        return True
    return False


def _extract_image_urls(html: str, page_url: str) -> list[dict]:'''

content = content.replace(old_extract, new_filter_and_extract)

# 2. Add title pre-filter check at the start of _prefetch_wikipedia
old_fetch_start = '''        title = record.title_hint or record.record_url.split("/wiki/")[-1].replace("_", " ")
        try:
            page = wiki.page(title)
            if not await page.exists():
                return (record, None, f"Wikipedia page does not exist: {title}")

            text = await page.text
            summary = await page.summary'''

new_fetch_start = '''        title = record.title_hint or record.record_url.split("/wiki/")[-1].replace("_", " ")
        if _title_likely_modern(title):
            return (record, None, f"Skipping modern title: {title}")
        try:
            page = wiki.page(title)
            if not await page.exists():
                return (record, None, f"Wikipedia page does not exist: {title}")

            summary = await page.summary
            text = await page.text
            if not _wiki_is_ancient(text, summary):
                return (record, None, f"Skipping modern content: {title}")'''

content = content.replace(old_fetch_start, new_fetch_start)

# 3. Remove the duplicate _wiki_is_ancient check later (it's now done earlier)
old_dupe_check = '''            if not _wiki_is_ancient(text, summary):
                return (record, None, f"Skipping modern content: {title}")

            image_urls'''
new_after_check = '''            image_urls'''
content = content.replace(old_dupe_check, new_after_check)

# 4. Reduce Wikipedia sleep from 2.0 to 0.5
content = content.replace(
    'if source.slug in wiki_slugs:\n                            await asyncio.sleep(2.0)',
    'if source.slug in wiki_slugs:\n                            await asyncio.sleep(0.5)'
)

with open(filepath, 'w') as f:
    f.write(content)
print('Done')
