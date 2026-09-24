from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="RONN Reader", version="1.1")

MAX_FETCH_BYTES = 3_000_000
MAX_REDIRECTS = 4
USER_AGENT = "RONN-Reader/1.1"


class CrawlBody(BaseModel):
    url: str
    max_chars: int = Field(default=24000, ge=1000, le=60000)


def _public_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only public http/https URLs are supported.")
    host = parsed.hostname.strip().lower()
    if host in {"localhost"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Local addresses are blocked.")
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        for info in infos[:8]:
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                raise HTTPException(status_code=400, detail="Private network addresses are blocked.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Could not resolve that website.")
    return parsed.geturl()


def _markdown_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for attr in ("fit_markdown", "raw_markdown", "markdown_with_citations"):
        v = getattr(value, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    return str(value)


def _read_body(response: requests.Response) -> bytes:
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        room = MAX_FETCH_BYTES - total
        if room <= 0:
            break
        piece = chunk[:room]
        chunks.append(piece)
        total += len(piece)
        if total >= MAX_FETCH_BYTES:
            break
    return b"".join(chunks)


def _http_fallback(url: str, max_chars: int) -> dict:
    """Bounded non-browser reader used when Crawl4AI/Chromium is unavailable."""
    current = _public_url(url)
    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.2",
    }

    response = None
    for _ in range(MAX_REDIRECTS + 1):
        response = session.get(
            current,
            headers=headers,
            timeout=(6, 20),
            allow_redirects=False,
            stream=True,
        )
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RuntimeError("redirect_without_location")
            current = _public_url(urljoin(current, location))
            continue
        break
    else:
        raise RuntimeError("too_many_redirects")

    if response is None:
        raise RuntimeError("no_response")

    try:
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and not any(
            x in content_type for x in ("text/html", "text/plain", "application/xhtml+xml")
        ):
            raise RuntimeError("unsupported_content_type")
        raw = _read_body(response)
        encoding = response.encoding or "utf-8"
    finally:
        response.close()

    html = raw.decode(encoding, errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "template"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = " ".join(str(soup.title.string).split())[:300]

    lines = []
    for line in soup.get_text("\n", strip=True).splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            lines.append(cleaned)
    text = "\n".join(lines)[:max_chars]

    base_host = (urlparse(current).hostname or "").lower()
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(current, str(a.get("href") or "").strip())
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        if (parsed.hostname or "").lower() != base_host:
            continue
        clean = parsed._replace(fragment="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        links.append({"href": clean, "text": " ".join(a.get_text(" ", strip=True).split())[:180]})
        if len(links) >= 40:
            break

    if not text.strip():
        raise RuntimeError("empty_page")

    return {
        "ok": True,
        "url": current,
        "title": title,
        "markdown": text,
        "links": links,
        "reader": "http-fallback",
    }


async def _crawl4ai_read(url: str, max_chars: int) -> dict:
    """Import Crawl4AI only when a crawl is requested so app startup stays fast."""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    browser = BrowserConfig(browser_type="chromium", headless=True, verbose=False)
    run = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=5,
        page_timeout=45000,
        remove_overlay_elements=True,
        exclude_external_links=False,
    )
    async with AsyncWebCrawler(config=browser) as crawler:
        result = await asyncio.wait_for(crawler.arun(url=url, config=run), timeout=55)

    if not getattr(result, "success", False):
        raise RuntimeError((getattr(result, "error_message", "") or "crawl_failed")[:500])

    text = _markdown_text(getattr(result, "markdown", ""))
    if not text.strip():
        text = str(getattr(result, "cleaned_html", "") or "")

    if not text.strip():
        raise RuntimeError("empty_page")

    return {
        "ok": True,
        "url": getattr(result, "url", url),
        "title": (getattr(result, "metadata", {}) or {}).get("title", ""),
        "markdown": text[:max_chars],
        "links": (getattr(result, "links", {}) or {}).get("internal", [])[:40],
        "reader": "crawl4ai",
    }


@app.get("/")
async def root():
    return {"ok": True, "service": "RONN Reader"}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "reader": "hybrid",
        "crawl4ai": "lazy",
        "http_fallback": True,
    }


@app.post("/crawl")
async def crawl(body: CrawlBody):
    url = _public_url(body.url)
    crawl_error = ""
    try:
        return await _crawl4ai_read(url, body.max_chars)
    except asyncio.TimeoutError:
        crawl_error = "TimeoutError"
    except Exception as exc:
        crawl_error = exc.__class__.__name__

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_http_fallback, url, body.max_chars),
            timeout=30,
        )
        result["crawl4ai_error"] = crawl_error
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Page reading timed out.")
    except HTTPException:
        raise
    except Exception as exc:
        detail = f"Reader could not retrieve the page: {exc.__class__.__name__}"
        if crawl_error:
            detail += f" (browser path: {crawl_error})"
        raise HTTPException(status_code=502, detail=detail)
