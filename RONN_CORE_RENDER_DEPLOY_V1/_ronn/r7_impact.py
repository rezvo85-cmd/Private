import hashlib
import json
import re
from typing import Iterable

CURRENT_DOMAINS = {
    'news','weather','sports','scores','standings','prices','markets','stocks','crypto','streamers','creators',
    'games','software','api','models','release','version','availability','hours','events','rankings'
}

SKILL_RULES = [
    ('debugging', ('error','bug','broken','fix','traceback','crash','not working','fails','exception')),
    ('coding', ('code','script','python','javascript','typescript','luau','api','backend','frontend','repository','repo')),
    ('research', ('research','latest','current','today','source','citation','look up','web','news','top ','best ')),
    ('design', ('design','logo','ui','ux','brand','layout','visual','style','mockup')),
    ('planning', ('plan','roadmap','strategy','project','milestone','schedule','launch')),
    ('analysis', ('analyze','compare','tradeoff','evaluate','why','reason','root cause')),
]


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def skill_profile(message: str, profile: str = 'chat') -> str:
    low = _clean(message).lower()
    scores = []
    for name, terms in SKILL_RULES:
        score = sum(1 for t in terms if t in low)
        if score:
            scores.append((score, name))
    if scores:
        scores.sort(reverse=True)
        return scores[0][1]
    return profile or 'chat'


def freshness_policy(message: str) -> dict:
    low = _clean(message).lower()
    current_terms = ('today','right now','currently','current ','latest','recent','this week','this month','2026','now')
    ranking_terms = ('top ','best ','most popular','biggest','most watched','most followed','ranking','ranked')
    changing_entities = ('streamer','creator','game','player','team','company','brand','app','model','software','price','stock','weather','news')
    explicit_current = any(t in low for t in current_terms)
    moving_ranking = any(t in low for t in ranking_terms) and any(e in low for e in changing_entities)
    current_fact = any(t in low for t in ('price','weather','news','score','standings','release date','version','availability','open now','outage','stock','market'))
    needs_live = bool(explicit_current or moving_ranking or current_fact)
    return {
        'live_required': needs_live,
        'moving_ranking': moving_ranking,
        'freshness_required': needs_live,
        'time_context_required': bool(moving_ranking or explicit_current),
        'source_refresh_rule': 'Prefer recent primary/official evidence and reject stale ranking snapshots.' if needs_live else 'Use stable knowledge unless the topic is time-sensitive.'
    }


def risk_policy(message: str, has_files: bool = False, has_images: bool = False) -> dict:
    low = _clean(message).lower()
    edit = any(x in low for x in ('change','edit','modify','rewrite','replace','delete','remove','upgrade','update','fix','repair'))
    destructive = any(x in low for x in ('delete','remove','overwrite','replace all','wipe','reset','format'))
    code = has_files or any(x in low for x in ('code','script','project','repo','server','frontend','backend','api'))
    release = any(x in low for x in ('publish','deploy','release','production','ship','live'))
    score = (2 if destructive else 0) + (1 if edit else 0) + (1 if code else 0) + (1 if release else 0)
    return {
        'score': min(score, 5),
        'level': 'high' if score >= 4 else ('medium' if score >= 2 else 'low'),
        'snapshot_recommended': bool(edit and code),
        'rollback_plan_required': bool(score >= 3),
        'proactive_warnings': [
            x for x, cond in (
                ('Create a checkpoint before broad edits.', edit and code),
                ('Prefer reversible changes until verification passes.', score >= 2),
                ('Do not publish/deploy until validation passes.', release),
                ('Destructive wording detected; verify target scope before acting.', destructive),
            ) if cond
        ]
    }


def attachment_graph(files: Iterable, image_count: int = 0) -> dict:
    nodes = []
    names = []
    for f in list(files or [])[:32]:
        name = getattr(f, 'name', '') or 'file'
        content = getattr(f, 'content', '') or ''
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        lang = {
            'py':'python','js':'javascript','ts':'typescript','tsx':'typescript','jsx':'javascript','lua':'lua','luau':'luau',
            'html':'html','css':'css','json':'json','md':'markdown','txt':'text','csv':'csv','yaml':'yaml','yml':'yaml'
        }.get(ext, ext or 'text')
        node = {
            'name': name[:180],
            'kind': 'file',
            'language': lang,
            'chars': len(content),
            'fingerprint': hashlib.sha256(content.encode('utf-8', errors='ignore')).hexdigest()[:12],
        }
        nodes.append(node); names.append(name.lower())
    links = []
    for i, a in enumerate(nodes):
        stem_a = re.sub(r'[^a-z0-9]+',' ', a['name'].lower()).split()
        for b in nodes[i+1:]:
            stem_b = re.sub(r'[^a-z0-9]+',' ', b['name'].lower()).split()
            overlap = set(stem_a) & set(stem_b)
            if overlap:
                links.append({'from':a['name'],'to':b['name'],'reason':'shared filename terms','terms':sorted(overlap)[:5]})
    return {
        'nodes': nodes,
        'links': links[:60],
        'image_count': int(image_count or 0),
        'multi_modal': bool(image_count and nodes),
        'instruction': 'Treat screenshots/images and attached text/code as evidence about the same task when context links them; do not analyze each in isolation.' if image_count and nodes else ''
    }


def agent_plan(message: str, profile: str, difficulty: int, has_files: bool = False, has_images: bool = False) -> dict:
    low = _clean(message).lower()
    skill = skill_profile(message, profile)
    freshness = freshness_policy(message)
    risk = risk_policy(message, has_files, has_images)
    phases = ['Understand']
    if has_files or has_images:
        phases += ['Inspect evidence']
    if freshness['live_required']:
        phases += ['Research current evidence']
    if skill == 'debugging':
        phases += ['Reproduce or isolate failure','Rank root causes','Apply smallest safe repair']
    elif skill == 'coding':
        phases += ['Map project','Plan change','Implement minimal coherent change']
    elif skill == 'research':
        phases += ['Gather sources','Compare evidence','Synthesize']
    else:
        phases += ['Solve']
    if difficulty >= 3 or risk['level'] != 'low':
        phases += ['Verify']
    phases += ['Deliver']
    return {
        'skill': skill,
        'difficulty': int(difficulty),
        'phases': list(dict.fromkeys(phases)),
        'auto_continue_safe_steps': True,
        'pause_before_irreversible': True,
        'resume_supported': True,
        'risk': risk,
        'freshness': freshness,
    }


def verification_policy(message: str, difficulty: int, profile: str, current: bool = False) -> dict:
    low = _clean(message).lower()
    factual = bool(re.match(r'^(who|what|when|where|why|how|which|is|are|was|were|does|did|can)\b', low))
    code = profile in {'coding','debugging'} or any(x in low for x in ('code','bug','fix','script','api','server'))
    hard = int(difficulty) >= 4
    return {
        'second_model_recommended': bool(hard or (factual and current) or (code and int(difficulty) >= 3)),
        'before_after_check': bool(code and any(x in low for x in ('fix','change','edit','upgrade','repair'))),
        'runtime_proof_required_for_fixed_claim': bool(code),
        'source_check_required': bool(current or factual),
        'confidence_floor_for_strong_claim': 0.80,
    }


def explanation_trace(message: str, plan: dict, route: str = '', model: str = '') -> dict:
    return {
        'summary': f"RONN interpreted this as {plan.get('skill','general')} work and selected a {'live/current' if plan.get('freshness',{}).get('live_required') else 'standard'} evidence path.",
        'route': route,
        'model': model,
        'phases': plan.get('phases', []),
        'note': 'This is a high-level decision summary, not hidden chain-of-thought.'
    }


def context_cleanup_policy(history_count: int, has_project: bool, has_files: bool) -> dict:
    history_count = int(history_count or 0)
    return {
        'compress_old_context': history_count > 24,
        'preserve_recent_turns': 14 if history_count > 24 else 20,
        'preserve_project_constraints': bool(has_project),
        'preserve_active_file_names': bool(has_files),
        'drop_unrelated_old_chat': history_count > 30,
    }


def quality_dimensions(message: str, plan: dict) -> list[str]:
    dims = ['relevance','clarity','requirement_coverage','unsupported_claims']
    if plan.get('freshness',{}).get('live_required'): dims += ['source_freshness','time_context']
    if plan.get('skill') in {'coding','debugging'}: dims += ['integration_consistency','verification_boundary','regression_risk']
    return dims



def response_quality_score(message: str, answer: str, report: dict | None = None) -> dict:
    answer=_clean(answer); message=_clean(message); report=report or {}
    warnings=[]; score=100
    if not answer:
        return {'score':0,'warnings':['empty answer'],'dimensions':{}}
    if len(answer)>12000 and len(message)<180:
        warnings.append('Answer may be much longer than the request requires.'); score-=10
    if re.search(r"\b(i|we) (tested|verified|ran|executed|fixed)\b",answer,re.I) and not re.search(r"\b(static|runtime|provider|test|check|verified)\b",answer,re.I):
        warnings.append('Strong completion language needs an explicit evidence boundary.'); score-=18
    current=(report.get('agent_plan') or {}).get('freshness',{}).get('live_required',False)
    if current and not re.search(r"\b(as of|current|today|202[5-9]|source|according|recent)\b",answer,re.I):
        warnings.append('Time-sensitive answer may be missing freshness context.'); score-=12
    dims={
        'directness': max(0,100-(10 if len(answer)>6000 and len(message)<200 else 0)),
        'completion_claim_discipline': 100-(18 if any('completion language' in w for w in warnings) else 0),
        'freshness_context': 100-(12 if any('freshness' in w for w in warnings) else 0),
        'nonempty':100,
    }
    return {'score':max(0,score),'warnings':warnings,'dimensions':dims}

def capability_manifest() -> dict:
    return {
        'live_research': {'state':'available_when_groq_compound_configured','scope':'current information and web-enabled synthesis'},
        'multi_step_agent': {'state':'available','scope':'planning, checkpoints, attached files, local deterministic tools, provider calls'},
        'second_model_verification': {'state':'available','scope':'hard non-live tasks and explicit verification'},
        'project_memory': {'state':'available','scope':'project facts, failures, decisions, user-approved memory'},
        'screen_understanding': {'state':'available_via_uploaded_images','scope':'screenshots/images attached to chat'},
        'coding_agent': {'state':'available_for_attached_project_files','scope':'index, analyze, propose/edit generated artifacts, verify statically'},
        'self_repair': {'state':'diagnostic_only','scope':'detect provider/build/config issues and recommend safe recovery'},
        'local_cloud_routing': {'state':'available','scope':'local deterministic tools plus configured cloud models'},
        'model_comparison': {'state':'available_in_apex','scope':'parallel candidates + adversarial synthesis'},
        'task_queue': {'state':'available','scope':'persistent local queue and status tracking'},
        'project_snapshots': {'state':'available_for_attached_text_files','scope':'snapshot, diff, restore-to-artifact'},
        'knowledge_base': {'state':'available','scope':'local searchable project/research/file knowledge'},
        'voice_input': {'state':'browser_dependent','scope':'Web Speech API when supported by the browser'},
        'desktop_control': {'state':'not_enabled','scope':'RONN does not silently control the operating system; a separate permissioned bridge would be required'},
    }


def r7_preflight(message: str, profile: str, difficulty: int, history_count: int = 0, files=None, image_count: int = 0, project_context: str = '') -> dict:
    plan = agent_plan(message, profile, difficulty, bool(files), bool(image_count))
    return {
        'fingerprint': hashlib.sha256(_clean(message).lower().encode()).hexdigest()[:16],
        'agent_plan': plan,
        'verification': verification_policy(message, difficulty, plan.get('skill', profile), plan.get('freshness',{}).get('live_required',False)),
        'attachments': attachment_graph(files or [], image_count),
        'context_cleanup': context_cleanup_policy(history_count, bool(project_context), bool(files)),
        'quality_dimensions': quality_dimensions(message, plan),
        'capabilities': capability_manifest(),
    }


def r7_directive(report: dict) -> str:
    return "RONN R7 IMPACT POLICY:\n" + json.dumps(report, ensure_ascii=False)[:18000] + """
Operational rules:
- Work toward the user's outcome, not merely a plausible-sounding answer.
- For changing facts/rankings, use live evidence when available and include time context when it matters.
- For difficult work, plan in phases, continue through safe reversible steps, and verify before strong completion claims.
- For debugging, isolate/reproduce when possible, rank root causes, repair the smallest coherent surface, then check for regressions.
- Treat uploaded screenshots, code, logs, and documents as one connected evidence set when they relate to the same task.
- Use second-model or adversarial verification when the task is hard enough to justify it; do not waste extra model calls on trivial questions.
- Preserve project decisions and known failures. Do not reintroduce a previously rejected fix without new evidence.
- If a change is risky, create or recommend a checkpoint and keep rollback possible.
- Give only a high-level explanation of why a route was chosen; never expose hidden chain-of-thought.
- Be proactive about stale sources, missing runtime proof, destructive changes, and provider failure, but keep warnings concise.
- "Do it for me" means execute what RONN's actual local/provider tools can safely perform; never pretend to control the desktop or external apps without a permissioned bridge.
"""
