"""RONN R18 evidence-first research helpers."""
from __future__ import annotations
import re
from r17_browser import fetch as browse

URL_RE=re.compile(r"https?://[^\s)\]>]+",re.I)

def extract_urls(text):
    out=[]
    for u in URL_RE.findall(str(text or "")):
        u=u.rstrip(".,;:")
        if u not in out:out.append(u)
        if len(out)>=8:break
    return out

def collect_pages(urls):
    pages=[]
    for url in list(urls or [])[:5]:
        try:
            p=browse(url)
            pages.append({"url":p["url"],"title":p.get("title",""),"status":p.get("status_code"),"text":p.get("text","")[:16000]})
        except Exception as exc:
            pages.append({"url":url,"error":str(exc)[:240]})
    return pages

def prompt(query,pages=None):
    evidence=""
    for i,p in enumerate(pages or [],1):
        evidence+=f"\nSOURCE {i}: {p.get('url')}\nTITLE: {p.get('title','')}\nTEXT:\n{p.get('text','')[:16000]}\n"
    return """Answer as RONN's evidence-first researcher. Distinguish current verified evidence, background knowledge, inference, and uncertainty.
Prefer recent reliable sources. Never invent citations or claim browsing that is not represented below.
Return a concise answer with source URLs when evidence is supplied.

QUESTION:
"""+str(query)[:20000]+("\n\nBROWSED EVIDENCE:"+evidence if evidence else "")
