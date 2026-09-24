from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

_CRAWL4AI_COMPONENTS = None


def _crawler_components():
    """Load Crawl4AI only when a crawl is actually requested.

    Render can start and health-check the Reader without importing the entire
    browser/crawler stack. Python caches the imported modules after first use.
    """
    global _CRAWL4AI_COMPONENTS
    if _CRAWL4AI_COMPONENTS is None:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
        _CRAWL4AI_COMPONENTS=(AsyncWebCrawler,BrowserConfig,CrawlerRunConfig,CacheMode)
    return _CRAWL4AI_COMPONENTS

app = FastAPI(title="RONN Reader", version="1.0")

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
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        for info in infos[:8]:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
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

@app.get("/health")
async def health():
    return {
        "ok": True,
        "reader": "crawl4ai",
        "crawler_load": "ready" if _CRAWL4AI_COMPONENTS is not None else "lazy",
    }

@app.post("/crawl")
async def crawl(body: CrawlBody):
    url = _public_url(body.url)
    try:
        AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode = _crawler_components()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Crawl4AI runtime is unavailable: {exc.__class__.__name__}",
        )
    browser = BrowserConfig(browser_type="chromium", headless=True, verbose=False)
    run = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=5,
        page_timeout=45000,
        remove_overlay_elements=True,
        exclude_external_links=False,
    )
    try:
        async with AsyncWebCrawler(config=browser) as crawler:
            result = await asyncio.wait_for(crawler.arun(url=url, config=run), timeout=55)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Page reading timed out.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Crawl4AI could not read the page: {exc.__class__.__name__}")

    if not getattr(result, "success", False):
        raise HTTPException(status_code=502, detail=(getattr(result, "error_message", "") or "Crawl failed")[:500])

    text = _markdown_text(getattr(result, "markdown", ""))
    if not text.strip():
        text = str(getattr(result, "cleaned_html", "") or "")

    return {
        "ok": True,
        "url": getattr(result, "url", url),
        "title": (getattr(result, "metadata", {}) or {}).get("title", ""),
        "markdown": text[: body.max_chars],
        "links": (getattr(result, "links", {}) or {}).get("internal", [])[:40],
    }
