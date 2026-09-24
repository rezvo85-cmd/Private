from __future__ import annotations

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

_CRAWL4AI_COMPONENTS = None
MAX_FETCH_BYTES = 3_000_000
MAX_REDIRECTS = 4
USER_AGENT = "RONN-Reader/1.2"


def _crawler_components():
    """Load Crawl4AI only when a crawl is actually requested."""
    global _CRAWL4AI_COMPONENTS
    if _CRAWL4AI_COMPONENTS is None:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
        _CRAWL4AI_COMPONENTS=(AsyncWebCrawler,BrowserConfig,CrawlerRunConfig,CacheMode)
    return _CRAWL4AI_COMPONENTS


app = FastAPI(title="RONN Reader", version="1.2")


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


class _HTMLTextParser(HTMLParser):
    SKIP={"script","style","noscript","svg","canvas","template"}

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url=base_url
        self.skip_depth=0
        self.in_title=False
        self.title_parts=[]
        self.text_parts=[]
        self.links=[]
        self._seen_links=set()

    def handle_starttag(self, tag, attrs):
        tag=tag.lower()
        if tag in self.SKIP:
            self.skip_depth+=1
            return
        if self.skip_depth:
            return
        if tag=="title":
            self.in_title=True
        if tag=="a":
            href=dict(attrs).get("href")
            if not href:
                return
            absolute=urljoin(self.base_url,str(href).strip())
            parsed=urlparse(absolute)
            base_host=(urlparse(self.base_url).hostname or "").lower()
            if parsed.scheme not in {"http","https"}:
                return
            if (parsed.hostname or "").lower()!=base_host:
                return
            clean=parsed._replace(fragment="").geturl()
            if clean not in self._seen_links and len(self.links)<40:
                self._seen_links.add(clean)
                self.links.append({"href":clean})

    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth-=1
            return
        if tag=="title":
            self.in_title=False

    def handle_data(self, data):
        if self.skip_depth:
            return
        text=" ".join(str(data or "").split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        self.text_parts.append(text)


def _parse_html(html: str, base_url: str, max_chars: int) -> dict:
    parser=_HTMLTextParser(base_url)
    parser.feed(str(html or ""))
    parser.close()
    text="\n".join(parser.text_parts)[:max_chars]
    return {
        "title":" ".join(parser.title_parts)[:300],
        "markdown":text,
        "links":parser.links[:40],
    }


def _read_limited(response: requests.Response) -> bytes:
    out=[]
    total=0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        room=MAX_FETCH_BYTES-total
        if room<=0:
            break
        piece=chunk[:room]
        out.append(piece)
        total+=len(piece)
        if total>=MAX_FETCH_BYTES:
            break
    return b"".join(out)


def _http_fallback(url: str, max_chars: int) -> dict:
    """Browser-independent reader used when Chromium/Crawl4AI is unavailable."""
    current=_public_url(url)
    session=requests.Session()
    response=None
    headers={
        "User-Agent":USER_AGENT,
        "Accept":"text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.2",
    }

    for _ in range(MAX_REDIRECTS+1):
        response=session.get(
            current,
            headers=headers,
            timeout=(6,20),
            allow_redirects=False,
            stream=True,
        )
        if 300<=response.status_code<400:
            location=response.headers.get("Location")
            response.close()
            if not location:
                raise RuntimeError("redirect_without_location")
            current=_public_url(urljoin(current,location))
            response=None
            continue
        break
    else:
        raise RuntimeError("too_many_redirects")

    if response is None:
        raise RuntimeError("no_response")

    try:
        response.raise_for_status()
        content_type=(response.headers.get("Content-Type") or "").lower()
        allowed=(
            not content_type
            or "text/html" in content_type
            or "text/plain" in content_type
            or "application/xhtml+xml" in content_type
        )
        if not allowed:
            raise RuntimeError("unsupported_content_type")
        raw=_read_limited(response)
        encoding=response.encoding or "utf-8"
    finally:
        response.close()

    body=raw.decode(encoding,errors="replace")
    if "text/plain" in content_type:
        text=body[:max_chars]
        parsed={"title":"","markdown":text,"links":[]}
    else:
        parsed=_parse_html(body,current,max_chars)

    if not str(parsed.get("markdown") or "").strip():
        raise RuntimeError("empty_page")

    return {
        "ok":True,
        "url":current,
        "title":parsed.get("title") or "",
        "markdown":str(parsed.get("markdown") or "")[:max_chars],
        "links":parsed.get("links") or [],
        "reader":"http-fallback",
    }


async def _crawl4ai_read(url: str, max_chars: int) -> dict:
    AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode = _crawler_components()
    browser=BrowserConfig(browser_type="chromium",headless=True,verbose=False)
    run=CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=5,
        page_timeout=45000,
        remove_overlay_elements=True,
        exclude_external_links=False,
    )
    async with AsyncWebCrawler(config=browser) as crawler:
        result=await asyncio.wait_for(crawler.arun(url=url,config=run),timeout=55)

    if not getattr(result,"success",False):
        raise RuntimeError((getattr(result,"error_message","") or "crawl_failed")[:500])

    text=_markdown_text(getattr(result,"markdown",""))
    if not text.strip():
        text=str(getattr(result,"cleaned_html","") or "")
    if not text.strip():
        raise RuntimeError("empty_page")

    return {
        "ok":True,
        "url":getattr(result,"url",url),
        "title":(getattr(result,"metadata",{}) or {}).get("title",""),
        "markdown":text[:max_chars],
        "links":(getattr(result,"links",{}) or {}).get("internal",[])[:40],
        "reader":"crawl4ai",
    }


@app.get("/")
async def root():
    return {"ok":True,"service":"RONN Reader","version":"1.2"}


@app.get("/health")
async def health():
    return {
        "ok":True,
        "reader":"hybrid",
        "crawler_load":"ready" if _CRAWL4AI_COMPONENTS is not None else "lazy",
        "http_fallback":True,
    }


@app.post("/crawl")
async def crawl(body: CrawlBody):
    url=_public_url(body.url)
    browser_error=""
    try:
        return await _crawl4ai_read(url,body.max_chars)
    except asyncio.TimeoutError:
        browser_error="TimeoutError"
    except Exception as exc:
        browser_error=exc.__class__.__name__

    try:
        fallback=await asyncio.wait_for(
            asyncio.to_thread(_http_fallback,url,body.max_chars),
            timeout=30,
        )
        fallback["browser_error"]=browser_error
        return fallback
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504,detail="Page reading timed out.")
    except HTTPException:
        raise
    except Exception as exc:
        detail=f"Reader could not retrieve the page: {exc.__class__.__name__}"
        if browser_error:
            detail+=f" (browser path: {browser_error})"
        raise HTTPException(status_code=502,detail=detail)
