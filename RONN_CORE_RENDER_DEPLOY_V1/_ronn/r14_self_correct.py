"""RONN R14 deterministic self-correction gate."""
from __future__ import annotations
import re

RISK_TERMS=("definitely","guaranteed","100%","fixed","working","verified","tested","deployed","live","i checked","i ran","i opened")

def inspect(question,answer,tool_evidence=False):
    q=str(question or "").lower(); a=str(answer or "")
    low=a.lower(); issues=[]
    if not a.strip(): issues.append("empty_answer")
    if len(a)>12000 and len(q)<180: issues.append("verbosity_mismatch")
    if not tool_evidence and any(x in low for x in RISK_TERMS):
        issues.append("unsupported_completion_or_verification_language")
    if "http" in low and "source" in q and not re.search(r"https?://",a):
        issues.append("missing_source_link")
    if any(x in q for x in ("short","brief","simple")) and len(a)>1800:
        issues.append("requested_brevity_missed")
    if q.count("?") and len(a.strip())<3:
        issues.append("non_answer")
    return {"needs_repair":bool(issues),"issues":issues,"score":max(0,100-len(issues)*22)}

def reviewer_instruction(report):
    if not report.get("needs_repair"): return ""
    return "Repair these answer-quality defects before delivery: "+", ".join(report.get("issues") or [])
