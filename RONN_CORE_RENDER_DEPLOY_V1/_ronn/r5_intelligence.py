import re
import json
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

FRESH_TERMS = {
    'today','tonight','now','current','currently','latest','recent','newest','this week','this month',
    'price','weather','news','score','standings','release','version','availability','open now','outage','market'
}
DEBUG_TERMS = ('error','bug','broken','crash','fails','failed','not working','doesn\'t work','doesnt work','fix','debug','traceback','exception')
ACTION_TERMS = ('build','make','create','change','edit','fix','repair','implement','add','remove','generate','export','package')
RESEARCH_TERMS = ('research','find out','look up','latest','current','sources','compare evidence','verify fact')
DESIGN_TERMS = ('design','ui','ux','logo','theme','style','layout','visual','appealing','bubbly','glow')
STRICT_TERMS = ('must','need','make sure','do not','don\'t','dont','exactly','only','keep','preserve','without','never')


def _clean(text):
    return re.sub(r'\s+',' ',str(text or '')).strip()


def _tokens(text):
    return [x for x in re.findall(r"[a-z0-9_./'-]{2,}", (text or '').lower()) if x]


def classify_intent(message: str):
    low=_clean(message).lower()
    scores={'answer':1,'action':0,'debug':0,'research':0,'design':0,'decision':0}
    scores['action'] += sum(1 for x in ACTION_TERMS if x in low)
    scores['debug'] += sum(2 for x in DEBUG_TERMS if x in low)
    scores['research'] += sum(1 for x in RESEARCH_TERMS if x in low)
    scores['design'] += sum(1 for x in DESIGN_TERMS if x in low)
    scores['decision'] += sum(1 for x in ('which','best','better','compare','choose','recommend') if x in low)
    if '?' in message: scores['answer'] += 1
    intent=max(scores,key=scores.get)
    return {'primary':intent,'scores':scores}


def constraint_graph(message: str):
    text=_clean(message)
    parts=[p.strip(' -•\t') for p in re.split(r'(?<=[.!?])\s+|\n+|\s+and\s+(?=(?:make|add|include|keep|use|do|don\'t|dont|fix|change)\b)',text,flags=re.I) if p.strip()]
    hard=[]; negative=[]; deliverables=[]; preferences=[]
    for p in parts:
        low=p.lower()
        if any(x in low for x in ('do not','don\'t','dont','never','without')): negative.append(p[:700])
        if any(x in low for x in STRICT_TERMS): hard.append(p[:700])
        if any(x in low for x in ACTION_TERMS): deliverables.append(p[:700])
        if any(x in low for x in ('prefer','like','want','appealing','style','look','feel')): preferences.append(p[:700])
    if not deliverables and text: deliverables=[text[:900]]
    return {
        'hard_constraints':list(dict.fromkeys(hard))[:40],
        'negative_constraints':list(dict.fromkeys(negative))[:24],
        'deliverables':list(dict.fromkeys(deliverables))[:40],
        'preferences':list(dict.fromkeys(preferences))[:30],
    }


def complexity_factors(message: str, profile: str='', has_files=False, has_project=False):
    text=_clean(message); low=text.lower(); score=0; reasons=[]
    n=len(text)
    if n>300: score+=1; reasons.append('long_request')
    if n>1000: score+=1; reasons.append('very_long_request')
    if has_files: score+=1; reasons.append('attached_files')
    if has_project: score+=1; reasons.append('active_project')
    if sum(1 for x in STRICT_TERMS if x in low)>=3: score+=1; reasons.append('many_constraints')
    if any(x in low for x in DEBUG_TERMS): score+=1; reasons.append('debugging')
    if any(x in low for x in ('whole project','entire project','full system','architecture','production','multi-file','1000','hundred')): score+=2; reasons.append('large_scope')
    if profile in ('coding','research','analysis','mathscience'): score+=1; reasons.append('specialist_domain')
    if any(x in low for x in FRESH_TERMS): score+=1; reasons.append('freshness_required')
    return {'score':min(7,score),'reasons':reasons}


def reasoning_policy(message: str, profile: str, difficulty: int, has_files=False, has_project=False):
    cf=complexity_factors(message,profile,has_files,has_project)
    effective=max(int(difficulty or 0),cf['score'])
    if effective>=6: tier='apex'
    elif effective>=4: tier='deep'
    elif effective>=2: tier='balanced'
    else: tier='fast'
    if any(x in _clean(message).lower() for x in FRESH_TERMS): tier='tools'
    return {
        'tier':tier,
        'effective_difficulty':effective,
        'parallel_candidates':effective>=5,
        'adversarial_review':effective>=4,
        'verification_required':effective>=3,
        'runtime_evidence_required': any(x in _clean(message).lower() for x in ('works','working','fixed','tested','passed','runs','launches')),
        'context_budget_chars':42000 if has_files or has_project or effective>=4 else 22000,
        'complexity_factors':cf,
    }


def freshness_policy(message: str):
    low=_clean(message).lower(); hits=[x for x in FRESH_TERMS if x in low]
    return {
        'live_required':bool(hits),
        'signals':sorted(hits)[:16],
        'source_preference':['official/primary','maintainer documentation','recent reputable secondary','community reports as anecdotal evidence'] if hits else [],
    }


def reference_resolution(message: str, history):
    low=_clean(message).lower()
    signals=[]
    for phrase in ('it','that','this','same as before','the latest one','that file','that error','the file you sent','the old version','the new one'):
        if phrase in low: signals.append(phrase)
    context=[]
    if signals:
        for row in list(history or [])[-8:]:
            role=row.get('role','') if isinstance(row,dict) else ''
            content=row.get('content','') if isinstance(row,dict) else ''
            if content: context.append({'role':role,'content':_clean(content)[:700]})
    return {'has_context_reference':bool(signals),'signals':signals,'recent_context':context[-6:]}


def debug_hypotheses(message: str, files=None):
    low=_clean(message).lower(); out=[]
    def add(name,why,priority):
        if not any(x['name']==name for x in out): out.append({'name':name,'why':why,'priority':priority})
    if 'not a function' in low: add('symbol_type_or_name_collision','A value is being called like a function; inspect declarations, DOM globals, imports, and stale bundles.',1)
    if 'port' in low or 'address already in use' in low: add('port_or_stale_process','Another process may own the expected port or an old build may still be serving.',1)
    if '404' in low: add('route_or_asset_path','Check route registration, base URL, relative asset paths, and build output.',1)
    if '401' in low or '403' in low: add('authentication_or_permission','Check key loading, authorization headers, scope, account permissions, and endpoint.',1)
    if '429' in low: add('rate_limit_or_quota','Check provider quota, token budget, retry policy, and model-specific limits.',1)
    if 'cannot scroll' in low or "can't scroll" in low: add('nested_overflow_or_flex_min_height','Check overflow ownership, min-height:0 on grid/flex children, and fixed/absolute overlays.',1)
    if 'invisible' in low or 'cannot see' in low or "can't see" in low: add('contrast_or_clipping','Check text contrast, opacity, z-index, clipping, and viewport overlap.',2)
    if files:
        names=' '.join(getattr(f,'name','') for f in files).lower()
        if any(x in names for x in ('package.json','requirements','pyproject')): add('dependency_or_version_mismatch','Inspect declared dependencies and installed/runtime versions.',2)
        if any(x in names for x in ('html','css','js','tsx','jsx')): add('frontend_cache_or_bundle_mismatch','Check cache-busting/build ID and source-vs-served asset mismatch.',2)
    if not out and any(x in low for x in DEBUG_TERMS): add('root_cause_unknown','Start with reproducible symptom, first error, environment/config, dependency chain, then minimal repair.',3)
    return sorted(out,key=lambda x:x['priority'])[:8]


def response_contract(message: str, intent: dict, policy: dict):
    primary=intent.get('primary','answer')
    contract={
        'lead_with_direct_result':True,
        'avoid_repeating_request':True,
        'state_verification_boundary':policy.get('verification_required',False),
        'separate_required_from_optional':primary in ('action','debug','design'),
        'use_steps_when_procedural':primary in ('action','debug'),
        'include_sources_when_live':policy.get('tier')=='tools',
        'do_not_claim_completion_without_evidence':True,
    }
    return contract


def preflight_v5(message: str, profile: str, difficulty: int, history=None, has_files=False, has_project=False, files=None):
    intent=classify_intent(message)
    policy=reasoning_policy(message,profile,difficulty,has_files,has_project)
    return {
        'fingerprint':hashlib.sha256(_clean(message).lower().encode()).hexdigest()[:16],
        'intent':intent,
        'constraints':constraint_graph(message),
        'reasoning_policy':policy,
        'freshness':freshness_policy(message),
        'references':reference_resolution(message,history or []),
        'debug_hypotheses':debug_hypotheses(message,files),
        'response_contract':response_contract(message,intent,policy),
    }


def intelligence_directive_v5(report: dict) -> str:
    return "RONN R5 ADAPTIVE INTELLIGENCE POLICY:\n" + json.dumps(report,ensure_ascii=False)[:14000] + """
Execution rules:
- Treat the constraint graph as a checklist; never silently drop hard or negative constraints.
- Resolve context references from recent conversation/project evidence before asking the user to repeat information.
- For debugging, rank hypotheses and test/inspect the highest-evidence causes before rewriting unrelated systems.
- Separate edited, statically checked, runtime tested, provider-reachable, and fully verified states.
- Never convert a heuristic signal into a factual claim. Heuristics guide inspection; evidence decides conclusions.
- Prefer reversible, minimal changes first when the root cause is uncertain.
- If the request depends on current information, use a live/tool route rather than stale memory.
- Before finalizing, check outcome coverage, contradictions, unsupported certainty, and whether the response actually addresses the user's goal.
- Never expose private chain-of-thought. Give concise rationale, evidence boundaries, checks performed, and unresolved uncertainty instead.
"""


def route_override(report: dict, requested_mode: str='auto'):
    if requested_mode and requested_mode!='auto': return requested_mode
    return report.get('reasoning_policy',{}).get('tier','balanced')
