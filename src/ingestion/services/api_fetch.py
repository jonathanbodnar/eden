"""API-specific fetch logic for sources with structured REST APIs.

During the fetch phase, instead of downloading HTML pages, these functions
call the source API to get rich JSON metadata for each artifact.
The JSON is stored as the raw object content.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "EdenBot/1.0 (research ingestion platform)"


def _strip_html(text: str) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def api_fetch_url(slug: str, external_id: str) -> str | None:
    """Return the JSON API URL for a given source slug + external_id.

    Returns None if this slug has no API fetcher (fall back to HTML).
    """
    if slug == "cdli":
        art_id = external_id.removeprefix("cdli-")
        return f"https://cdli.earth/artifacts/{art_id}.json"

    if slug in ("met-museum", "metmuseum"):
        obj_id = external_id.removeprefix("met-")
        return f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{obj_id}"

    if slug == "europeana":
        item_path = external_id.removeprefix("europeana-").replace("-", "/")
        return f"https://api.europeana.eu/record/v2/{item_path}.json"

    if slug == "sefaria":
        ref = external_id.removeprefix("sefaria-").replace(" ", "_")
        return f"https://www.sefaria.org/api/texts/{ref}"

    if slug == "dss-bible":
        return None  # HTML scrape, no API URL

    if slug == "ctext":
        path = external_id.removeprefix("ctext::")
        return f"https://api.ctext.org/gettext?urn=ctp:{path}"

    if slug == "suttacentral":
        uid = external_id.removeprefix("sc-")
        return f"https://suttacentral.net/api/bilarasuttas/{uid}/sujato"

    if slug == "oracc":
        eid = external_id.removeprefix("oracc-")
        proj, _, text_id = eid.partition("-")
        return f"http://oracc.org/{proj}/{text_id}.json" if text_id else None

    if slug == "loc":
        loc_id = external_id.removeprefix("loc-")
        return f"https://www.loc.gov/item/{loc_id}/?fo=json"

    if slug == "internet-archive":
        ia_id = external_id.removeprefix("ia-")
        return f"https://archive.org/metadata/{ia_id}"

    if slug == "wikidata-artifacts":
        qid = external_id.removeprefix("wd-art-")
        return f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}&format=json&languages=en"

    if slug == "bsb-mdz":
        bsb_id = external_id.removeprefix("bsb-")
        return f"https://api.digitale-sammlungen.de/iiif/presentation/v2/{bsb_id}/manifest"

    if slug == "gallica":
        ark = external_id.removeprefix("gallica-")
        return f"https://gallica.bnf.fr/services/OAIRecord?ark={ark}"

    if slug == "pleiades":
        pid = external_id.removeprefix("pleiades-")
        return f"https://pleiades.stoa.org/places/{pid}/json"

    if slug == "open-context":
        oc_id = external_id.removeprefix("oc-")
        return f"https://opencontext.org/subjects/{oc_id}.json"

    if slug == "unesco-whc":
        site_id = external_id.removeprefix("unesco-")
        return f"https://data.unesco.org/api/explore/v2.1/catalog/datasets/whc001/records?where=id_no%3D{site_id}&limit=1"

    if slug == "wikidata-locations":
        qid = external_id.removeprefix("wd-loc-")
        return f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}&format=json&languages=en"

    if slug == "openalex":
        oa_id = external_id.removeprefix("oa-")
        return f"https://api.openalex.org/works/{oa_id}"

    if slug == "core":
        core_id = external_id.removeprefix("core-")
        return f"https://api.core.ac.uk/v3/works/{core_id}"

    if slug == "tla-egyptian":
        parts = external_id.removeprefix("tla-")
        last_dash = parts.rfind("-")
        if last_dash < 0:
            return None
        ds_short = parts[:last_dash]
        row_idx = parts[last_dash + 1:]
        ds_full = f"thesaurus-linguae-aegyptiae/{ds_short}"
        return (
            f"https://datasets-server.huggingface.co/rows"
            f"?dataset={ds_full}&config=default&split=train"
            f"&offset={row_idx}&length=1"
        )

    if slug == "sacred-texts":
        return None  # HTML scrape via Wayback, handled in fetch_worker

    return None


def parse_api_metadata(slug: str, data: dict) -> dict:
    """Extract structured metadata from an API response for use in normalization.

    Returns a dict suitable for storing in raw_metadata_jsonb.
    """
    if slug == "cdli":
        return _parse_cdli(data)
    if slug in ("met-museum", "metmuseum"):
        return _parse_met(data)
    if slug == "europeana":
        return _parse_europeana(data)
    if slug == "sefaria":
        return _parse_sefaria(data)
    if slug == "ctext":
        return _parse_ctext(data)
    if slug == "suttacentral":
        return _parse_suttacentral(data)
    if slug == "oracc":
        return _parse_oracc(data)
    if slug == "loc":
        return _parse_loc(data)
    if slug == "internet-archive":
        return _parse_internet_archive(data)
    if slug in ("wikidata-artifacts", "wikidata-locations"):
        return _parse_wikidata(data, is_location=(slug == "wikidata-locations"))
    if slug == "bsb-mdz":
        return _parse_bsb(data)
    if slug == "gallica":
        return _parse_gallica(data)
    if slug == "pleiades":
        return _parse_pleiades(data)
    if slug == "open-context":
        return _parse_open_context(data)
    if slug == "unesco-whc":
        return _parse_unesco(data)
    if slug == "openalex":
        return _parse_openalex(data)
    if slug == "core":
        return _parse_core(data)
    if slug == "tla-egyptian":
        return _parse_tla(data)
    return data


# ---------------------------------------------------------------------------
# CDLI parser
# ---------------------------------------------------------------------------

def _extract_name(obj, *keys) -> str:
    """Pull a human-readable name from a nested API dict.

    Tries each key in order, returns the first non-empty string.
    Falls back to "" rather than ever stringifying a dict.
    """
    if not isinstance(obj, dict):
        return str(obj) if obj else ""
    for k in keys:
        val = obj.get(k)
        if isinstance(val, str) and val:
            return val
    return ""


def _parse_cdli(art: dict) -> dict:
    # Start with the complete raw response so nothing is lost
    meta: dict = {"_raw": art, "source_api": "cdli"}

    meta["cdli_id"] = art.get("id")
    meta["title"] = art.get("designation", "")
    meta["museum_no"] = art.get("museum_no", "")
    meta["excavation_no"] = art.get("excavation_no", "")

    # Dimensions
    dim_parts = {}
    for field in ("height", "width", "thickness"):
        if art.get(field):
            dim_parts[field] = art[field]
    if dim_parts:
        meta["dimensions_parsed"] = dim_parts
        meta["dimensions"] = " x ".join(f"{v}mm ({k})" for k, v in dim_parts.items())

    # Period
    meta["period"] = _extract_name(art.get("period"), "name", "period")

    # Provenience / findspot
    prov = art.get("provenience")
    meta["origin_place"] = _extract_name(prov, "provenience", "name")
    if isinstance(prov, dict):
        meta["provenience_raw"] = prov
    meta["findspot_comments"] = art.get("findspot_comments", "")
    meta["findspot_square"] = art.get("findspot_square", "")

    # Artifact type
    art_type = art.get("artifact_type") or art.get("artifactType")
    meta["object_type"] = _extract_name(art_type, "artifact_type", "name")

    # Genres (list)
    genres = art.get("genres", [])
    genre_parts = []
    for g in (genres if isinstance(genres, list) else []):
        if isinstance(g, dict):
            name = _extract_name(g.get("genre", {}), "genre", "name")
            comment = (g.get("comments") or "").strip()
            genre_parts.append(f"{name}: {comment}".strip(": ") if comment else name)
    meta["genre"] = "; ".join(genre_parts)

    # Languages (list)
    languages = art.get("languages", [])
    lang_names = []
    for l in (languages if isinstance(languages, list) else []):
        if isinstance(l, dict):
            name = _extract_name(l.get("language", {}), "language", "name")
            if name:
                lang_names.append(name)
    meta["language_family"] = ", ".join(lang_names)

    # Materials (list)
    materials = art.get("materials", [])
    mat_names = []
    for m in (materials if isinstance(materials, list) else []):
        if isinstance(m, dict):
            mat_names.append(_extract_name(m.get("material", {}), "material", "name"))
    meta["medium"] = ", ".join(n for n in mat_names if n)

    # Material aspects & colors
    aspects = art.get("material_aspects", [])
    if aspects:
        meta["material_aspects"] = [
            _extract_name(a.get("aspect", a), "aspect", "name") for a in aspects if isinstance(a, dict)
        ]
    colors = art.get("material_colors", [])
    if colors:
        meta["material_colors"] = [
            _extract_name(c.get("color", c), "color", "name") for c in colors if isinstance(c, dict)
        ]

    # Collections / repository
    collections = art.get("collections", [])
    if collections and isinstance(collections[0], dict):
        cinfo = collections[0].get("collection", {})
        if isinstance(cinfo, dict):
            meta["repository"] = cinfo.get("collection", "")
            meta["repository_url"] = cinfo.get("collection_url", "")
            meta["repository_country"] = cinfo.get("country_iso", "")
            meta["repository_holding"] = cinfo.get("collection_holding", "")
            meta["repository_status"] = cinfo.get("collection_holding_status", "")
            lat = cinfo.get("location_latitude_wgs1984")
            lon = cinfo.get("location_longitude_wgs1984")
            if lat and lon:
                meta["repository_coords"] = {"lat": lat, "lon": lon}

    # Inscription / ATF
    inscription = art.get("inscription")
    if isinstance(inscription, dict):
        atf = inscription.get("atf", "")
        if atf:
            meta["text"] = atf
            meta["text_format"] = "ATF"

    # Composites
    composites = art.get("composites", [])
    if composites:
        meta["composites"] = [
            {
                "composite_no": c.get("composite_no", ""),
                "designation": _extract_name(c.get("composite", {}), "designation"),
            }
            for c in composites if isinstance(c, dict)
        ]

    # External resources
    ext_res = art.get("external_resources", [])
    if ext_res:
        meta["external_resources"] = []
        for er in ext_res:
            if not isinstance(er, dict):
                continue
            res = er.get("external_resource", {})
            if isinstance(res, dict):
                meta["external_resources"].append({
                    "name": res.get("external_resource", ""),
                    "abbrev": res.get("abbrev", ""),
                    "url": (res.get("base_url", "") + er.get("external_resource_key", "")).strip(),
                    "project_url": res.get("project_url", ""),
                })

    # Dates — map period names to approximate BC date ranges
    period_dates = {
        "Uruk III": (-3500, -3200), "Uruk IV": (-3500, -3200),
        "Uruk V": (-3800, -3500), "Proto-Elamite": (-3200, -2700),
        "ED I": (-2900, -2750), "ED II": (-2750, -2600),
        "ED IIIa": (-2600, -2500), "ED IIIb": (-2500, -2340),
        "Early Dynastic I-II": (-2900, -2600), "Early Dynastic IIIa": (-2600, -2500),
        "Early Dynastic IIIb": (-2500, -2340),
        "Old Akkadian": (-2340, -2200), "Akkadian": (-2340, -2200),
        "Lagash II": (-2200, -2112), "Gutian": (-2200, -2112),
        "Ur III": (-2112, -2004),
        "Early Old Babylonian": (-2004, -1900),
        "Old Babylonian": (-2004, -1595),
        "Old Assyrian": (-2000, -1750),
        "Middle Babylonian": (-1595, -1155),
        "Middle Assyrian": (-1392, -1056),
        "Neo-Assyrian": (-911, -612),
        "Neo-Babylonian": (-626, -539),
        "Achaemenid": (-539, -330),
        "Hellenistic": (-330, -63),
        "Seleucid": (-312, -63),
        "Parthian": (-247, 224),
        "Sasanian": (224, 651),
    }
    dates = []
    period_name = meta.get("period", "")
    if period_name and period_name in period_dates:
        start, end = period_dates[period_name]
        dates.append({
            "type": "object_creation", "start": start, "end": end,
            "label": period_name, "confidence": "approximate",
        })

    dates_ref = art.get("dates_referenced")
    if dates_ref and dates_ref != "00.00.00.00":
        if not dates:
            dates.append({"label": dates_ref, "type": "object_creation", "confidence": "uncertain"})
        else:
            dates[0]["label"] = f"{period_name} ({dates_ref})"
    if dates:
        meta["dates"] = dates

    dates_list = art.get("dates", [])
    if dates_list:
        meta["dates_detailed"] = dates_list

    # Publications
    pubs = art.get("publications", [])
    if pubs:
        meta["publications"] = []
        for p in pubs:
            if not isinstance(p, dict):
                continue
            pub = p.get("publication", {}) if isinstance(p.get("publication"), dict) else {}
            entry = {
                "designation": pub.get("designation", ""),
                "exact_reference": p.get("exact_reference", ""),
                "publication_type": p.get("publication_type", ""),
                "title": pub.get("title", ""),
                "year": pub.get("year"),
                "publisher": pub.get("publisher", ""),
                "series": pub.get("series", ""),
            }
            authors = pub.get("authors", [])
            if authors:
                entry["authors"] = [
                    _extract_name(a.get("author", {}), "author", "name")
                    for a in authors[:10] if isinstance(a, dict)
                ]
            meta["publications"].append(entry)

    # Seals / impressions
    seals = art.get("seals", [])
    if seals:
        meta["seals"] = seals
    impressions = art.get("impressions", [])
    if impressions:
        meta["impressions"] = impressions

    # Witnesses
    witnesses = art.get("witnesses", [])
    if witnesses:
        meta["witnesses"] = witnesses

    # Images — CDLI serves photos and line drawings at predictable URLs
    # Photo: /dl/photo/P{id:06d}.jpg (not all artifacts have photos)
    # Lineart: /dl/lineart/P{id:06d}_l.jpg (most artifacts have these)
    images = []
    cdli_id = art.get("id")
    if cdli_id:
        p_num = f"P{int(cdli_id):06d}"
        images.append(f"https://cdli.earth/dl/photo/{p_num}.jpg")
        images.append(f"https://cdli.earth/dl/lineart/{p_num}_l.jpg")

    for img_field in ("images", "photos"):
        for img in art.get(img_field, []):
            if isinstance(img, dict) and img.get("url"):
                url = img["url"]
                if url not in images:
                    images.append(url)
            elif isinstance(img, str) and img not in images:
                images.append(img)
    if images:
        meta["image_urls"] = images

    return meta


# ---------------------------------------------------------------------------
# Met Museum parser
# ---------------------------------------------------------------------------

def _parse_met(obj: dict) -> dict:
    # Store complete raw response so nothing is lost
    meta: dict = {"_raw": obj, "source_api": "met"}

    meta["met_object_id"] = obj.get("objectID")
    meta["title"] = obj.get("title", "")
    meta["culture"] = obj.get("culture", "")
    meta["period"] = obj.get("period", "")
    meta["dynasty"] = obj.get("dynasty", "")
    meta["reign"] = obj.get("reign", "")
    meta["medium"] = obj.get("medium", "")
    meta["object_type"] = obj.get("objectName", "")
    meta["department"] = obj.get("department", "")
    meta["classification"] = obj.get("classification", "")
    meta["dimensions"] = obj.get("dimensions", "")
    meta["credit_line"] = obj.get("creditLine", "")
    meta["repository"] = obj.get("repository", "")
    meta["portfolio"] = obj.get("portfolio", "")
    meta["artist_role"] = obj.get("artistRole", "")
    meta["artist_prefix"] = obj.get("artistPrefix", "")
    meta["artist_display_name"] = obj.get("artistDisplayName", "")
    meta["artist_display_bio"] = obj.get("artistDisplayBio", "")
    meta["artist_nationality"] = obj.get("artistNationality", "")
    meta["artist_begin_date"] = obj.get("artistBeginDate", "")
    meta["artist_end_date"] = obj.get("artistEndDate", "")
    meta["object_date"] = obj.get("objectDate", "")
    meta["object_wikidata_url"] = obj.get("objectWikidata_URL", "")
    meta["link_resource"] = obj.get("linkResource", "")
    meta["rights_and_reproduction"] = obj.get("rightsAndReproduction", "")
    meta["metadata_date"] = obj.get("metadataDate", "")

    # Geography — every field
    origin_parts = [obj.get("city"), obj.get("state"), obj.get("country"),
                     obj.get("region"), obj.get("subregion"), obj.get("locale")]
    meta["origin_place"] = ", ".join(filter(None, origin_parts)).strip()
    meta["geography_type"] = obj.get("geographyType", "")
    meta["excavation"] = obj.get("excavation", "")
    meta["locus"] = obj.get("locus", "")
    meta["river"] = obj.get("river", "")
    meta["county"] = obj.get("county", "")

    geo = {}
    for f in ("geographyType", "city", "state", "county", "country",
              "region", "subregion", "locale", "locus", "excavation", "river"):
        if obj.get(f):
            geo[f] = obj[f]
    if geo:
        meta["geography"] = geo

    # Dates
    meta["date_label"] = obj.get("objectDate", "")
    dates = []
    begin = obj.get("objectBeginDate")
    end = obj.get("objectEndDate")
    if begin is not None or end is not None:
        dates.append({
            "type": "object_creation",
            "start": begin,
            "end": end,
            "label": obj.get("objectDate", ""),
            "confidence": "approximate",
        })
    if dates:
        meta["dates"] = dates

    # Tags
    tags = obj.get("tags") or []
    if tags:
        meta["tags"] = [t.get("term", "") for t in tags if isinstance(t, dict)]
        meta["tags_aat_urls"] = [t.get("AAT_URL", "") for t in tags if isinstance(t, dict) and t.get("AAT_URL")]
        meta["tags_wikidata_urls"] = [t.get("Wikidata_URL", "") for t in tags if isinstance(t, dict) and t.get("Wikidata_URL")]

    # Images — full-res originals, skip thumbnails
    images = []
    if obj.get("primaryImage"):
        images.append(obj["primaryImage"])
    for img in obj.get("additionalImages", []):
        if img and img not in images:
            images.append(img)
    if images:
        meta["image_urls"] = images

    # Constituents / artists
    constituents = obj.get("constituents") or []
    if constituents:
        meta["artists"] = [
            {
                "name": c.get("name", ""),
                "role": c.get("role", ""),
                "gender": c.get("gender", ""),
                "wikidata_url": c.get("constituentWikidata_URL", ""),
                "ulan_url": c.get("constituentULAN_URL", ""),
            }
            for c in constituents if isinstance(c, dict)
        ]

    meta["is_public_domain"] = obj.get("isPublicDomain", False)
    meta["object_url"] = obj.get("objectURL", "")
    meta["accession_number"] = obj.get("accessionNumber", "")
    meta["accession_year"] = obj.get("accessionYear", "")
    meta["gallery_number"] = obj.get("GalleryNumber", "")
    meta["is_highlight"] = obj.get("isHighlight", False)

    if obj.get("measurements"):
        meta["measurements_parsed"] = obj["measurements"]

    return meta


# ---------------------------------------------------------------------------
# Europeana parser
# ---------------------------------------------------------------------------

def _parse_europeana(data: dict) -> dict:
    obj = data.get("object", data)
    proxy_in = obj.get("proxies", [{}])
    proxy = proxy_in[0] if proxy_in else {}
    agg = (obj.get("aggregations") or [{}])[0] if obj.get("aggregations") else {}

    meta: dict = {"source_api": "europeana"}

    titles = proxy.get("dcTitle", {})
    for lang, vals in titles.items():
        if vals:
            meta["title"] = vals[0]
            break
    if not meta.get("title"):
        meta["title"] = ""

    descs = proxy.get("dcDescription", {})
    for lang, vals in descs.items():
        if vals:
            meta["text"] = vals[0][:5000]
            break

    for field, key in [
        ("dcCreator", "creator"),
        ("dcDate", "date_label"),
        ("dcType", "object_type"),
        ("dcFormat", "medium"),
        ("dcSubject", "tags"),
    ]:
        val = proxy.get(field, {})
        if isinstance(val, dict):
            for lang, vals in val.items():
                if vals:
                    meta[key] = vals if key == "tags" else vals[0]
                    break
        elif isinstance(val, list) and val:
            meta[key] = val

    images = []
    if agg.get("edmIsShownBy"):
        images.append(agg["edmIsShownBy"])
    if agg.get("edmObject"):
        images.append(agg["edmObject"])
    for view in agg.get("hasView", []):
        if isinstance(view, str):
            images.append(view)
        elif isinstance(view, dict) and view.get("about"):
            images.append(view["about"])
    if images:
        meta["image_urls"] = images

    meta["repository"] = agg.get("edmDataProvider", {})
    if isinstance(meta["repository"], dict):
        for lang, vals in meta["repository"].items():
            if vals:
                meta["repository"] = vals[0] if isinstance(vals, list) else vals
                break

    return meta


# ---------------------------------------------------------------------------
# Sefaria parser — Hebrew Bible, Talmud, etc.
# ---------------------------------------------------------------------------

def _parse_sefaria(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "sefaria"}
    meta["title"] = data.get("ref", data.get("heRef", ""))
    meta["book"] = data.get("book", "")

    en_text = data.get("text", "")
    if isinstance(en_text, list):
        en_text = "\n".join(_flatten_text(en_text))
    en_text = re.sub(r"<[^>]+>", "", en_text).strip()

    he_text = data.get("he", "")
    if isinstance(he_text, list):
        he_text = "\n".join(_flatten_text(he_text))
    he_text = re.sub(r"<[^>]+>", "", he_text).strip()

    meta["text"] = en_text if en_text else he_text
    meta["language_family"] = "Hebrew"

    translations = []
    if he_text:
        translations.append({"language": "Hebrew", "text": he_text, "version_type": "original"})
    if en_text:
        translations.append({"language": "English", "text": en_text})
    meta["translations"] = translations

    cats = data.get("categories", [])
    if cats:
        meta["genre"] = " > ".join(cats)

    book = data.get("book", "")
    tanakh_dates = {
        "Genesis": (-1400, -400), "Exodus": (-1400, -400),
        "Leviticus": (-1400, -400), "Numbers": (-1400, -400),
        "Deuteronomy": (-1400, -400),
        "Joshua": (-1200, -600), "Judges": (-1200, -600),
        "I Samuel": (-1000, -600), "II Samuel": (-1000, -600),
        "I Kings": (-600, -550), "II Kings": (-600, -550),
        "Isaiah": (-740, -530), "Jeremiah": (-626, -580),
        "Ezekiel": (-593, -571),
        "Hosea": (-750, -720), "Joel": (-500, -350),
        "Amos": (-760, -750), "Obadiah": (-586, -550),
        "Jonah": (-750, -400), "Micah": (-742, -687),
        "Nahum": (-663, -612), "Habakkuk": (-612, -589),
        "Zephaniah": (-640, -609), "Haggai": (-520, -520),
        "Zechariah": (-520, -480), "Malachi": (-460, -430),
        "Psalms": (-1000, -300), "Proverbs": (-900, -400),
        "Job": (-600, -400), "Song of Songs": (-900, -300),
        "Ruth": (-1000, -400), "Lamentations": (-586, -550),
        "Ecclesiastes": (-400, -200), "Esther": (-400, -300),
        "Daniel": (-530, -165), "Ezra": (-450, -400),
        "Nehemiah": (-430, -400),
        "I Chronicles": (-400, -300), "II Chronicles": (-400, -300),
    }
    for bk, (start, end) in tanakh_dates.items():
        if bk.lower() in book.lower() or book.lower() in bk.lower():
            meta["dates"] = [{
                "type": "composition", "start": start, "end": end,
                "label": f"{bk} (composed {abs(start)}-{abs(end)} BC)",
                "confidence": "approximate",
            }]
            break

    meta["is_public_domain"] = True

    return meta


def _flatten_text(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj] if obj.strip() else []
    if isinstance(obj, list):
        parts = []
        for item in obj:
            parts.extend(_flatten_text(item))
        return parts
    return []


# ---------------------------------------------------------------------------
# DSS HTML parser
# ---------------------------------------------------------------------------

def parse_dss_html(html: str, external_id: str) -> dict:
    """Parse structured HTML from dssenglishbible.com into metadata.
    
    The page has a white-background TD containing: metadata header,
    then the actual translation text with verse numbers.
    """
    meta: dict = {"source_api": "dss-bible"}

    scroll_id = external_id.removeprefix("dss-")
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).replace("Biblical Dead Sea Scrolls -", "").strip() if title_match else ""
    if not title:
        title = f"Dead Sea Scroll {scroll_id}"
    meta["title"] = title

    content_section = ""
    parts = html.split('bgcolor="white"')
    if len(parts) < 2:
        parts = html.split("bgcolor='white'")
    if len(parts) >= 2:
        content_section = parts[1]
    else:
        content_section = html

    plain = re.sub(r"<[^>]+>", " ", content_section)
    plain = re.sub(r"&nbsp;", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()

    language = "Hebrew"
    date_str = ""
    location = ""
    contents_desc = ""

    lang_m = re.search(r"Language:\s*(\w+)", plain)
    if lang_m:
        language = lang_m.group(1)
    date_m = re.search(r"Date:\s*(.+?)(?:Location:|Contents:|$)", plain)
    if date_m:
        date_str = date_m.group(1).strip().rstrip("_").strip()
    loc_m = re.search(r"Location:\s*(.+?)(?:Contents:|Language:|Date:|\d+[:\s]+\d+|\d+\s+[A-Z])", plain)
    if loc_m:
        location = loc_m.group(1).strip().rstrip("_").strip()
        if len(location) > 200:
            location = location[:200]
    cont_m = re.search(r"Contents:\s*(.+?)(?:\d+:\d+|\d+\s+[A-Z])", plain)
    if cont_m:
        contents_desc = cont_m.group(1).strip().rstrip("_").strip()

    meta["language_family"] = language
    meta["origin_place"] = location if location else "Qumran"
    meta["contents_coverage"] = contents_desc

    verse_chunks = re.split(r"(?=\d+:\d+\s)", plain)
    translation_lines = []
    for chunk in verse_chunks:
        vm = re.match(r"(\d+:\d+)\s+(.*)", chunk)
        if vm:
            ref = vm.group(1)
            text = vm.group(2).strip()
            text = re.sub(r"\[\.+\]", "[...]", text)
            if text and len(text) > 3:
                translation_lines.append(f"{ref} {text}")

    if not translation_lines:
        single_verse = re.split(r"(?=\d+\s+[A-Z])", plain)
        for chunk in single_verse:
            vm = re.match(r"(\d+)\s+([A-Z].*)", chunk)
            if vm and len(vm.group(2)) > 5:
                translation_lines.append(f"{vm.group(1)} {vm.group(2).strip()}")

    meta["text"] = "\n".join(translation_lines)

    translations = []
    if translation_lines:
        translations.append({
            "language": "English",
            "text": "\n".join(translation_lines),
            "translator": "Craig Davis",
            "version_type": "translation",
        })
    meta["translations"] = translations

    dates = []
    if date_str:
        bc_match = re.search(r"(\d+)\s*B\.?C\.?", date_str)
        ad_match = re.search(r"(\d+)\s*A\.?D\.?", date_str)
        start = -int(bc_match.group(1)) if bc_match else None
        end = int(ad_match.group(1)) if ad_match else None
        if start is not None or end is not None:
            dates.append({
                "type": "object_creation",
                "start": start if start else -300,
                "end": end if end else 68,
                "label": date_str,
                "confidence": "approximate",
            })
    meta["dates"] = dates
    meta["is_public_domain"] = True

    return meta


# ---------------------------------------------------------------------------
# CText parser
# ---------------------------------------------------------------------------

def _parse_ctext(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "ctext"}
    meta["title"] = data.get("title", data.get("urn", ""))

    fulltext = data.get("fulltext", "")
    if isinstance(fulltext, list):
        fulltext = "\n".join(fulltext)
    meta["text"] = fulltext
    meta["language_family"] = "Chinese"
    meta["is_public_domain"] = True

    translations = []
    en_trans = data.get("translation", "")
    if isinstance(en_trans, list):
        en_trans = "\n".join(en_trans)
    if en_trans:
        translations.append({"language": "English", "text": en_trans})
    meta["translations"] = translations

    return meta


# ---------------------------------------------------------------------------
# SuttaCentral parser
# ---------------------------------------------------------------------------

def _parse_suttacentral(data: dict) -> dict:
    meta: dict = {"_raw": {k: v for k, v in data.items() if k != "html_text"}, "source_api": "suttacentral"}
    meta["language_family"] = "Pali"
    meta["is_public_domain"] = True

    keys_order = data.get("keys_order", [])
    translation_text = data.get("translation_text", {})
    root_text = data.get("root_text", {})

    if keys_order and translation_text:
        title_key = keys_order[1] if len(keys_order) > 1 else keys_order[0]
        meta["title"] = translation_text.get(title_key, "").strip()
    elif keys_order and root_text:
        title_key = keys_order[1] if len(keys_order) > 1 else keys_order[0]
        meta["title"] = root_text.get(title_key, "").strip()

    en_parts = []
    pali_parts = []
    for key in keys_order:
        en_val = translation_text.get(key, "").strip()
        if en_val:
            en_parts.append(en_val)
        pali_val = root_text.get(key, "").strip()
        if pali_val:
            pali_parts.append(pali_val)

    en_text = "\n".join(en_parts)
    pali_text = "\n".join(pali_parts)

    meta["text"] = en_text if en_text else pali_text

    translations = []
    if pali_text:
        translations.append({"language": "Pali", "text": pali_text, "version_type": "original"})
    if en_text:
        translations.append({"language": "English", "text": en_text, "translator": "Bhikkhu Sujato"})
    meta["translations"] = translations

    meta["dates"] = [{
        "type": "composition", "start": -500, "end": -200,
        "label": "Pali Canon (c. 5th-3rd century BC)",
        "confidence": "approximate",
    }]

    return meta


# ---------------------------------------------------------------------------
# ORACC parser
# ---------------------------------------------------------------------------

def _parse_oracc(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "oracc"}

    cdl = data.get("cdl", [])
    designation = data.get("textid", "")
    meta["title"] = designation

    text_parts = []
    for chunk in cdl:
        if isinstance(chunk, dict):
            if chunk.get("type") == "line_variant" or chunk.get("f"):
                form = chunk.get("f", {})
                if isinstance(form, dict):
                    text_parts.append(form.get("form", ""))
            for child in chunk.get("cdl", []):
                if isinstance(child, dict) and child.get("f"):
                    text_parts.append(child["f"].get("form", ""))

    if text_parts:
        meta["text"] = " ".join(t for t in text_parts if t)
        meta["text_format"] = "ATF"

    meta["language_family"] = "Sumerian"
    meta["is_public_domain"] = True

    return meta


# ---------------------------------------------------------------------------
# Library of Congress parser
# ---------------------------------------------------------------------------

def _parse_loc(data: dict) -> dict:
    item = data.get("item", data)
    meta: dict = {"_raw": data, "source_api": "loc"}

    meta["title"] = item.get("title", "")
    meta["text"] = item.get("description", [""])[0] if isinstance(item.get("description"), list) else item.get("description", "")

    subjects = item.get("subject", [])
    if subjects:
        meta["tags"] = subjects

    dates = []
    date_str = item.get("date", "")
    if date_str:
        dates.append({"type": "publication", "label": date_str, "confidence": "approximate"})
    meta["dates"] = dates

    repo = item.get("repository", [])
    if isinstance(repo, list) and repo:
        meta["repository"] = repo[0]
    elif isinstance(repo, str):
        meta["repository"] = repo

    images = []
    for resource in item.get("resources", []):
        if isinstance(resource, dict):
            img_url = resource.get("image", resource.get("url", ""))
            if img_url and img_url.startswith("http"):
                images.append(img_url)
    if images:
        meta["image_urls"] = images

    meta["is_public_domain"] = item.get("rights", "") == "no known restrictions"

    return meta


# ---------------------------------------------------------------------------
# Internet Archive parser
# ---------------------------------------------------------------------------

def _parse_internet_archive(data: dict) -> dict:
    meta_raw = data.get("metadata", data)
    meta: dict = {"_raw": data, "source_api": "internet_archive"}

    meta["title"] = _strip_html(meta_raw.get("title", ""))
    desc = meta_raw.get("description", "")
    if isinstance(desc, list):
        desc = " ".join(str(d) for d in desc)
    meta["text"] = _strip_html(desc)[:5000] if desc else ""

    subjects = meta_raw.get("subject", [])
    if isinstance(subjects, str):
        subjects = [subjects]
    meta["tags"] = subjects

    creator = meta_raw.get("creator", "")
    if isinstance(creator, list):
        creator = "; ".join(creator)
    meta["creator"] = creator

    date_str = meta_raw.get("date", "")
    if date_str:
        meta["dates"] = [{"type": "publication", "label": str(date_str), "confidence": "approximate"}]

    meta["language_family"] = meta_raw.get("language", "")
    meta["is_public_domain"] = "public" in str(meta_raw.get("licenseurl", "")).lower()

    return meta


# ---------------------------------------------------------------------------
# Wikidata parser (artifacts + locations)
# ---------------------------------------------------------------------------

def _parse_wikidata(data: dict, is_location: bool = False) -> dict:
    entities = data.get("entities", {})
    entity = next(iter(entities.values()), {}) if entities else data

    meta: dict = {"_raw": data, "source_api": "wikidata"}

    labels = entity.get("labels", {})
    en_label = labels.get("en", {})
    meta["title"] = en_label.get("value", "") if isinstance(en_label, dict) else str(en_label)

    descs = entity.get("descriptions", {})
    en_desc = descs.get("en", {})
    meta["text"] = en_desc.get("value", "") if isinstance(en_desc, dict) else str(en_desc)

    claims = entity.get("claims", {})

    def _claim_value(prop: str):
        prop_claims = claims.get(prop, [])
        for c in prop_claims:
            ms = c.get("mainsnak", {})
            dv = ms.get("datavalue", {})
            if dv.get("type") == "string":
                return dv.get("value", "")
            if dv.get("type") == "wikibase-entityid":
                return dv.get("value", {}).get("id", "")
            if dv.get("type") == "time":
                return dv.get("value", {}).get("time", "")
            if dv.get("type") == "globecoordinate":
                return dv.get("value", {})
            if dv.get("type") == "quantity":
                return dv.get("value", {}).get("amount", "")
        return None

    coords = _claim_value("P625")
    if isinstance(coords, dict):
        meta["latitude"] = coords.get("latitude")
        meta["longitude"] = coords.get("longitude")

    inception = _claim_value("P571")
    if inception:
        meta["dates"] = [{"type": "object_creation", "label": str(inception), "confidence": "approximate"}]

    country_qid = _claim_value("P17")
    if country_qid:
        meta["country_qid"] = country_qid

    culture_qid = _claim_value("P2596")
    if culture_qid:
        meta["culture"] = culture_qid

    images = []
    for c in claims.get("P18", []):
        fname = c.get("mainsnak", {}).get("datavalue", {}).get("value", "")
        if fname:
            safe_name = fname.replace(" ", "_")
            images.append(f"https://commons.wikimedia.org/wiki/Special:FilePath/{safe_name}")
    if images:
        meta["image_urls"] = images

    alt_names = []
    for lang_alias in entity.get("aliases", {}).values():
        for a in lang_alias:
            if isinstance(a, dict):
                alt_names.append(a.get("value", ""))
    if alt_names:
        meta["alternate_names"] = alt_names

    meta["is_public_domain"] = True

    return meta


# ---------------------------------------------------------------------------
# BSB/MDZ parser (IIIF manifest)
# ---------------------------------------------------------------------------

def _parse_bsb(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "bsb"}

    label = data.get("label", "")
    if isinstance(label, list):
        label = label[0] if label else ""
    if isinstance(label, dict):
        label = label.get("@value", "")
    meta["title"] = str(label)

    desc = data.get("description", "")
    if isinstance(desc, list):
        desc = desc[0] if desc else ""
    if isinstance(desc, dict):
        desc = desc.get("@value", "")
    meta["text"] = str(desc)

    md = data.get("metadata", [])
    for entry in md:
        if not isinstance(entry, dict):
            continue
        lbl = entry.get("label", "")
        val = entry.get("value", "")
        if isinstance(val, list):
            val = val[0] if val else ""
        if isinstance(val, dict):
            val = val.get("@value", "")
        lbl_lower = str(lbl).lower()
        if "date" in lbl_lower:
            meta["date_label"] = str(val)
        elif "author" in lbl_lower or "creator" in lbl_lower:
            meta["creator"] = str(val)
        elif "language" in lbl_lower:
            meta["language_family"] = str(val)

    images = []
    for canvas in (data.get("sequences", [{}])[0] if data.get("sequences") else {}).get("canvases", [])[:10]:
        for img in canvas.get("images", []):
            resource = img.get("resource", {})
            img_id = resource.get("@id", "")
            if img_id:
                images.append(img_id)
    if images:
        meta["image_urls"] = images

    meta["repository"] = "Bayerische Staatsbibliothek"

    return meta


# ---------------------------------------------------------------------------
# Gallica / BnF parser
# ---------------------------------------------------------------------------

def _parse_gallica(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "gallica"}
    meta["title"] = data.get("title", "")
    meta["text"] = data.get("description", "")
    meta["creator"] = data.get("creator", "")
    meta["date_label"] = data.get("date", "")
    meta["language_family"] = data.get("language", "")
    meta["repository"] = "Bibliothèque nationale de France"
    meta["is_public_domain"] = True
    return meta


# ---------------------------------------------------------------------------
# Pleiades parser — ancient places
# ---------------------------------------------------------------------------

def _parse_pleiades(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "pleiades"}

    meta["title"] = data.get("title", "")
    desc = data.get("description", "")
    place_types = data.get("placeTypes", [])

    details_parts = []
    if desc:
        details_parts.append(desc)
    if place_types:
        details_parts.append(f"Type: {', '.join(place_types)}")
    for name_rec in data.get("names", []):
        if isinstance(name_rec, dict):
            romanized = name_rec.get("romanized", "")
            lang = name_rec.get("language", "")
            if romanized:
                details_parts.append(f"Known as: {romanized}" + (f" ({lang})" if lang else ""))
    meta["text"] = "\n".join(details_parts)
    meta["origin_place"] = data.get("title", "")

    repr_point = data.get("reprPoint")
    if isinstance(repr_point, (list, tuple)) and len(repr_point) >= 2:
        meta["longitude"] = repr_point[0]
        meta["latitude"] = repr_point[1]

    connects = data.get("connectsWith", [])
    if connects:
        meta["connected_places"] = connects

    dates = []
    time_periods = set()
    for loc in data.get("locations", []):
        if not isinstance(loc, dict):
            continue
        for tp in loc.get("timePeriods", []):
            if isinstance(tp, dict):
                time_periods.add(tp.get("period", {}).get("label", "") if isinstance(tp.get("period"), dict) else str(tp.get("timePeriod", "")))
    for feat in data.get("features", []):
        if not isinstance(feat, dict):
            continue
        when = feat.get("when", {})
        if isinstance(when, dict):
            start = when.get("start")
            stop = when.get("stop")
            if start or stop:
                dates.append({
                    "type": "archaeological_context",
                    "label": f"{start or '?'} to {stop or '?'}",
                    "confidence": "approximate",
                })
    if dates:
        meta["dates"] = dates
    if time_periods:
        meta["tags"] = [p for p in time_periods if p]

    meta["is_public_domain"] = True

    return meta


# ---------------------------------------------------------------------------
# Open Context parser
# ---------------------------------------------------------------------------

def _parse_open_context(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "open_context"}

    meta["title"] = data.get("label", data.get("dc-terms:title", ""))
    meta["text"] = data.get("dc-terms:description", "")

    geo = data.get("features", [{}])[0].get("geometry", {}) if data.get("features") else {}
    if geo.get("type") == "Point" and geo.get("coordinates"):
        coords = geo["coordinates"]
        meta["longitude"] = coords[0]
        meta["latitude"] = coords[1]

    when = data.get("dc-terms:temporal", "")
    if when:
        meta["dates"] = [{"type": "archaeological_context", "label": str(when), "confidence": "approximate"}]

    context = data.get("context", "")
    if context:
        meta["origin_place"] = str(context)

    meta["is_public_domain"] = True

    return meta


# ---------------------------------------------------------------------------
# UNESCO World Heritage parser
# ---------------------------------------------------------------------------

def _parse_unesco(data: dict) -> dict:
    results = data.get("results", [data])
    rec = results[0] if isinstance(results, list) and results else data

    meta: dict = {"_raw": data, "source_api": "unesco"}

    meta["title"] = rec.get("name_en", rec.get("site", ""))
    desc = rec.get("description_en") or rec.get("short_description_en", "")
    meta["text"] = _strip_html(desc) if desc else ""
    meta["origin_place"] = rec.get("states_names", "")

    coords = rec.get("coordinates", {})
    if isinstance(coords, dict):
        meta["latitude"] = coords.get("lat")
        meta["longitude"] = coords.get("lon")

    year = rec.get("date_inscribed")
    if year:
        meta["dates"] = [{"type": "recorded", "label": f"UNESCO Inscribed {year}", "start": int(year), "end": int(year), "confidence": "certain"}]

    criteria = rec.get("criteria_txt", "")
    if criteria:
        meta["tags"] = [c.strip() for c in str(criteria).split(",") if c.strip()]

    meta["category"] = rec.get("category", "")
    meta["region"] = rec.get("region", "")

    images = []
    main_img = rec.get("main_image_url", "")
    if main_img:
        images.append(main_img)
    extra_imgs = rec.get("images_urls", "")
    if isinstance(extra_imgs, str) and extra_imgs:
        for url in extra_imgs.split(","):
            url = url.strip()
            if url and url.startswith("http") and url not in images:
                images.append(url)
    if images:
        meta["image_urls"] = images[:10]

    meta["is_public_domain"] = True

    return meta


# ---------------------------------------------------------------------------
# OpenAlex parser
# ---------------------------------------------------------------------------

def _parse_openalex(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "openalex"}

    meta["title"] = data.get("display_name", data.get("title", ""))

    abstract_inv = data.get("abstract_inverted_index", {})
    if abstract_inv:
        word_positions = []
        for word, positions in abstract_inv.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        meta["text"] = " ".join(w for _, w in word_positions)
    else:
        meta["text"] = ""

    year = data.get("publication_year")
    if year:
        meta["dates"] = [{"type": "publication", "start": year, "end": year, "label": str(year), "confidence": "certain"}]

    authors = data.get("authorships", [])
    if authors:
        meta["creator"] = "; ".join(
            a.get("author", {}).get("display_name", "") for a in authors[:10] if isinstance(a, dict)
        )

    concepts = data.get("concepts", [])
    if concepts:
        meta["tags"] = [c.get("display_name", "") for c in concepts if isinstance(c, dict)]

    source = data.get("primary_location", {}).get("source", {})
    if source:
        meta["repository"] = source.get("display_name", "")

    meta["doi"] = data.get("doi", "")
    meta["cited_by_count"] = data.get("cited_by_count", 0)

    return meta


# ---------------------------------------------------------------------------
# CORE parser
# ---------------------------------------------------------------------------

def _parse_core(data: dict) -> dict:
    meta: dict = {"_raw": data, "source_api": "core"}

    meta["title"] = data.get("title", "")
    meta["text"] = data.get("abstract", data.get("fullText", ""))[:10000]

    year = data.get("yearPublished")
    if year:
        meta["dates"] = [{"type": "publication", "start": year, "end": year, "label": str(year), "confidence": "certain"}]

    authors = data.get("authors", [])
    if authors:
        meta["creator"] = "; ".join(
            a.get("name", "") if isinstance(a, dict) else str(a) for a in authors[:10]
        )

    meta["language_family"] = data.get("language", {}).get("name", "") if isinstance(data.get("language"), dict) else ""
    meta["doi"] = data.get("doi", "")

    repos = data.get("repositories", [])
    if repos:
        meta["repository"] = repos[0].get("name", "") if isinstance(repos[0], dict) else ""

    return meta


# ---------------------------------------------------------------------------
# TLA (Thesaurus Linguae Aegyptiae) parser
# ---------------------------------------------------------------------------

def _parse_tla(data: dict) -> dict:
    """Parse TLA Hugging Face dataset row (hieroglyphs + transliteration + translation)."""
    rows = data.get("rows", [data])
    row = rows[0].get("row", rows[0]) if isinstance(rows, list) and rows else data

    meta: dict = {"_raw": data, "source_api": "tla"}

    hieroglyphs = row.get("hieroglyphs", "")
    transliteration = row.get("transliteration", "")
    translation = row.get("translation", "")
    glossing = row.get("glossing", "")
    lemmatization = row.get("lemmatization", "")
    upos = row.get("UPOS", "")

    title_parts = []
    if transliteration:
        title_parts.append(transliteration[:80])
    if hieroglyphs:
        title_parts.append(hieroglyphs[:60])
    meta["title"] = " — ".join(title_parts) if title_parts else "TLA Egyptian Text"

    text_parts = []
    if hieroglyphs:
        text_parts.append(f"Hieroglyphs: {hieroglyphs}")
    if transliteration:
        text_parts.append(f"Transliteration: {transliteration}")
    if glossing:
        text_parts.append(f"Glossing: {glossing}")
    if translation:
        text_parts.append(f"Translation: {translation}")
    meta["text"] = "\n".join(text_parts)

    meta["language_family"] = "Egyptian"

    translations = []
    if hieroglyphs:
        translations.append({
            "language": "Egyptian (Hieroglyphic)",
            "text": hieroglyphs,
            "version_type": "original",
        })
    if transliteration:
        translations.append({
            "language": "Egyptian (Transliteration)",
            "text": transliteration,
        })
    if translation:
        lang = "German"
        translations.append({
            "language": lang,
            "text": translation,
        })
    meta["translations"] = translations

    if lemmatization:
        meta["lemmatization"] = lemmatization
    if upos:
        meta["part_of_speech"] = upos
    if glossing:
        meta["glossing"] = glossing

    dates = []
    date_start = row.get("dateNotBefore")
    date_end = row.get("dateNotAfter")
    if date_start or date_end:
        start_val = int(date_start) if date_start else None
        end_val = int(date_end) if date_end else None
        label_parts = []
        if start_val is not None:
            label_parts.append(f"{abs(start_val)} {'BC' if start_val < 0 else 'AD'}")
        if end_val is not None:
            label_parts.append(f"{abs(end_val)} {'BC' if end_val < 0 else 'AD'}")
        dates.append({
            "type": "composition",
            "start": start_val if start_val else -3000,
            "end": end_val if end_val else -300,
            "label": " to ".join(label_parts),
            "confidence": "approximate",
        })
    meta["dates"] = dates

    meta["origin_place"] = "Egypt"
    meta["is_public_domain"] = True
    meta["tags"] = ["hieroglyphic", "egyptian", "ancient text", "TLA"]

    return meta


# ---------------------------------------------------------------------------
# Sacred Texts (sacred-texts.com via Wayback Machine) parser
# ---------------------------------------------------------------------------

_ST_CATEGORY_DATES = {
    "egy": ("Egyptian", -3000, -300),
    "ane": ("Ancient Near East", -3000, -300),
    "hin": ("Hindu", -1500, 0),
    "bud": ("Buddhism", -500, 0),
    "cfu": ("Confucianism", -600, 0),
    "tao": ("Taoism", -600, 0),
    "zor": ("Zoroastrianism", -1500, -300),
    "jai": ("Jainism", -600, 0),
    "jud": ("Judaism", -1200, 0),
    "cla": ("Classics", -800, 0),
    "sbe": ("Sacred Books of the East", -1500, 0),
}


def parse_sacred_texts_html(html: str, external_id: str) -> dict:
    """Parse a sacred-texts.com page fetched via Wayback Machine."""
    meta: dict = {"source_api": "sacred-texts"}

    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = ""
    if title_m:
        title = _strip_html(title_m.group(1))
        title = re.sub(r"\s*\|\s*Internet Sacred Text Archive\s*$", "", title)
        title = re.sub(r"\s*\|\s*Sacred Texts Archive\s*$", "", title)
    if not title:
        title = external_id.replace("st-", "").replace("-", " ")
    meta["title"] = title.strip()

    desc_m = re.search(r'<meta\s+(?:name|property)="(?:og:)?description"\s+content="([^"]*)"', html, re.IGNORECASE)
    if desc_m:
        meta["description"] = _strip_html(desc_m.group(1))

    body_text = html
    for tag in ["<script[^>]*>.*?</script>", "<style[^>]*>.*?</style>",
                "<head[^>]*>.*?</head>", "<nav[^>]*>.*?</nav>",
                "<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->"]:
        body_text = re.sub(tag, " ", body_text, flags=re.IGNORECASE | re.DOTALL)

    hr_parts = re.split(r"<hr[^>]*>", body_text, flags=re.IGNORECASE)
    if len(hr_parts) >= 3:
        body_text = "<hr>".join(hr_parts[1:-1])

    body_text = _strip_html(body_text)
    body_text = re.sub(r"\n{3,}", "\n\n", body_text)
    body_text = body_text.strip()

    meta["text"] = body_text

    path = external_id.removeprefix("st-")
    cat = path.split("-")[0] if "-" in path else ""
    cat_info = _ST_CATEGORY_DATES.get(cat)
    if cat_info:
        label, date_start, date_end = cat_info
        meta["genre"] = label
        meta["dates"] = [{
            "type": "composition",
            "start": date_start,
            "end": date_end,
            "label": f"{label} text ({abs(date_start)}-{abs(date_end)} BC)",
            "confidence": "approximate",
        }]

    meta["language_family"] = "English"
    translations = []
    if body_text:
        translations.append({
            "language": "English",
            "text": body_text,
            "version_type": "translation",
        })
    meta["translations"] = translations

    meta["is_public_domain"] = True
    meta["tags"] = ["sacred text", "translation", "ancient"]
    if cat_info:
        meta["tags"].append(cat_info[0].lower())

    return meta
