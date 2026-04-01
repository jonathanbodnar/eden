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

    # Dates
    dates_ref = art.get("dates_referenced")
    if dates_ref and dates_ref != "00.00.00.00":
        meta["dates"] = [{"label": dates_ref, "type": "object_creation", "confidence": "uncertain"}]
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

    # Images
    images = []
    for img_field in ("images", "photos"):
        for img in art.get(img_field, []):
            if isinstance(img, dict) and img.get("url"):
                images.append(img["url"])
            elif isinstance(img, str):
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
