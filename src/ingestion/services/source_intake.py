"""AI-Assisted Trusted Source Intake service.

Pipeline: normalize URLs -> group by domain -> fetch samples -> rule-based extraction -> AI classification.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import anthropic
import httpx

from src.ingestion.config import settings
from src.ingestion.schemas.intake import (
    DomainGroup,
    FieldConfidence,
    SuggestedSource,
)

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 12.0
MAX_CONTENT_BYTES = 50_000
MAX_PAGES_PER_DOMAIN = 5
OVERALL_TIMEOUT = 55.0
USER_AGENT = "EdenBot/1.0 (research ingestion platform)"


@dataclass
class PageData:
    url: str
    status: int = 0
    title: str = ""
    meta_description: str = ""
    meta_sitename: str = ""
    language: str = ""
    content_type: str = ""
    content_snippet: str = ""
    has_json_api: bool = False
    has_xml_tei: bool = False
    has_iiif: bool = False
    robots_snippet: str = ""
    error: str = ""


@dataclass
class DomainAnalysis:
    domain: str
    urls: list[str] = field(default_factory=list)
    pages: list[PageData] = field(default_factory=list)
    robots_txt: str = ""


def normalize_urls(raw_urls: list[str]) -> list[str]:
    """Trim, dedupe, reject malformed URLs."""
    seen = set()
    result = []
    for raw in raw_urls:
        url = raw.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                continue
        except Exception:
            continue
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def group_by_domain(urls: list[str]) -> dict[str, list[str]]:
    """Group URLs by their domain."""
    groups: dict[str, list[str]] = {}
    for url in urls:
        domain = urlparse(url).netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        groups.setdefault(domain, []).append(url)
    return groups


async def fetch_page(client: httpx.AsyncClient, url: str) -> PageData:
    """Fetch a single page and extract metadata."""
    page = PageData(url=url)
    try:
        resp = await client.get(
            url,
            follow_redirects=True,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        page.status = resp.status_code
        page.content_type = resp.headers.get("content-type", "")

        if resp.status_code != 200:
            page.error = f"HTTP {resp.status_code}"
            return page

        body = resp.text[:MAX_CONTENT_BYTES]

        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if title_match:
            page.title = html.unescape(title_match.group(1).strip())[:200]

        desc_match = re.search(r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', body, re.IGNORECASE)
        if desc_match:
            page.meta_description = html.unescape(desc_match.group(1).strip())[:300]

        sitename_match = re.search(r'<meta\s+[^>]*property=["\']og:site_name["\'][^>]*content=["\'](.*?)["\']', body, re.IGNORECASE)
        if sitename_match:
            page.meta_sitename = html.unescape(sitename_match.group(1).strip())[:200]

        lang_match = re.search(r'<html[^>]*\slang=["\']([^"\']+)["\']', body, re.IGNORECASE)
        if lang_match:
            page.language = lang_match.group(1).strip()[:10]

        page.has_json_api = bool(re.search(r'application/json|/api/|\.json', body, re.IGNORECASE))
        page.has_xml_tei = bool(re.search(r'text/xml|application/xml|<TEI|xmlns:tei', body, re.IGNORECASE))
        page.has_iiif = bool(re.search(r'iiif\.io|/iiif/|manifest\.json', body, re.IGNORECASE))

        text_content = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)
        text_content = re.sub(r"<style[^>]*>.*?</style>", "", text_content, flags=re.IGNORECASE | re.DOTALL)
        text_content = re.sub(r"<[^>]+>", " ", text_content)
        text_content = re.sub(r"\s+", " ", text_content).strip()
        page.content_snippet = text_content[:1000]

    except Exception as exc:
        page.error = str(exc)[:200]

    return page


async def fetch_robots(client: httpx.AsyncClient, domain: str) -> str:
    """Try fetching robots.txt for a domain."""
    try:
        resp = await client.get(
            f"https://{domain}/robots.txt",
            follow_redirects=True,
            timeout=10.0,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code == 200:
            return resp.text[:2000]
    except Exception:
        pass
    return ""


def rules_based_extraction(analysis: DomainAnalysis) -> tuple[SuggestedSource, FieldConfidence, list[str]]:
    """Extract what we can from fetched pages using rules before AI."""
    source = SuggestedSource()
    conf = FieldConfidence()
    evidence: list[str] = []

    source.domain = analysis.domain
    source.base_url = f"https://{analysis.domain}"
    conf.domain = 1.0
    conf.base_url = 1.0

    all_titles = [p.title for p in analysis.pages if p.title]
    all_sitenames = [p.meta_sitename for p in analysis.pages if p.meta_sitename]
    all_languages = [p.language for p in analysis.pages if p.language]
    all_descriptions = [p.meta_description for p in analysis.pages if p.meta_description]

    if all_sitenames:
        source.name = all_sitenames[0]
        conf.name = 0.85
        evidence.append(f"Site name from og:site_name: '{source.name}'")
    elif all_titles:
        source.name = all_titles[0]
        if len(source.name) > 60:
            source.name = source.name[:60]
        conf.name = 0.65
        evidence.append(f"Name inferred from page title: '{source.name}'")

    if source.name:
        slug = re.sub(r"[^a-z0-9]+", "_", source.name.lower()).strip("_")
        source.slug = slug[:100]
        conf.slug = conf.name * 0.9
    else:
        source.slug = re.sub(r"[^a-z0-9]+", "_", analysis.domain.split(".")[0])
        conf.slug = 0.5

    if all_languages:
        source.default_language = all_languages[0][:5]
        conf.default_language = 0.9
        evidence.append(f"Language detected: {source.default_language}")

    has_api = any(p.has_json_api for p in analysis.pages)
    has_tei = any(p.has_xml_tei for p in analysis.pages)
    has_iiif = any(p.has_iiif for p in analysis.pages)

    if has_tei:
        source.ingestion_method = "xml_feed"
        source.parser_type = "tei_parser"
        conf.ingestion_method = 0.85
        conf.parser_type = 0.85
        evidence.append("TEI/XML content detected")
    elif has_iiif:
        source.ingestion_method = "iiif"
        source.parser_type = "museum_html_parser"
        conf.ingestion_method = 0.85
        conf.parser_type = 0.6
        evidence.append("IIIF manifest patterns detected")
    elif has_api:
        source.ingestion_method = "api"
        source.parser_type = "json_api_parser"
        conf.ingestion_method = 0.75
        conf.parser_type = 0.75
        evidence.append("JSON API endpoints detected")
    else:
        source.ingestion_method = "html_scrape"
        source.parser_type = "museum_html_parser"
        conf.ingestion_method = 0.6
        conf.parser_type = 0.5
        evidence.append("No API detected, defaulting to HTML scrape")

    if analysis.robots_txt:
        if "disallow: /" in analysis.robots_txt.lower() and "allow:" not in analysis.robots_txt.lower():
            evidence.append("robots.txt blocks all crawling — review needed")
            source.license_notes = "robots.txt appears to block all crawling. Review before ingestion."
            conf.license_notes = 0.8
        elif "crawl-delay" in analysis.robots_txt.lower():
            delay_match = re.search(r"crawl-delay:\s*(\d+)", analysis.robots_txt, re.IGNORECASE)
            if delay_match:
                delay = int(delay_match.group(1))
                source.rate_limit_rpm = max(1, 60 // max(delay, 1))
                conf.rate_limit_rpm = 0.8
                evidence.append(f"robots.txt crawl-delay: {delay}s -> {source.rate_limit_rpm} RPM")

    content_combined = " ".join(all_descriptions + [p.content_snippet for p in analysis.pages])[:3000]
    domain_lower = analysis.domain.lower()
    museum_keywords = ["museum", "gallery", "collection", "artifact", "artefact", "exhibition"]
    corpus_keywords = ["corpus", "archive", "database", "catalog", "library", "text", "inscription"]
    if any(kw in domain_lower or kw in content_combined.lower() for kw in museum_keywords):
        source.source_category = "museum_collection"
        conf.source_category = 0.65
        evidence.append("Museum/collection keywords detected")
    elif any(kw in domain_lower or kw in content_combined.lower() for kw in corpus_keywords):
        source.source_category = "text_corpus"
        conf.source_category = 0.65
        evidence.append("Corpus/archive keywords detected")

    return source, conf, evidence


INTAKE_SYSTEM_PROMPT = """You are an expert at analyzing websites for a research ingestion platform focused on ancient history, archaeology, and Near Eastern studies.

Given metadata about a website (page titles, descriptions, content snippets, detected features), classify it as a potential trusted source.

You must respond by calling the classify_source tool with structured JSON output.

VALID VALUES for each field:
- source_category: text_corpus, museum_collection, site_archive, gazetteer, public_domain_library
- trust_tier: primary, secondary, tertiary
- ingestion_method: api, xml_feed, html_scrape, iiif, pdf_download, manual_import
- parser_type: tei_parser, museum_html_parser, json_api_parser, pdf_parser
- is_secondary_source: true if the site contains scholarly commentary/analysis rather than primary source data

GUIDELINES for trust_tier:
- primary: Official corpus, major museum, authoritative database (e.g., CDLI, ORACC, British Museum)
- secondary: Academic publications, scholarly commentary, well-established educational sites
- tertiary: Blogs, personal sites, aggregators, unverified content

For confidence scores: 1.0 = certain, 0.8+ = high, 0.5-0.8 = medium, <0.5 = low/guessing"""

CLASSIFY_TOOL = {
    "name": "classify_source",
    "description": "Classify a website as a potential trusted source for the ingestion platform.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A clear, concise name for this source"},
            "slug": {"type": "string", "description": "URL-safe lowercase slug"},
            "source_category": {"type": "string", "enum": ["text_corpus", "museum_collection", "site_archive", "gazetteer", "public_domain_library"]},
            "trust_tier": {"type": "string", "enum": ["primary", "secondary", "tertiary"]},
            "ingestion_method": {"type": "string", "enum": ["api", "xml_feed", "html_scrape", "iiif", "pdf_download", "manual_import"]},
            "parser_type": {"type": "string", "enum": ["tei_parser", "museum_html_parser", "json_api_parser", "pdf_parser"]},
            "default_language": {"type": "string", "description": "ISO language code"},
            "rate_limit_rpm": {"type": "integer", "description": "Suggested requests per minute"},
            "crawl_frequency_hours": {"type": "integer", "description": "How often to re-crawl"},
            "license_notes": {"type": "string", "description": "Notes about licensing/access restrictions"},
            "notes": {"type": "string", "description": "General notes about this source's content and relevance"},
            "is_secondary_source": {"type": "boolean", "description": "Whether this is a secondary scholarly source rather than primary data"},
            "confidence": {
                "type": "object",
                "properties": {
                    "name": {"type": "number"},
                    "source_category": {"type": "number"},
                    "trust_tier": {"type": "number"},
                    "ingestion_method": {"type": "number"},
                    "parser_type": {"type": "number"},
                    "default_language": {"type": "number"},
                    "rate_limit_rpm": {"type": "number"},
                    "crawl_frequency_hours": {"type": "number"},
                    "license_notes": {"type": "number"},
                    "notes": {"type": "number"},
                },
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Brief reasons supporting the classification",
            },
        },
        "required": ["name", "slug", "source_category", "trust_tier", "ingestion_method", "parser_type", "confidence", "evidence"],
    },
}


async def ai_classify_domain(
    analysis: DomainAnalysis,
    rules_source: SuggestedSource,
    rules_conf: FieldConfidence,
    rules_evidence: list[str],
) -> tuple[SuggestedSource, FieldConfidence, list[str]]:
    """Use Anthropic to refine the rules-based classification."""
    if not settings.anthropic_api_key:
        logger.warning("No Anthropic API key configured, using rules-only classification")
        return rules_source, rules_conf, rules_evidence

    page_summaries = []
    for p in analysis.pages:
        summary = f"URL: {p.url}\n"
        if p.title:
            summary += f"Title: {p.title}\n"
        if p.meta_description:
            summary += f"Description: {p.meta_description}\n"
        if p.meta_sitename:
            summary += f"Site name: {p.meta_sitename}\n"
        if p.language:
            summary += f"Language: {p.language}\n"
        if p.content_snippet:
            summary += f"Content excerpt: {p.content_snippet[:500]}\n"
        if p.has_json_api:
            summary += "Detected: JSON API endpoints\n"
        if p.has_xml_tei:
            summary += "Detected: XML/TEI content\n"
        if p.has_iiif:
            summary += "Detected: IIIF manifests\n"
        page_summaries.append(summary)

    user_message = f"""Analyze this website as a potential trusted source:

Domain: {analysis.domain}

Rules-based pre-analysis:
- Suggested name: {rules_source.name}
- Suggested category: {rules_source.source_category}
- Suggested method: {rules_source.ingestion_method}
- Evidence so far: {'; '.join(rules_evidence)}

Fetched pages:
{'---'.join(page_summaries)}

Robots.txt excerpt:
{analysis.robots_txt[:500] if analysis.robots_txt else 'Not available'}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": INTAKE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_message}],
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_source"},
        )

        for block in response.content:
            if block.type == "tool_use":
                data = block.input
                source = SuggestedSource(
                    name=data.get("name", rules_source.name),
                    slug=data.get("slug", rules_source.slug),
                    domain=analysis.domain,
                    base_url=f"https://{analysis.domain}",
                    source_category=data.get("source_category", rules_source.source_category),
                    trust_tier=data.get("trust_tier", rules_source.trust_tier),
                    ingestion_method=data.get("ingestion_method", rules_source.ingestion_method),
                    parser_type=data.get("parser_type", rules_source.parser_type),
                    priority=100,
                    default_language=data.get("default_language", rules_source.default_language),
                    rate_limit_rpm=data.get("rate_limit_rpm", rules_source.rate_limit_rpm),
                    crawl_frequency_hours=data.get("crawl_frequency_hours", rules_source.crawl_frequency_hours),
                    license_notes=data.get("license_notes", rules_source.license_notes),
                    notes=data.get("notes", rules_source.notes),
                    is_secondary_source=data.get("is_secondary_source", False),
                )

                ai_conf = data.get("confidence", {})
                conf = FieldConfidence(
                    name=ai_conf.get("name", rules_conf.name),
                    slug=ai_conf.get("name", rules_conf.slug) * 0.9,
                    domain=1.0,
                    base_url=1.0,
                    source_category=ai_conf.get("source_category", rules_conf.source_category),
                    trust_tier=ai_conf.get("trust_tier", rules_conf.trust_tier),
                    ingestion_method=ai_conf.get("ingestion_method", rules_conf.ingestion_method),
                    parser_type=ai_conf.get("parser_type", rules_conf.parser_type),
                    default_language=ai_conf.get("default_language", rules_conf.default_language),
                    rate_limit_rpm=ai_conf.get("rate_limit_rpm", rules_conf.rate_limit_rpm),
                    crawl_frequency_hours=ai_conf.get("crawl_frequency_hours", rules_conf.crawl_frequency_hours),
                    license_notes=ai_conf.get("license_notes", rules_conf.license_notes),
                    notes=ai_conf.get("notes", rules_conf.notes),
                )

                ai_evidence = data.get("evidence", [])
                all_evidence = rules_evidence + [f"[AI] {e}" for e in ai_evidence]

                return source, conf, all_evidence

    except Exception as exc:
        logger.error("Anthropic classification failed for %s: %s", analysis.domain, exc)
        rules_evidence.append(f"[AI] Classification failed: {str(exc)[:100]}")

    return rules_source, rules_conf, rules_evidence


async def _analyze_single_domain(
    client: httpx.AsyncClient,
    domain: str,
    domain_urls: list[str],
) -> DomainGroup:
    """Analyze a single domain: fetch pages concurrently, run rules, then AI."""
    analysis = DomainAnalysis(domain=domain, urls=domain_urls)

    urls_to_fetch = domain_urls[:MAX_PAGES_PER_DOMAIN]
    homepage_url = f"https://{domain}"
    need_homepage = homepage_url not in domain_urls

    fetch_tasks = [fetch_page(client, url) for url in urls_to_fetch]
    if need_homepage:
        fetch_tasks.append(fetch_page(client, homepage_url))
    fetch_tasks.append(fetch_robots(client, domain))

    fetched = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    robots_result = fetched[-1]
    if isinstance(robots_result, str):
        analysis.robots_txt = robots_result

    page_results = fetched[:-1]
    for i, result in enumerate(page_results):
        if isinstance(result, Exception):
            logger.warning("Fetch failed for %s: %s", urls_to_fetch[i] if i < len(urls_to_fetch) else homepage_url, result)
            continue
        if isinstance(result, PageData):
            if need_homepage and i == len(urls_to_fetch) and not result.error:
                analysis.pages.insert(0, result)
            else:
                analysis.pages.append(result)

    rules_source, rules_conf, rules_evidence = rules_based_extraction(analysis)

    source, conf, evidence = await ai_classify_domain(
        analysis, rules_source, rules_conf, rules_evidence
    )

    return DomainGroup(
        domain=domain,
        urls=domain_urls,
        suggested_source=source,
        confidence=conf,
        evidence=evidence,
    )


async def analyze_urls(urls: list[str]) -> list[DomainGroup]:
    """Full intake pipeline: normalize -> group -> fetch -> rules -> AI -> return candidates."""
    clean_urls = normalize_urls(urls)
    if not clean_urls:
        return []

    domain_groups = group_by_domain(clean_urls)

    async with httpx.AsyncClient() as client:
        tasks = [
            _analyze_single_domain(client, domain, domain_urls)
            for domain, domain_urls in domain_groups.items()
        ]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=OVERALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("Intake analysis timed out after %.0fs", OVERALL_TIMEOUT)
            raise TimeoutError(f"Analysis timed out after {OVERALL_TIMEOUT:.0f}s. Try fewer URLs.")

    final: list[DomainGroup] = []
    for r in results:
        if isinstance(r, DomainGroup):
            final.append(r)
        elif isinstance(r, Exception):
            logger.error("Domain analysis failed: %s", r)

    return final
