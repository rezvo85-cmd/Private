import re
import time
import hashlib
from dataclasses import dataclass

FRESHNESS = {
    'today','tonight','yesterday','latest','current','currently','now','recent','newest',
    'price','weather','news','score','standings','release','version','updated','update',
    'election','president','ceo','stock','market','rate','availability','open now'
}
VERIFY_VERBS = {
    'tested','verified','confirmed','ran','executed','opened','downloaded','installed',
    'fixed','repaired','working','works','passed','deployed','published','connected'
}
RISK_DOMAINS = {
    'medical': ('medical','medicine','doctor','symptom','diagnosis','dose','medication'),
    'legal': ('legal','lawyer','lawsuit','court','law','contract'),
    'financial': ('investment','investing','financial advice','stock','tax','loan','credit'),
    'security': ('password','credential','api key','token','private key','malware','exploit'),
}


def _sentences(text: str):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text or '') if s.strip()]


def tokens(text: str):
    return set(re.findall(r"[a-z0-9_'-]{3,}", (text or '').lower()))


def task_signature(message: str) -> str:
    normalized = re.sub(r'\s+', ' ', (message or '').strip().lower())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def current_information_risk(message: str):
    low = (message or '').lower()
    hits = sorted({w for w in FRESHNESS if w in low})
    return {'time_sensitive': bool(hits), 'signals': hits[:12]}


def domain_risk(message: str):
    low = (message or '').lower()
    domains=[]
    for name, words in RISK_DOMAINS.items():
        if any(w in low for w in words):
            domains.append(name)
    return {'domains': domains, 'high_stakes': bool(set(domains) & {'medical','legal','financial','security'})}


def ambiguity_scan(message: str):
    text=(message or '').strip()
    low=text.lower()
    unresolved=[]
    if len(text) < 18 and any(x in low.split() for x in ('it','that','this','one','same')):
        unresolved.append('short_reference')
    if any(x in low for x in ('the latest one','same as before','that file','that error','fix it')):
        unresolved.append('context_reference')
    if any(x in low for x in ('best','better','which one')) and not any(x in low for x in ('for ','because ','priority','criteria','budget','fast','accurate')):
        unresolved.append('decision_criteria_may_be_implicit')
    return {'ambiguous': bool(unresolved), 'signals': unresolved}


def build_task_plan(message: str, profile: str, difficulty: int, has_files=False, has_project=False):
    low=(message or '').lower()
    phases=[{'name':'Understand','goal':'Resolve the actual user goal and active constraints.'}]
    if difficulty >= 2 or len(message or '') > 280:
        phases.append({'name':'Plan','goal':'Break the work into dependent, checkable steps.'})
    if current_information_risk(message)['time_sensitive'] or profile == 'research':
        phases.append({'name':'Research','goal':'Collect current evidence before making time-sensitive claims.'})
    if has_files:
        phases.append({'name':'Inspect','goal':'Inspect supplied files as connected project evidence.'})
    if any(x in low for x in ('debug','fix','broken','error','crash','failed','doesn\'t work','doesnt work')):
        phases.append({'name':'Diagnose','goal':'Identify root cause and dependency chain before repair.'})
    phases.append({'name':'Solve','goal':'Produce the requested result while preserving requirements.'})
    if difficulty >= 3 or profile in ('coding','research','analysis','mathscience'):
        phases.append({'name':'Verify','goal':'Check requirements, contradictions, evidence boundaries, and likely failure modes.'})
    return {
        'signature': task_signature(message),
        'profile': profile,
        'difficulty': int(difficulty),
        'phases': phases,
        'checkpoint_count': len(phases),
        'resumable': difficulty >= 3 or has_files or has_project,
    }


def explicit_requirements(message: str):
    out=[]
    for s in _sentences(message):
        low=s.lower()
        if any(x in low for x in ('must ','need ','needs ','make sure','keep ','use ','do not ','don\'t ','without ','exactly ','only ','include ','change ','rename ')):
            out.append(s[:700])
    # If no explicit marker, preserve the request itself as the primary requirement.
    if not out and (message or '').strip():
        out=[re.sub(r'\s+',' ',message.strip())[:900]]
    return list(dict.fromkeys(out))[:32]


def requirement_coverage(message: str, answer: str):
    reqs=explicit_requirements(message)
    answer_tokens=tokens(answer)
    rows=[]
    for r in reqs:
        rt=tokens(r)
        overlap=len(rt & answer_tokens)
        ratio=overlap/max(1,min(len(rt),8))
        rows.append({'requirement':r,'lexical_signal':round(min(1.0,ratio),2),'likely_addressed':ratio>=0.35})
    covered=sum(1 for r in rows if r['likely_addressed'])
    return {'requirements':rows,'covered_signal':covered,'total':len(rows),'coverage_signal':round(covered/max(1,len(rows)),2)}


def completion_claim_scan(answer: str):
    issues=[]
    for s in _sentences(answer):
        low=s.lower()
        if any(re.search(rf'\b{re.escape(v)}\b', low) for v in VERIFY_VERBS):
            if any(x in low for x in ('i tested','i verified','i ran','i fixed','it is fixed','passed all','fully working','confirmed working','i checked')):
                issues.append(s[:600])
    return issues[:12]


def suspicious_specificity(answer: str):
    issues=[]
    for s in _sentences(answer):
        low=s.lower()
        # Specific numeric/date claims can be legitimate; flag them only for audit, never auto-reject.
        if re.search(r'\b(?:19|20)\d{2}\b|\b\d+(?:\.\d+)?%\b|\$\d', s) and not any(x in low for x in ('example','placeholder','approximately','about ','around ')):
            issues.append(s[:500])
    return issues[:10]


def contradiction_scan(texts):
    """Lightweight contradiction detector for repeated short claims with explicit negation.
    It is intentionally conservative and only supplies review signals.
    """
    positives={}
    negatives={}
    for source,text in texts:
        for s in _sentences(text):
            clean=re.sub(r'[^a-z0-9 ]',' ',s.lower())
            clean=re.sub(r'\s+',' ',clean).strip()
            if len(clean)<8 or len(clean)>220:
                continue
            neg=bool(re.search(r'\b(no|not|never|cannot|can\'t|doesn\'t|does not|isn\'t|is not|without)\b', s.lower()))
            core=re.sub(r'\b(no|not|never|cannot|cant|can t|doesnt|does not|isnt|is not|without)\b','',clean)
            core=' '.join(core.split())
            if not core:
                continue
            bucket=negatives if neg else positives
            bucket.setdefault(core,[]).append({'source':source,'text':s[:500]})
    conflicts=[]
    # Exact-core match after negation removal. Conservative by design.
    for core in set(positives) & set(negatives):
        conflicts.append({'topic':core[:180],'positive':positives[core][0],'negative':negatives[core][0]})
    return conflicts[:12]


def answer_audit(message: str, answer: str, profile: str='', runtime_verified=False, evidence_mode='model'):
    completion=completion_claim_scan(answer)
    current=current_information_risk(message)
    domain=domain_risk(message)
    coverage=requirement_coverage(message,answer)
    warnings=[]
    if completion and not runtime_verified:
        warnings.append('Answer contains completion/test language without a runtime-verification flag.')
    if current['time_sensitive'] and evidence_mode not in ('live','research','tools'):
        warnings.append('Request appears time-sensitive but answer route was not marked live/research.')
    if coverage['total'] and coverage['coverage_signal'] < .5:
        warnings.append('Low lexical requirement-coverage signal; review for dropped requirements.')
    specificity=suspicious_specificity(answer)
    risk='high' if domain['high_stakes'] or current['time_sensitive'] else ('medium' if completion or specificity else 'standard')
    return {
        'risk':risk,
        'warnings':warnings,
        'completion_claims':completion,
        'specificity_review':specificity,
        'coverage':coverage,
        'time_sensitive':current,
        'domain_risk':domain,
        'runtime_verified':bool(runtime_verified),
        'evidence_mode':evidence_mode,
        'audited_at':int(time.time()),
    }


def preflight_report(message: str, profile: str, difficulty: int, has_files=False, has_project=False):
    return {
        'plan':build_task_plan(message,profile,difficulty,has_files,has_project),
        'requirements':explicit_requirements(message),
        'freshness':current_information_risk(message),
        'risk':domain_risk(message),
        'ambiguity':ambiguity_scan(message),
    }
