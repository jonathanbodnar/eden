"""Re-ingest Greek/Latin texts from Perseus GitHub where TEI extraction failed."""
import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

TEXTS = [
    {
        "title": "Homer - Iliad (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0012/tlg001/tlg0012.tlg001.perseus-grc2.xml",
    },
    {
        "title": "Homer - Odyssey (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0012/tlg002/tlg0012.tlg002.perseus-grc2.xml",
    },
    {
        "title": "Hesiod - Theogony (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0020/tlg001/tlg0020.tlg001.perseus-grc2.xml",
    },
    {
        "title": "Hesiod - Works and Days (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0020/tlg002/tlg0020.tlg002.perseus-grc2.xml",
    },
    {
        "title": "Josephus - Antiquities of the Jews (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0526/tlg001/tlg0526.tlg001.perseus-grc2.xml",
    },
    {
        "title": "Josephus - The Jewish War (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0526/tlg004/tlg0526.tlg004.perseus-grc2.xml",
    },
    {
        "title": "Eusebius - Ecclesiastical History (Ancient Greek Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg2018/tlg002/tlg2018.tlg002.perseus-grc2.xml",
    },
    {
        "title": "Ovid - Metamorphoses (Latin Original)",
        "url": "https://raw.githubusercontent.com/PerseusDL/canonical-latinLit/master/data/phi0959/phi006/phi0959.phi006.perseus-lat2.xml",
        "language": "Latin",
    },
]


def extract_tei_body(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes)
    body = root.find(".//tei:body", TEI_NS)
    if body is None:
        body = root.find(".//{http://www.tei-c.org/ns/1.0}body")
    if body is None:
        return ""
    text = ET.tostring(body, encoding="unicode", method="text").strip()
    lines = text.split("\n")
    cleaned = "\n".join(line.strip() for line in lines)
    import re
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


async def main():
    pool = await asyncpg.create_pool(
        host="localhost", port=5432, user="eden", password="eden", database="eden",
        min_size=1, max_size=3,
    )

    async with httpx.AsyncClient(timeout=120) as client:
        for t in TEXTS:
            title = t["title"]
            url = t["url"]
            language = t.get("language", "Ancient Greek")

            log.info("Downloading %s ...", title)
            resp = await client.get(url)
            if resp.status_code != 200:
                log.error("  HTTP %d for %s", resp.status_code, url)
                continue

            text = extract_tei_body(resp.content)
            if not text or len(text) < 1000:
                log.error("  Extracted text too short (%d chars) for %s", len(text), title)
                continue
            log.info("  Extracted %d chars", len(text))

            checksum = hashlib.sha256(text.encode()).hexdigest()
            byte_size = len(text.encode("utf-8"))

            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT sv.id as sv_id, sr.id as sr_id
                    FROM source_records sr
                    JOIN source_versions sv ON sv.source_record_id = sr.id
                    WHERE sr.canonical_title = $1
                    LIMIT 1
                """, title)
                if not row:
                    log.warning("  No existing record for %s, skipping", title)
                    continue

                await conn.execute("""
                    UPDATE source_versions
                    SET text_extracted = $1,
                        tsv = setweight(to_tsvector('english', $3), 'A') ||
                              to_tsvector('english', LEFT($1, 10000))
                    WHERE id = $2
                """, text, row["sv_id"], title)

                await conn.execute("""
                    UPDATE raw_objects
                    SET checksum = $1, byte_size = $2
                    WHERE id = (SELECT raw_object_id FROM source_records WHERE id = $3)
                """, checksum, byte_size, row["sr_id"])

                log.info("  Updated %s (sv=%s)", title, row["sv_id"])

            await asyncio.sleep(1)

    await pool.close()
    log.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
