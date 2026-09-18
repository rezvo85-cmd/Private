import time, uuid, re, json, ast
from project_brain import record_attempt

def new_task_id(): return uuid.uuid4().hex[:12]

def requirement_ledger(message):
    text=(message or "").strip()
    req=[]
    # Preserve explicit clauses and list-like requirements without inventing them.
    parts=re.split(r'(?:\n+|[.;]\s+|\band\b(?=\s+(?:make|add|include|keep|use|do|don\'t|dont|no)\b))',text,flags=re.I)
    for p in parts:
        p=p.strip(" -•\t")
        if len(p)>=8 and p not in req: req.append(p[:500])
    return req[:30] or ([text[:500]] if text else [])

def verification_plan(message, profile, has_studio=False):
    low=(message or "").lower()
    checks=["requirements","internal_consistency"]
    if profile in ("coding","roblox"): checks += ["syntax_interfaces","dependency_consistency","edge_cases"]
    if profile=="roblox": checks += ["client_server_boundary","remote_contracts"]
    if has_studio: checks += ["studio_job_confirmation","post_apply_snapshot"]
    if any(x in low for x in ("latest","current","today")): checks += ["fresh_source_required"]
    return list(dict.fromkeys(checks))

def verification_directive(ledger, checks):
    return """VERIFICATION ENGINE:
Requirements to preserve:
%s
Required final checks: %s
Before finishing, privately audit the proposed result against every requirement. Repair detected omissions or contradictions.
Never claim runtime testing, play-testing, Studio application, web research, or file execution unless a real result confirms it.
When runtime observation is unavailable, say 'static verification only' rather than pretending a play test happened.
""" % ("\n".join("- "+x for x in ledger), ", ".join(checks))

def _balanced_pairs(code, pairs):
    stack=[]; opening=set(pairs); closing={v:k for k,v in pairs.items()}
    quote=None; escape=False
    for ch in code:
        if quote:
            if escape: escape=False; continue
            if ch=="\\": escape=True; continue
            if ch==quote: quote=None
            continue
        if ch in ("'",'"','`'): quote=ch; continue
        if ch in opening: stack.append(ch)
        elif ch in closing:
            if not stack or stack[-1] != closing[ch]: return False
            stack.pop()
    return not stack

def static_code_checks(text):
    issues=[]
    if not text: return {"passed":True,"issues":[],"blocks":0,"scope":"response_static_checks"}
    fences=text.count("```")
    if fences%2: issues.append("Unclosed code fence")
    blocks=list(re.finditer(r"```([A-Za-z0-9_+#.-]*)\n?([\s\S]*?)```",text))
    checked=0
    for m in blocks[:24]:
        lang=(m.group(1) or "").strip().lower(); code=m.group(2)
        if not code.strip(): continue
        if lang in ("python","py"):
            checked+=1
            try: ast.parse(code)
            except SyntaxError as e: issues.append(f"Python syntax: line {e.lineno}: {e.msg}")
        elif lang in ("json",):
            checked+=1
            try: json.loads(code)
            except Exception as e: issues.append(f"JSON syntax: {str(e)[:160]}")
        elif lang in ("javascript","js","typescript","ts","tsx","jsx","lua","luau","css"):
            checked+=1
            if not _balanced_pairs(code,{"(":")","[":"]","{":"}"}):
                issues.append(f"{lang or 'code'} structural check: unbalanced (), [], or {{}}")
    if "RemoteEvent" in text and "OnServerEvent" in text and "FireServer" not in text:
        issues.append("Server RemoteEvent listener shown without an obvious client FireServer call; verify architecture.")
    if re.search(r"(?i)\b(?:TODO|FIXME|PASTE_YOUR_|YOUR_API_KEY|REPLACE_ME)\b", text):
        issues.append("Response contains placeholder/TODO markers; verify they are intentional before calling the result complete.")
    return {"passed":not issues,"issues":issues[:30],"blocks":checked,"scope":"response_static_checks"}

def task_status(pid, task_id, stages):
    for s in stages:
        record_attempt(pid,task_id,s,"planned","")
    return {"task_id":task_id,"stages":stages}
