"""RONN R17 safe text-browser agent.

Fetches public HTTP(S) pages, rejects private/local addresses, extracts readable
text and links, and returns evidence metadata. It is not a hidden desktop browser.
"""
from __future__ import annotations
import ipaddress, re, socket, time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import requests

UA="RONN/17 Browser Agent"
MAX_BYTES=2_000_000
MAX_TEXT=45_000

class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.title=""; self._in_title=False; self.text=[]; self.links=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="title":self._in_title=True
        if tag=="a" and d.get("href"):self.links.append((d.get("href"),""))
    def handle_endtag(self,tag):
        if tag=="title":self._in_title=False
    def handle_data(self,data):
        s=re.sub(r"\s+"," ",data).strip()
        if not s:return
        if self._in_title:self.title=(self.title+" "+s).strip()
        if len(s)>1:self.text.append(s)
        if self.links and not self.links[-1][1]:
            href,_=self.links[-1]; self.links[-1]=(href,s[:160])

def normalize_url(url):
    u=str(url or "").strip()
    if not u:raise ValueError("URL is required.")
    if "://" not in u:u="https://"+u
    p=urlparse(u)
    if p.scheme not in {"http","https"} or not p.hostname:
        raise ValueError("Only public http/https URLs are allowed.")
    if p.username is not None or p.password is not None:
        raise ValueError("URL credentials are not allowed.")
    try:
        port=p.port
    except ValueError:
        raise ValueError("Invalid URL port.")
    expected_port=443 if p.scheme=="https" else 80
    if port is not None and port!=expected_port:
        raise ValueError("Only standard web ports are allowed.")
    return p.geturl()

def _public_host(url):
    url=normalize_url(url)
    p=urlparse(url)
    host=p.hostname
    if not host:raise ValueError("URL has no host.")
    if host.lower() in {"localhost","localhost.localdomain"}:raise ValueError("Local addresses are blocked.")
    try:
        infos=socket.getaddrinfo(host,p.port or (443 if p.scheme=="https" else 80),type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Host could not be resolved: {exc}")
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Private/local network targets are blocked.")
    return True

def fetch(url,timeout=12):
    url=normalize_url(url)
    started=time.time()
    with requests.Session() as session:
        session.trust_env=False
        r=None
        for _hop in range(6):
            _public_host(url)
            r=session.get(
                url,
                headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.2"},
                timeout=max(3,min(int(timeout),20)),
                allow_redirects=False,
                stream=True,
            )
            if r.status_code in {301,302,303,307,308} and r.headers.get("location"):
                nxt=urljoin(url,r.headers["location"])
                r.close()
                url=normalize_url(nxt)
                continue
            break

        if r is None:
            raise ValueError("Browser request could not start.")
        if r.status_code in {301,302,303,307,308}:
            r.close()
            raise ValueError("Too many redirects.")

        try:
            final=normalize_url(r.url)
            _public_host(final)
            chunks=[]; total=0
            for chunk in r.iter_content(65536):
                if not chunk:continue
                total+=len(chunk)
                if total>MAX_BYTES:break
                chunks.append(chunk)
            raw=b"".join(chunks)
            ctype=(r.headers.get("content-type") or "").lower()
            enc=r.encoding or "utf-8"
            text=raw.decode(enc,errors="replace")
            if "html" in ctype or "<html" in text[:1000].lower():
                x=Extractor(); x.feed(text)
                body="\n".join(x.text)
                links=[]
                seen=set()
                for href,label in x.links:
                    try:
                        absolute=normalize_url(urljoin(final,href))
                    except ValueError:
                        continue
                    if absolute in seen:continue
                    seen.add(absolute); links.append({"text":label or absolute,"url":absolute})
                    if len(links)>=80:break
                title=x.title[:300]
            else:
                body=text; links=[]; title=""
            body=re.sub(r"\n{3,}","\n\n",body)[:MAX_TEXT]
            return {
                "ok":bool(r.ok),
                "status_code":r.status_code,
                "url":final,
                "title":title,
                "text":body,
                "links":links,
                "bytes":len(raw),
                "content_type":ctype,
                "elapsed_ms":round((time.time()-started)*1000,2),
            }
        finally:
            r.close()

def follow(page,index):
    links=page.get("links") or []
    i=int(index)
    if i<0 or i>=len(links):raise IndexError("Link index out of range.")
    return fetch(links[i]["url"])
