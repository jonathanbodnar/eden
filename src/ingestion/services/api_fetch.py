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

def _parse_cdli(art: dict) -> dict:
    meta: dict = {
        "source_api": "cdli",
        "cdli_id": art.get("id"),
    }

    meta["title"] = art.get("designation", "")
    meta["museum_no"] = art.get("museum_no", "")
    meta["excavation_no"] = art.get("excavation_no", "")

    for field in ("height", "width", "thickness"):
        if art.get(field):
            meta.setdefault("dimensions_parsed", {})[field] = art[field]
    dims = meta.get("dimensions_parsed", {})
    if dims:
        meta["dimensions"] = " x ".join(
            f"{v}mm ({k})" for k, v in dims.items()
        )

    period = art.get("period")
    if isinstance(period, dict):
        meta["period"] = period.get("name", str(period))
    elif period:
        meta["period"] = str(period)

    prov = art.get("provenience")
    if isinstance(prov, dict):
        meta["origin_place"] = prov.get("provenience", prov.get("name", str(prov)))
    elif prov:
        meta["origin_place"] = str(prov)

    meta["findspot_comments"] = art.get("findspot_comments", "")
    meta["findspot_square"] = art.get("findspot_square", "")

    genres = art.get("genres", [])
    if genres:
        genre_names = []
        for g in genres:
            if isinstance(g, dict):
                ginfo = g.get("genre", {})
                name = ginfo.get("genre", "") if isinstance(ginfo, dict) else str(ginfo)
                comment = g.get("comments", "")
                genre_names.append(f"{name}: {comment}".strip(": ") if comment else name)
        meta["genre"] = "; ".join(genre_names) if genre_names else ""
    else:
        genre = art.get("genre")
        if isinstance(genre, dict):
            meta["genre"] = genre.get("name", str(genre))
        elif genre:
            meta["genre"] = str(genre)

    languages = art.get("languages", [])
    if languages:
        lang_names = []
        for l in languages:
            if isinstance(l, dict):
                linfo = l.get("language", {})
                name = linfo.get("language", "") if isinstance(linfo, dict) else str(linfo)
                if name and name != "undetermined":
                    lang_names.append(name)
        meta["language_family"] = ", ".join(lang_names) if lang_names else ""
    if not meta.get("language_family"):
        lang = art.get("language")
        if isinstance(lang, dict):
            meta["language_family"] = lang.get("name", str(lang))
        elif lang:
            meta["language_family"] = str(lang)

    materials = art.get("materials", [])
    if materials:
        mat_names = []
        for m in materials:
            if isinstance(m, dict):
                minfo = m.get("material", {})
                mat_names.append(minfo.get("material", str(minfo)) if isinstance(minfo, dict) else str(minfo))
        meta["medium"] = ", ".join(mat_names) if mat_names else ""
    if not meta.get("medium"):
        material = art.get("material")
        if isinstance(material, dict):
            meta["medium"] = material.get("name", str(material))
        elif material:
            meta["medium"] = str(material)

    art_type = art.get("artifact_type") or art.get("artifactType")
    if isinstance(art_type, dict):
        meta["object_type"] = art_type.get("name", art_type.get("artifact_type", str(art_type)))
    elif art_type:
        meta["object_type"] = str(art_type)

    collections = art.get("collections", [])
    if collections:
        col = collections[0]
        if isinstance(col, dict):
            cinfo = col.get("collection", {})
            if isinstance(cinfo, dict):
                meta["repository"] = cinfo.get("collection", "")
                meta["repository_url"] = cinfo.get("collection_url", "")
                meta["repository_country"] = cinfo.get("country_iso", "")
                lat = cinfo.get("location_latitude_wgs1984")
                lon = cinfo.get("location_longitude_wgs1984")
                if lat and lon:
                    meta["repository_coords"] = {"lat": lat, "lon": lon}
            else:
                meta["repository"] = str(cinfo)
    if not meta.get("repository"):
        collection = art.get("collection")
        if isinstance(collection, dict):
            meta["repository"] = collection.get("name", str(collection))
        elif collection:
            meta["repository"] = str(collection)

    inscription = art.get("inscription")
    if isinstance(inscription, dict):
        atf = inscription.get("atf", "")
        if atf:
            meta["text"] = atf
            meta["text_format"] = "ATF"

    composites = art.get("composites", [])
    if composites:
        meta["composites"] = []
        for c in composites[:5]:
            if isinstance(c, dict):
                comp = c.get("composite", {})
                meta["composites"].append({
                    "composite_no": c.get("composite_no", ""),
                    "designation": comp.get("designation", "") if isinstance(comp, dict) else "",
                })

    ext_res = art.get("external_resources", [])
    if ext_res:
        meta["external_resources"] = []
        for er in ext_res[:10]:
            if isinstance(er, dict):
                res = er.get("external_resource", {})
                if isinstance(res, dict):
                    meta["external_resources"].append({
                        "name": res.get("external_resource", ""),
                        "abbrev": res.get("abbrev", ""),
                        "url": (res.get("base_url", "") + er.get("external_resource_key", "")).strip(),
                    })

    dates = art.get("dates_referenced")
    if dates and dates != "00.00.00.00":
        meta["dates"] = [{"label": dates, "type": "object_creation", "confidence": "uncertain"}]

    pubs = art.get("publications", [])
    if pubs:
        meta["publications"] = []
        for p in pubs[:10]:
            if not isinstance(p, dict):
                continue
            pub = p.get("publication", {})
            entry = {
                "designation": pub.get("designation", "") if isinstance(pub, dict) else "",
                "exact_reference": p.get("exact_reference", ""),
            }
            if isinstance(pub, dict):
                entry["title"] = pub.get("title", "")
                entry["year"] = pub.get("year")
                authors = pub.get("authors", [])
                if authors:
                    entry["authors"] = [
                        a.get("author", {}).get("author", "")
                        for a in authors[:5]
                        if isinstance(a, dict)
                    ]
            meta["publications"].append(entry)

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
    meta: dict = {
        "source_api": "met",
        "met_object_id": obj.get("objectID"),
    }

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

    origin_parts = [obj.get("city"), obj.get("state"), obj.get("country"),
                     obj.get("region"), obj.get("subregion"), obj.get("locale")]
    meta["origin_place"] = " ".join(filter(None, origin_parts)).strip()
    if obj.get("geographyType"):
        meta["geography_type"] = obj["geographyType"]
    if obj.get("excavation"):
        meta["excavation"] = obj["excavation"]
    if obj.get("locus"):
        meta["locus"] = obj["locus"]
    if obj.get("river"):
        meta["river"] = obj["river"]

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

    tags = obj.get("tags") or []
    if tags:
        meta["tags"] = [t.get("term", "") for t in tags if isinstance(t, dict)]

    images = []
    if obj.get("primaryImage"):
        images.append(obj["primaryImage"])
    for img in obj.get("additionalImages", []):
        if img and img not in images:
            images.append(img)
    if images:
        meta["image_urls"] = images

    constituents = obj.get("constituents") or []
    if constituents:
        meta["artists"] = [
            {"name": c.get("name", ""), "role": c.get("role", "")}
            for c in constituents
            if isinstance(c, dict)
        ]

    meta["is_public_domain"] = obj.get("isPublicDomain", False)
    meta["object_url"] = obj.get("objectURL", "")
    meta["accession_number"] = obj.get("accessionNumber", "")
    meta["accession_year"] = obj.get("accessionYear", "")

    if obj.get("measurements"):
        meta["measurements_parsed"] = obj["measurements"]

    meta["gallery_number"] = obj.get("GalleryNumber", "")
    meta["is_highlight"] = obj.get("isHighlight", False)

    geo = {}
    for f in ("geographyType", "city", "state", "county", "country",
              "region", "subregion", "locale", "locus", "excavation", "river"):
        if obj.get(f):
            geo[f] = obj[f]
    if geo:
        meta["geography"] = geo

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
