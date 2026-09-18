import time
from r5_intelligence import classify_intent,constraint_graph,complexity_factors,reasoning_policy,freshness_policy,reference_resolution,debug_hypotheses,preflight_v5
from project_indexer import index_files
from quality_gate import quality_report

class F:
    def __init__(self,name,content): self.name=name; self.content=content

def run_r5_benchmarks():
    tests=[]
    def t(name,fn):
        start=time.time()
        try: ok=bool(fn()); tests.append({'name':name,'passed':ok,'ms':round((time.time()-start)*1000,2)})
        except Exception as e: tests.append({'name':name,'passed':False,'error':str(e)[:300],'ms':round((time.time()-start)*1000,2)})
    t('intent_debug',lambda: classify_intent('fix this crash error')['primary']=='debug')
    t('intent_design',lambda: classify_intent('red bubbly UI design')['primary']=='design')
    t('constraints_negative',lambda: len(constraint_graph("Keep RONN red. Don't rename it.")['negative_constraints'])==1)
    t('complexity_large_scope',lambda: complexity_factors('upgrade the entire project with 1000 improvements','coding')['score']>=2)
    t('policy_deep',lambda: reasoning_policy('debug the full system','coding',4)['adversarial_review'])
    t('freshness_live',lambda: freshness_policy('what is the latest version today')['live_required'])
    t('reference_resolution',lambda: reference_resolution('fix that error',[{'role':'user','content':'Error 500'}])['has_context_reference'])
    t('debug_not_function',lambda: debug_hypotheses('TypeError: projectContext is not a function')[0]['name']=='symbol_type_or_name_collision')
    t('debug_scroll',lambda: any(x['name']=='nested_overflow_or_flex_min_height' for x in debug_hypotheses('I cannot scroll down')))
    t('project_index_python',lambda: index_files([F('a.py','import os\ndef hello():\n return os.getenv("PORT")')])['languages'].get('python')==1)
    t('project_index_duplicate',lambda: 'x' in index_files([F('a.py','def x(): pass'),F('b.py','def x(): pass')])['duplicate_symbols'])
    t('quality_completion_boundary',lambda: bool(quality_report('fix it','I tested and completely fixed it.',runtime_verified=False)['warnings']))
    t('quality_current_boundary',lambda: quality_report('latest weather','It is sunny.',evidence_mode='model')['quality_score']<100)
    t('preflight_has_contract',lambda: 'response_contract' in preflight_v5('fix this bug','coding',3,history=[]))
    passed=sum(x['passed'] for x in tests)
    return {'passed':passed,'total':len(tests),'score':round(100*passed/max(1,len(tests)),1),'tests':tests,
            'scope':'RONN R5 deterministic intelligence/regression checks. These do not claim external model intelligence or live-provider quality.'}
