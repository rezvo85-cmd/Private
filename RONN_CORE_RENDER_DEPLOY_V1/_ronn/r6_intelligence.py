import re, json, hashlib
from brevity_engine import response_length_policy

# R6 turns the 1001-1500 roadmap into grouped operational policies. The individual ideas
# overlap heavily, so these systems enforce them without pretending there are 500 independent switches.
MOVING_RANKING_ENTITIES=(
    'streamer','streamers','youtuber','youtubers','creator','creators','influencer','influencers',
    'artist','artists','player','players','podcast','podcasts','channel','channels','game','games','app','apps',
    'movie','movies','show','shows','song','songs','team','teams','company','companies','brand','brands'
)
RANK_TERMS=('top ','best ','most popular','biggest','most watched','most followed','ranking','ranked','greatest')
CURRENT_TERMS=('today','now','current','currently','latest','recent','this week','this month','2026','right now')


def _clean(x): return re.sub(r'\s+',' ',str(x or '')).strip()


def ranking_policy(message: str):
    low=_clean(message).lower()
    moving=any(x in low for x in MOVING_RANKING_ENTITIES)
    ranked=any(x in low for x in RANK_TERMS)
    current=any(x in low for x in CURRENT_TERMS)
    subjective=any(x in low for x in ('best','greatest','favorite','most entertaining','most talented'))
    return {
        'is_ranking':bool(ranked),'moving_subject':bool(moving),
        'live_required':bool(ranked and moving),
        'subjective_criteria':bool(subjective),
        'criteria_rule':'State or infer a sensible criterion; do not present subjective ordering as objective fact.' if ranked else '',
        'time_context_required':bool((ranked and moving) or current),
    }


def evidence_policy(message: str, profile: str):
    low=_clean(message).lower(); ranking=ranking_policy(message)
    current=ranking['live_required'] or any(x in low for x in (
        'price','weather','news','score','standings','release date','version','availability','open now','outage','market','stock'
    ))
    code=profile=='coding' or any(x in low for x in ('code','script','api','debug','function','class','server','frontend','backend'))
    return {
        'live_required':current,
        'runtime_evidence_preferred':code and any(x in low for x in ('fix','working','works','tested','run','launch','error','bug')),
        'source_priority':['official/primary','maintainer/repository','recent reputable secondary','community evidence'] if current else [],
        'never_invent_sources':True,'never_invent_test_results':True,
    }


def intent_resolution(message: str):
    text=_clean(message); low=text.lower(); result={'kind':'answer','confidence':0.7,'signals':[]}
    groups={
        'debug':('error','bug','broken','not working','doesnt work','doesn\'t work','crash','traceback','fix it'),
        'action':('build','make','create','implement','add','change','edit','repair','package'),
        'research':('research','look up','find sources','latest','current','today','news'),
        'comparison':('compare','versus',' vs ','which is better','best','top '),
        'explain':('explain','why','how does','what is','what are'),
    }
    scores={k:sum(1 for s in sigs if s in low) for k,sigs in groups.items()}
    if max(scores.values() or [0])>0:
        result['kind']=max(scores,key=scores.get); result['confidence']=min(.98,.65+.08*max(scores.values()))
        result['signals']=[s for s in groups[result['kind']] if s in low][:8]
    return result


def recovery_policy(message: str):
    low=_clean(message).lower(); actions=[]
    if 'empty response' in low or 'no response' in low: actions += ['retry_nonstream','fallback_model','provider_health_check']
    if '429' in low or 'rate limit' in low: actions += ['backoff','reduce_output_budget','fallback_model']
    if 'model not found' in low: actions += ['refresh_model_catalog','fallback_model']
    if 'port' in low or 'address already in use' in low: actions += ['check_process_owner','choose_free_port','verify_build_fingerprint']
    if 'scroll' in low: actions += ['inspect_overflow_owner','inspect_flex_min_height','inspect_fixed_overlays']
    return list(dict.fromkeys(actions))


def r6_preflight(message: str, profile: str, difficulty: int, style='balanced', has_files=False, has_images=False, has_project=False):
    ranking=ranking_policy(message); evidence=evidence_policy(message,profile)
    brevity=response_length_policy(message,style,difficulty,has_files,has_images,has_project)
    return {
        'fingerprint':hashlib.sha256(_clean(message).lower().encode()).hexdigest()[:16],
        'intent':intent_resolution(message),
        'ranking':ranking,
        'evidence':evidence,
        'brevity':brevity,
        'recovery':recovery_policy(message),
        'answer_rules':{
            'direct_answer_first':True,'no_request_repetition':True,'no_filler_preamble':True,
            'short_sentences_when_simple':True,'separate_fact_from_opinion':True,
            'do_not_overclaim':True,'do_not_repeat_failed_fix':True,
            'current_rankings_need_live_evidence':ranking['live_required'],
        },
    }


def r6_directive(report: dict) -> str:
    return "RONN R6 INTELLIGENCE POLICY:\n" + json.dumps(report,ensure_ascii=False)[:12000] + """
Operational rules:
- Resolve the user's actual intent before answering; use recent context for short references such as 'that', 'it', and 'the latest one'.
- For changing rankings (streamers, creators, games, players, etc.), use live/research evidence. State the ranking criterion and time context when it matters.
- Treat 'best' as criteria-dependent when appropriate; do not silently convert taste into objective fact.
- For debugging, form several plausible root-cause hypotheses, test the highest-evidence one first, and do not repeat approaches already shown to fail.
- Separate static inspection, execution, provider reachability, and runtime verification.
- Prefer primary/official evidence for current facts and exact technical behavior.
- When provider output is empty, malformed, rate-limited, or unavailable, recover automatically through retry/fallback logic before surfacing failure.
- Keep simple answers short. Complexity should buy depth, not verbosity.
- Before finalizing, check intent coverage, factual support, contradictions, response length, and unsupported completion claims.
"""
