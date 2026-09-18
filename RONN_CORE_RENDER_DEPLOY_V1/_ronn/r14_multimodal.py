"""RONN R14 multimodal task planner."""
from __future__ import annotations
import re

def plan(message, image_count=0, files=None):
    low=str(message or "").lower()
    files=list(files or [])
    names=[str(getattr(f,"name","")).lower() for f in files]
    kinds=[]
    if image_count: kinds.append("image")
    if any(n.endswith(".pdf") for n in names): kinds.append("pdf")
    if any(n.endswith((".py",".js",".ts",".lua",".luau",".html",".css",".json")) for n in names): kinds.append("code")
    if any(n.endswith((".csv",".xlsx")) for n in names): kinds.append("table")
    if any(n.endswith((".docx",".txt",".md")) for n in names): kinds.append("document")
    screenshot=bool(image_count and any(x in low for x in ("screenshot","screen","ui","button","page","error")))
    return {
      "modalities":kinds,"image_count":int(image_count),"file_count":len(files),
      "screenshot_mode":screenshot,
      "needs_cross_modal":bool(image_count and files),
      "instruction":"Inspect visible evidence before inferring hidden state; connect image evidence to the user's text and attached files."
    }

def directive(p):
    if not p["modalities"]: return ""
    extra=" Treat the image as a UI screenshot: describe visible state and do not infer off-screen controls." if p["screenshot_mode"] else ""
    return "RONN MULTIMODAL PLAN: "+p["instruction"]+extra
