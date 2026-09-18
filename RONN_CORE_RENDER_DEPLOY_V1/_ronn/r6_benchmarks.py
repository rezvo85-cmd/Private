import time
from brevity_engine import response_length_policy, requested_list_count, brevity_audit
from r6_intelligence import ranking_policy, evidence_policy, intent_resolution, recovery_policy, r6_preflight


def run_r6_benchmarks():
    tests=[]
    def t(name,fn):
        st=time.time()
        try: tests.append({'name':name,'passed':bool(fn()),'ms':round((time.time()-st)*1000,2)})
        except Exception as e: tests.append({'name':name,'passed':False,'error':str(e)[:250],'ms':round((time.time()-st)*1000,2)})
    t('simple_question_quick',lambda: response_length_policy('Who is Jotaro?')['tier']=='quick')
    t('detail_request_deep',lambda: response_length_policy('Give me a detailed deep dive explaining the whole architecture',difficulty=4)['tier']=='deep')
    t('list_count_10',lambda: requested_list_count('give me the best 10 streamers')==10)
    t('ranking_streamers_live',lambda: ranking_policy('who are the best 10 streamers')['live_required'])
    t('ranking_subjective',lambda: ranking_policy('best streamers')['subjective_criteria'])
    t('current_evidence',lambda: evidence_policy('top 10 streamers','research')['live_required'])
    t('debug_intent',lambda: intent_resolution('fix this error')['kind']=='debug')
    t('action_intent',lambda: intent_resolution('build me a new dashboard')['kind']=='action')
    t('empty_recovery',lambda: 'fallback_model' in recovery_policy('provider gave empty response'))
    t('rate_recovery',lambda: 'backoff' in recovery_policy('429 rate limit'))
    t('scroll_recovery',lambda: 'inspect_overflow_owner' in recovery_policy('cannot scroll'))
    t('r6_preflight_brevity',lambda: r6_preflight('What is RAM?','knowledge',0)['brevity']['tier']=='quick')
    t('r6_preflight_ranking',lambda: r6_preflight('top 10 streamers','research',0)['ranking']['live_required'])
    t('brevity_long_sentence_audit',lambda: bool(brevity_audit('What is RAM?',' '.join(['word']*180)+'.',response_length_policy('What is RAM?'))['warnings']))
    passed=sum(1 for x in tests if x['passed'])
    return {'passed':passed,'total':len(tests),'score':round(100*passed/max(1,len(tests)),1),'tests':tests,
            'scope':'RONN R6 deterministic brevity/routing/reliability checks; not a benchmark of external model intelligence.'}
