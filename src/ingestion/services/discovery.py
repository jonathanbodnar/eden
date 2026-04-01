"""Website discovery: crawl a source's domain to find content pages."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from src.ingestion.models.enums import IngestionMethod

logger = logging.getLogger(__name__)

CRAWL_TIMEOUT = 15.0
MAX_CONTENT_BYTES = 200_000
MAX_PAGES = 200
MAX_DEPTH = 3
CONCURRENCY = 5
USER_AGENT = "EdenBot/1.0 (research ingestion platform)"

SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".avi", ".mov",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".xml", ".rss", ".atom", ".json",
}

SKIP_PATH_PATTERNS = re.compile(
    r"/(login|logout|register|signup|cart|checkout|admin|wp-admin|feed|tag|author"
    r"|comment|reply|print|share|search|page/\d+|cdn-cgi|\.well-known)/",
    re.IGNORECASE,
)

CONTENT_SIGNALS = re.compile(
    r"<article|<main|class=[\"'][^\"']*(?:entry|post|content|article|record|object|item)[^\"']*[\"']",
    re.IGNORECASE,
)


@dataclass
class DiscoveredPage:
    url: str
    external_id: str
    title: str = ""
    content_hint: str = ""
    depth: int = 0


@dataclass
class CrawlResult:
    pages: list[DiscoveredPage] = field(default_factory=list)
    pages_visited: int = 0
    errors: int = 0


def _url_to_external_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_same_domain(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    domain = domain.lower()
    return host == domain or host.endswith(f".{domain}")


def _should_skip_url(url: str) -> bool:
    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    if any(path_lower.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True

    if SKIP_PATH_PATTERNS.search(parsed.path):
        return True

    if parsed.fragment:
        return True

    return False


def _extract_links(body: str, base_url: str) -> list[str]:
    links = []
    for match in re.finditer(r'<a\s[^>]*href=["\']([^"\'#]+)["\']', body, re.IGNORECASE):
        href = match.group(1).strip()
        if href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        links.append(_normalize_url(absolute))
    return links


def _extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if match:
        return html.unescape(match.group(1).strip())[:300]
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.IGNORECASE | re.DOTALL)
    if h1:
        text = re.sub(r"<[^>]+>", "", h1.group(1))
        return html.unescape(text.strip())[:300]
    return ""


def _has_content(body: str) -> bool:
    """Heuristic: does this page look like a content page vs navigation/index."""
    text_only = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)
    text_only = re.sub(r"<style[^>]*>.*?</style>", "", text_only, flags=re.IGNORECASE | re.DOTALL)
    text_only = re.sub(r"<[^>]+>", " ", text_only)
    text_only = re.sub(r"\s+", " ", text_only).strip()

    if len(text_only) < 500:
        return False

    if CONTENT_SIGNALS.search(body):
        return True

    paragraph_count = len(re.findall(r"<p[\s>]", body, re.IGNORECASE))
    return paragraph_count >= 3


async def _fetch_page(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[str, str, int]:
    """Returns (body, content_type, status_code). Empty body on error."""
    try:
        resp = await client.get(
            url,
            follow_redirects=True,
            timeout=CRAWL_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        ct = resp.headers.get("content-type", "")
        if resp.status_code != 200 or "text/html" not in ct.lower():
            return "", ct, resp.status_code
        return resp.text[:MAX_CONTENT_BYTES], ct, resp.status_code
    except Exception as exc:
        logger.debug("Fetch failed for %s: %s", url, exc)
        return "", "", 0


async def crawl_html_source(
    base_url: str,
    domain: str,
    max_pages: int = MAX_PAGES,
    max_depth: int = MAX_DEPTH,
) -> CrawlResult:
    """BFS crawl a website to discover content pages."""
    result = CrawlResult()
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(_normalize_url(base_url), 0)]
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient() as client:
        while queue and len(result.pages) < max_pages:
            batch = []
            while queue and len(batch) < CONCURRENCY:
                url, depth = queue.pop(0)
                if url in visited:
                    continue
                if depth > max_depth:
                    continue
                visited.add(url)
                batch.append((url, depth))

            if not batch:
                break

            async def process_url(url: str, depth: int) -> None:
                async with semaphore:
                    body, ct, status = await _fetch_page(client, url)
                    result.pages_visited += 1

                    if not body:
                        if status != 200 and status != 0:
                            result.errors += 1
                        return

                    title = _extract_title(body)

                    if _has_content(body) and depth > 0:
                        result.pages.append(DiscoveredPage(
                            url=url,
                            external_id=_url_to_external_id(url),
                            title=title,
                            depth=depth,
                        ))

                    if depth < max_depth and len(result.pages) < max_pages:
                        for link in _extract_links(body, url):
                            if link not in visited and _is_same_domain(link, domain) and not _should_skip_url(link):
                                queue.append((link, depth + 1))

            tasks = [process_url(url, depth) for url, depth in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(
        "Crawl of %s complete: %d content pages found, %d pages visited, %d errors",
        domain, len(result.pages), result.pages_visited, result.errors,
    )
    return result


async def discover_source(
    ingestion_method: str,
    base_url: str,
    domain: str,
    max_pages: int = MAX_PAGES,
) -> CrawlResult:
    """Dispatch discovery based on ingestion method."""
    method = ingestion_method
    if isinstance(ingestion_method, IngestionMethod):
        method = ingestion_method.value

    if method in ("html_scrape", "pdf_download"):
        return await crawl_html_source(base_url, domain, max_pages=max_pages)

    if method in ("api", "xml_feed", "iiif"):
        return await crawl_html_source(base_url, domain, max_pages=min(max_pages, 50))

    if method == "manual_import":
        return CrawlResult()

    return await crawl_html_source(base_url, domain, max_pages=max_pages)
