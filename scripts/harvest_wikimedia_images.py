"""Harvest images from Wikimedia Commons for all visual library artifacts.
Searches Commons for each artifact, downloads image metadata, and stores in object_images."""
import asyncio
import logging
import re
import urllib.parse

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
MAX_IMAGES_PER_ARTIFACT = 8
SEARCH_DELAY = 0.5

SEARCH_TERMS = {
    "Göbekli Tepe Pillar Reliefs": ["Göbekli Tepe pillar relief", "Göbekli Tepe carving"],
    "Göbekli Tepe Pillar 43 (Vulture Stone)": ["Göbekli Tepe Pillar 43 vulture", "Göbekli Tepe vulture stone"],
    "Karahan Tepe Human Sculptures": ["Karahan Tepe sculpture", "Karahan Tepe excavation"],
    "Sayburç Narrative Relief": ["Sayburç relief", "Sayburc neolithic"],
    "Nevali Çori T-Pillars": ["Nevali Cori pillar", "Nevali Çori sculpture"],
    "Ain Ghazal Plaster Statues": ["Ain Ghazal statue", "'Ain Ghazal plaster"],
    "Jericho Tower and Plastered Skulls": ["Jericho tower neolithic", "Jericho plastered skull"],
    "Çatalhöyük Murals and Shrines": ["Çatalhöyük mural", "Catalhoyuk fresco shrine"],
    "Nabta Playa Stone Circle": ["Nabta Playa stone circle"],
    "Nabta Playa Cattle Burials": ["Nabta Playa megalith"],
    'Tassili n\'Ajjer "Round Head" Paintings': ["Tassili n'Ajjer round head", "Tassili rock art painting"],
    'Tassili n\'Ajjer "Swimming Figures"': ["Tassili swimming figures", "Tassili n'Ajjer rock painting"],
    "Ennedi Plateau Rock Art": ["Ennedi rock art", "Ennedi plateau painting"],
    "Bhimbetka Rock Paintings": ["Bhimbetka rock painting", "Bhimbetka cave art"],
    "Chauvet Cave Paintings": ["Chauvet cave painting", "Grotte Chauvet"],
    "Lascaux Cave Paintings": ["Lascaux cave painting", "Lascaux bull"],
    "Altamira Cave Paintings": ["Altamira cave bison", "Altamira cave painting"],
    "Val Camonica Petroglyphs": ["Val Camonica petroglyph", "Valcamonica rock art"],
    "Alta Rock Carvings": ["Alta rock carving Norway", "Alta petroglyph"],
    "Newgrange Spiral Carvings": ["Newgrange spiral kerbstone", "Newgrange entrance stone"],
    "Knowth Megalithic Art": ["Knowth megalithic art", "Knowth kerbstone"],
    "Stonehenge and Aubrey Holes": ["Stonehenge aerial", "Stonehenge monument"],
    "Durrington Walls Settlement": ["Durrington Walls", "Durrington Walls excavation"],
    "Skara Brae Village": ["Skara Brae village", "Skara Brae interior"],
    "Carnac Stones": ["Carnac stones alignment", "Carnac menhir"],
    "Proto-Cuneiform Tablets": ["proto-cuneiform tablet Uruk", "Uruk tablet pictographic"],
    "Uruk Pictograph Tablets": ["Uruk pictograph tablet", "early cuneiform tablet"],
    "Warka Vase": ["Warka Vase", "Uruk Vase alabaster"],
    "Cylinder Seal Impressions": ["Mesopotamian cylinder seal", "cylinder seal impression Ur"],
    "Royal Tomb of Ur Artifacts": ["Royal Cemetery Ur gold", "Queen Puabi headdress"],
    "Bull-Headed Lyre of Ur": ["Bull headed lyre Ur", "lyre Ur gold"],
    "Standard of Ur": ["Standard of Ur war peace", "Standard of Ur mosaic"],
    "Stele of the Vultures": ["Stele of the Vultures", "Stele Vultures Lagash"],
    "Victory Stele of Naram-Sin": ["Victory Stele Naram-Sin", "Naram-Sin stele Louvre"],
    "Burney Relief (Queen of the Night)": ["Burney Relief", "Queen of the Night relief Babylon"],
    "Kudurru Boundary Stones": ["Kudurru stone Babylon", "Kudurru boundary stone"],
    "Assyrian Palace Reliefs": ["Assyrian palace relief Nineveh", "Assyrian relief Nimrud"],
    "Winged Genies Reliefs": ["Assyrian winged genie relief", "Apkallu relief Nimrud"],
    "Lamassu Statues": ["Lamassu statue Assyrian", "Lamassu Khorsabad"],
    "Narmer Palette": ["Narmer Palette", "Narmer Palette both sides"],
    "Saqqara Tomb Paintings": ["Saqqara tomb painting mastaba", "Saqqara Old Kingdom painting"],
    "Beni Hasan Tomb Scenes": ["Beni Hasan tomb painting", "Beni Hasan wrestling"],
    "Great Pyramid Interior": ["Great Pyramid interior passage", "Great Pyramid grand gallery"],
    "Solar Boat (Khufu Ship)": ["Khufu ship solar boat", "Khufu boat museum"],
    "Valley of the Kings Murals": ["Valley of the Kings tomb painting", "KV tomb mural"],
    "Seti I Tomb Astronomical Ceiling": ["Seti I tomb ceiling astronomical", "KV17 ceiling"],
    "Book of Caverns Reliefs": ["Book of Caverns tomb relief", "Egyptian underworld painting"],
    "Temple of Karnak Reliefs": ["Karnak temple relief", "Karnak hypostyle hall"],
    "Temple of Luxor": ["Luxor temple colonnade", "Luxor temple Ramesses"],
    "Temple of Edfu": ["Edfu temple Horus", "Temple Edfu pylon"],
    "Temple of Dendera Ceiling": ["Dendera zodiac ceiling", "Dendera temple ceiling"],
    "Abydos Temple Reliefs": ["Abydos temple Seti relief", "Abydos king list"],
    "Osireion Megalithic Structure": ["Osireion Abydos", "Osireion granite"],
    "Canopic Chest Decoration": ["Canopic chest Egyptian", "Tutankhamun canopic"],
    "Book of the Dead Papyri": ["Book of Dead papyrus weighing heart", "Papyrus Ani"],
    "Mohenjo-Daro City Layout": ["Mohenjo-daro aerial ruins", "Mohenjo-daro excavation"],
    "Harappa Granary Complex": ["Harappa granary", "Harappa excavation"],
    "Great Bath of Mohenjo-Daro": ["Great Bath Mohenjo-daro", "Mohenjo-daro great bath"],
    "Indus Valley Animal Seals": ["Indus Valley seal unicorn", "Harappan seal animal"],
    "Pashupati Seal": ["Pashupati seal Mohenjo-daro", "proto-Shiva seal"],
    "Dancing Girl Statue": ["Dancing Girl Mohenjo-daro bronze", "Dancing Girl statue Indus"],
    "Priest-King Statue": ["Priest King Mohenjo-daro", "Priest King statue Indus"],
    "Ajanta Cave Paintings": ["Ajanta cave painting", "Ajanta Padmapani"],
    "Sanchi Gateway Reliefs": ["Sanchi stupa gateway torana", "Sanchi relief"],
    "Bharhut Reliefs": ["Bharhut relief stupa", "Bharhut Jataka"],
    "Oracle Bone Inscriptions": ["Oracle bone inscription Shang", "oracle bone Chinese"],
    "Shang Bronze Ding Vessels": ["Shang bronze ding vessel", "Chinese bronze ritual vessel"],
    "Sanxingdui Bronze Figures": ["Sanxingdui bronze figure", "Sanxingdui bronze mask"],
    "Sanxingdui Gold Mask": ["Sanxingdui gold mask", "Sanxingdui golden mask"],
    "Liangzhu Jade Cong": ["Liangzhu jade cong", "jade cong tube"],
    "Terracotta Army": ["Terracotta Army Xi'an", "Terracotta warriors pit"],
    "Mawangdui Silk Banner (T-shaped)": ["Mawangdui silk banner", "Mawangdui T-shaped painting"],
    "Han Dynasty Tomb Murals": ["Han dynasty tomb mural", "Han tomb painting"],
    "Knossos Bull-Leaping Fresco": ["Knossos bull leaping fresco", "Minoan bull leaping"],
    "Akrotiri Frescoes": ["Akrotiri fresco Santorini", "Akrotiri spring fresco"],
    "Mycenaean Warrior Vase": ["Mycenaean warrior vase", "warrior vase Mycenae"],
    "Lion Gate": ["Lion Gate Mycenae", "Mycenae lion gate"],
    "Greek Black-Figure Pottery": ["Greek black figure pottery", "Exekias Ajax Achilles"],
    "Greek Red-Figure Pottery": ["Greek red figure pottery", "Attic red figure vase"],
    "Delphi Bronze Charioteer": ["Delphi charioteer bronze", "Charioteer of Delphi"],
    "Parthenon Friezes": ["Parthenon frieze marble", "Parthenon Elgin marbles"],
    "Pompeii Frescoes (Villa of Mysteries)": ["Villa of Mysteries fresco Pompeii", "Pompeii fresco"],
    "Pompeii Graffiti": ["Pompeii graffiti", "Pompeii wall inscription"],
    "Roman Lararium Shrines": ["Roman lararium shrine Pompeii", "lararium painting"],
    "Roman Mosaics": ["Roman mosaic Alexander", "Roman floor mosaic"],
    "Olmec Colossal Heads": ["Olmec colossal head", "Olmec head basalt"],
    "Olmec Jade Celts": ["Olmec jade celt", "Olmec Kunz Axe"],
    "La Venta Altars (Thrones)": ["La Venta altar throne", "La Venta Olmec altar"],
    "Monte Albán Danzantes Reliefs": ["Monte Alban danzantes", "Monte Alban carved slab"],
    "Izapa Stelae": ["Izapa stele", "Izapa stela 5"],
    "Teotihuacan Jaguar Murals": ["Teotihuacan jaguar mural", "Teotihuacan Tepantitla"],
    "Feathered Serpent Pyramid Sculptural Heads": ["Feathered Serpent Pyramid Teotihuacan", "Quetzalcoatl pyramid head"],
    "Maya Hieroglyphic Stairway of Copán": ["Copan hieroglyphic stairway", "Copan Maya glyphs"],
    "Maya Ball Court Reliefs": ["Maya ball court relief", "Chichen Itza ball court"],
    "Maya Painted Ceramic Scenes": ["Maya painted vase ceramic", "Maya polychrome vase"],
    "Maya Bloodletting Scenes": ["Yaxchilan lintel 24", "Maya bloodletting relief"],
    "Palenque Sarcophagus Lid (Pacal)": ["Palenque sarcophagus lid Pacal", "Pacal tomb lid"],
    "Bonampak Murals": ["Bonampak mural painting", "Bonampak battle scene"],
    "Caral Sunken Plaza": ["Caral sunken plaza Peru", "Caral archaeological site"],
    "Caral Pyramid Complex": ["Caral pyramid Peru", "Caral Norte Chico"],
    "Chavín Tenon Heads": ["Chavin tenon head", "Chavin de Huantar head"],
    "Chavín Underground Galleries": ["Chavin underground gallery", "Chavin de Huantar interior"],
    "Lanzón Monolith": ["Lanzon monolith Chavin", "Chavin Lanzon stone"],
    "Paracas Burial Bundles": ["Paracas burial bundle mummy", "Paracas necropolis"],
    "Paracas Textiles": ["Paracas textile embroidery", "Paracas mantle"],
    "Nazca Geoglyphs (Nazca Lines)": ["Nazca lines aerial", "Nazca geoglyph hummingbird"],
    "Moche Pottery Scenes": ["Moche pottery portrait vessel", "Moche stirrup spout"],
    "Moche Sacrifice Murals": ["Moche sacrifice mural", "Huaca de la Luna mural"],
    "Nok Terracotta Sculptures": ["Nok terracotta sculpture", "Nok head Nigeria"],
    "Axum (Aksum) Stelae": ["Aksum stele obelisk", "Axum stele Ethiopia"],
    "Nubian Pyramids of Meroë": ["Meroe pyramids Sudan", "Nubian pyramids"],
    "Arnhem Land Rock Art": ["Arnhem Land rock art", "Ubirr rock painting"],
    "Kakadu Rock Art": ["Kakadu rock art", "Nourlangie rock painting"],
    "Wandjina Paintings": ["Wandjina rock painting", "Wandjina Kimberley"],
    "Bradshaw (Gwion Gwion) Rock Art": ["Bradshaw rock art Kimberley", "Gwion Gwion painting"],
    "Nan Madol": ["Nan Madol ruins Pohnpei", "Nan Madol basalt"],
    "Baalbek Trilithon": ["Baalbek trilithon stone", "Baalbek temple Jupiter"],
    "Puma Punku Stonework": ["Puma Punku stone block", "Puma Punku Tiwanaku"],
    "Göbekli Tepe Enclosure D (Full Architectural Layout)": ["Göbekli Tepe enclosure D aerial", "Göbekli Tepe excavation"],
    "Göbekli Tepe Pillar 18 (Central Monolith Pair)": ["Göbekli Tepe central pillar", "Göbekli Tepe pillar 18"],
    "Jericho Neolithic City Wall": ["Jericho neolithic wall tower", "Tell es-Sultan wall"],
    "Çatalhöyük Rooftop Entry Architecture": ["Çatalhöyük reconstruction rooftop", "Catalhoyuk house"],
    "Çatalhöyük Streetless Urban Layout": ["Çatalhöyük excavation aerial", "Catalhoyuk houses"],
    "Nabta Playa Megalith Alignments (Astronomical)": ["Nabta Playa megalith", "Nabta Playa alignment"],
    'Tassili n\'Ajjer "Cattle Period" Pastoral Scenes': ["Tassili cattle painting", "Tassili pastoral rock art"],
    "Val Camonica Solar Symbol Petroglyphs": ["Valcamonica solar symbol", "Val Camonica sun petroglyph"],
    "Alta Boat Procession Carvings": ["Alta rock carving boat", "Alta petroglyph boat"],
    "Newgrange Interior Passage Alignment (Winter Solstice Light)": ["Newgrange passage interior", "Newgrange solstice light"],
    "Uruk City Wall Foundations": ["Uruk city wall ruins", "Warka Uruk excavation"],
    "Ziggurat of Ur": ["Ziggurat of Ur", "Ur ziggurat reconstruction"],
    "Eridu Temple Layer Sequence": ["Eridu temple excavation", "Tell Abu Shahrain"],
    "Ishtar Gate (Reconstructed and Original Fragments)": ["Ishtar Gate Berlin Pergamon", "Ishtar Gate dragon bull"],
    "Saqqara Step Pyramid Complex (Full Layout)": ["Step Pyramid Saqqara complex", "Djoser pyramid aerial"],
    "Giza Plateau Full Layout": ["Giza plateau aerial pyramids", "Giza pyramids sphinx"],
    "Khafre Valley Temple Megalithic Blocks": ["Khafre valley temple interior", "Khafre temple granite"],
    "Mohenjo-Daro Covered Street Drainage System": ["Mohenjo-daro drain street", "Mohenjo-daro drainage"],
    "Dholavira Water Reservoir System": ["Dholavira reservoir", "Dholavira water system"],
    "Barabar Cave Polished Granite Interiors": ["Barabar cave interior", "Lomas Rishi cave"],
    "Sanxingdui Ritual Pit Layout": ["Sanxingdui pit excavation", "Sanxingdui ritual pit"],
    "Knossos Multi-Level Palace Layout": ["Knossos palace ruins", "Knossos throne room"],
    "Akrotiri Multi-Story Buildings": ["Akrotiri excavation buildings", "Akrotiri ruins Santorini"],
    "Roman Concrete Harbor Structures (Cosa and Ostia)": ["Roman concrete harbor", "Portus Ostia harbor"],
    "Teotihuacan Avenue of the Dead (Full Axial Layout)": ["Teotihuacan Avenue Dead aerial", "Teotihuacan pyramid sun"],
    "Teotihuacan Residential Compounds": ["Teotihuacan apartment compound", "Teotihuacan Tetitla mural"],
    "Maya Sacbe (Raised White Road Systems)": ["Maya sacbe causeway", "Coba sacbe road"],
    "Tikal Acropolis Complex": ["Tikal temple aerial", "Tikal acropolis Guatemala"],
    "Caral Residential Complexes": ["Caral residential area", "Caral settlement Peru"],
    "Caral Irrigation Systems": ["Caral irrigation canal", "Supe Valley agriculture"],
    'Chavín Temple "Black and White Portal"': ["Chavin portal entrance", "Chavin black white column"],
    "Nazca Underground Aqueducts (Puquios)": ["Nazca puquio aqueduct", "Nazca spiral well"],
    "Tiwanaku Kalasasaya Temple": ["Tiwanaku Kalasasaya gateway sun", "Tiwanaku ruins"],
    "Tiwanaku Semi-Subterranean Temple": ["Tiwanaku semi-subterranean temple", "Tiwanaku tenon heads"],
    "Great Zimbabwe Dry-Stone Walls": ["Great Zimbabwe walls tower", "Great Zimbabwe enclosure"],
    "Petra Water Channel System": ["Petra water channel", "Petra siq channel"],
    "Petra Siq Entrance Canyon": ["Petra Siq canyon treasury", "Petra Siq entrance"],
    "Nan Madol Canal Network": ["Nan Madol canal basalt", "Nan Madol aerial"],
    "Easter Island Rano Raraku Quarry (Moai Carving Site)": ["Rano Raraku moai quarry", "Easter Island moai hillside"],
    "Sacsayhuamán Zigzag Walls": ["Sacsayhuaman walls Cusco", "Sacsayhuaman zigzag stone"],
    "Baalbek Podium Blocks (Temple of Jupiter Foundation)": ["Baalbek podium blocks", "Baalbek Stone Pregnant Woman"],
}


async def search_commons(client: httpx.AsyncClient, query: str, limit: int = 10) -> list[dict]:
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",
        "srlimit": limit,
        "format": "json",
    }
    try:
        resp = await client.get(COMMONS_API, params=params)
        resp.raise_for_status()
        return resp.json().get("query", {}).get("search", [])
    except Exception as e:
        log.warning("Search failed for '%s': %s", query, e)
        return []


async def get_image_info(client: httpx.AsyncClient, titles: list[str]) -> list[dict]:
    if not titles:
        return []
    params = {
        "action": "query",
        "titles": "|".join(titles[:10]),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1280,
        "format": "json",
    }
    try:
        resp = await client.get(COMMONS_API, params=params)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        results = []
        for pid, page in pages.items():
            for ii in page.get("imageinfo", []):
                ext = ii.get("extmetadata", {})
                license_name = ext.get("LicenseShortName", {}).get("value", "")
                desc = ext.get("ImageDescription", {}).get("value", "")
                desc = re.sub(r"<[^>]+>", "", desc)[:500] if desc else ""
                results.append({
                    "title": page.get("title", ""),
                    "url": ii.get("url", ""),
                    "thumburl": ii.get("thumburl", ""),
                    "width": ii.get("width", 0),
                    "height": ii.get("height", 0),
                    "mime": ii.get("mime", ""),
                    "license": license_name,
                    "description": desc,
                })
        return results
    except Exception as e:
        log.warning("Image info failed: %s", e)
        return []


def is_good_image(img: dict) -> bool:
    if not img.get("url"):
        return False
    mime = img.get("mime", "")
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        return False
    w, h = img.get("width", 0), img.get("height", 0)
    if w < 300 or h < 200:
        return False
    return True


async def harvest_for_artifact(client: httpx.AsyncClient, pool, artifact_title: str, raw_object_id, trusted_source_id):
    search_queries = SEARCH_TERMS.get(artifact_title)
    if not search_queries:
        clean = artifact_title.replace("(", "").replace(")", "").replace('"', '')
        search_queries = [clean]

    all_file_titles = []
    seen = set()
    for q in search_queries:
        results = await search_commons(client, q, limit=10)
        for r in results:
            t = r["title"]
            if t not in seen:
                seen.add(t)
                all_file_titles.append(t)
        await asyncio.sleep(SEARCH_DELAY)

    if not all_file_titles:
        return 0

    images = await get_image_info(client, all_file_titles[:15])
    good = [img for img in images if is_good_image(img)]
    good = good[:MAX_IMAGES_PER_ARTIFACT]

    inserted = 0
    async with pool.acquire() as conn:
        for i, img in enumerate(good):
            existing = await conn.fetchval(
                "SELECT id FROM object_images WHERE image_url = $1", img["url"]
            )
            if existing:
                continue

            alt = img.get("description", "")[:500] or artifact_title
            caption = f"{artifact_title} — {img.get('license', 'Wikimedia Commons')}"

            await conn.execute("""
                INSERT INTO object_images (id, raw_object_id, trusted_source_id,
                                          image_url, alt_text, caption,
                                          content_type, image_order, created_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, NOW())
            """, raw_object_id, trusted_source_id, img["url"], alt, caption,
                img.get("mime", "image/jpeg"), i + 1)
            inserted += 1

    return inserted


async def main():
    pool = await asyncpg.create_pool(
        host="localhost", port=5432, user="eden", password="eden", database="eden",
        min_size=1, max_size=5,
    )

    async with pool.acquire() as conn:
        artifacts = await conn.fetch("""
            SELECT sr.canonical_title, sr.raw_object_id,
                   ro.trusted_source_id
            FROM source_records sr
            JOIN raw_objects ro ON sr.raw_object_id = ro.id
            WHERE ro.r2_key LIKE 'visual-library/%'
            ORDER BY sr.canonical_title
        """)
        existing_counts = {}
        for row in await conn.fetch("""
            SELECT ro.id as raw_object_id, COUNT(oi.id) as cnt
            FROM raw_objects ro
            JOIN object_images oi ON oi.raw_object_id = ro.id
            WHERE ro.r2_key LIKE 'visual-library/%'
            GROUP BY ro.id
        """):
            existing_counts[row["raw_object_id"]] = row["cnt"]

    log.info("Found %d visual library artifacts to harvest images for", len(artifacts))

    total_images = 0
    total_skipped = 0
    total_errors = 0

    async with httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": "EdenProject/1.0 (research; contact@eden.internal)"},
    ) as client:
        for art in artifacts:
            title = art["canonical_title"]
            existing = existing_counts.get(art["raw_object_id"], 0)
            if existing >= MAX_IMAGES_PER_ARTIFACT:
                log.info("  SKIP (has %d images): %s", existing, title)
                total_skipped += 1
                continue

            try:
                count = await harvest_for_artifact(
                    client, pool, title, art["raw_object_id"], art["trusted_source_id"]
                )
                if count > 0:
                    log.info("  +%d images: %s", count, title)
                    total_images += count
                else:
                    log.info("  0 images found: %s", title)
            except Exception as e:
                log.error("  ERROR on %s: %s", title, e)
                total_errors += 1

            await asyncio.sleep(SEARCH_DELAY)

    await pool.close()
    log.info("Done! Total images added: %d, Skipped: %d, Errors: %d",
             total_images, total_skipped, total_errors)


if __name__ == "__main__":
    asyncio.run(main())
