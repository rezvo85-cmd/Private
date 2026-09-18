import time
from r7_impact import freshness_policy,risk_policy,attachment_graph,agent_plan,verification_policy,context_cleanup_policy,capability_manifest,r7_preflight,skill_profile


def run_r7_benchmarks():
    tests=[]
    def t(name,fn):
        st=time.time()
        try:tests.append({'name':name,'passed':bool(fn()),'ms':round((time.time()-st)*1000,2)})
        except Exception as e:tests.append({'name':name,'passed':False,'error':str(e)[:240],'ms':round((time.time()-st)*1000,2)})
    t('current_streamer_ranking',lambda:freshness_policy('top 10 streamers right now')['live_required'])
    t('stable_fact_not_forced_live',lambda:not freshness_policy('what is RAM')['live_required'])
    t('debug_skill',lambda:skill_profile('fix this traceback please','chat')=='debugging')
    t('code_risk_snapshot',lambda:risk_policy('fix this code project',True)['snapshot_recommended'])
    t('destructive_high_risk',lambda:risk_policy('delete and replace all project files',True)['level']=='high')
    t('agent_debug_phases',lambda:'Rank root causes' in agent_plan('fix this crash','coding',4,True)['phases'])
    t('agent_current_research_phase',lambda:'Research current evidence' in agent_plan('best streamers right now','research',2)['phases'])
    t('second_model_hard',lambda:verification_policy('analyze this architecture deeply',6,'analysis')['second_model_recommended'])
    t('runtime_proof_code',lambda:verification_policy('fix this code',3,'coding')['runtime_proof_required_for_fixed_claim'])
    t('context_cleanup_long',lambda:context_cleanup_policy(40,True,True)['compress_old_context'])
    t('desktop_control_not_fake',lambda:capability_manifest()['desktop_control']['state']=='not_enabled')
    t('voice_browser_dependent',lambda:capability_manifest()['voice_input']['state']=='browser_dependent')
    t('attachments_multimodal',lambda:attachment_graph([],2)['image_count']==2)
    t('preflight_has_quality',lambda:len(r7_preflight('fix this bug','coding',4,12,[],0,'proj')['quality_dimensions'])>=4)
    passed=sum(1 for x in tests if x['passed'])
    return {'passed':passed,'total':len(tests),'score':round(100*passed/max(1,len(tests)),1),'tests':tests,
            'scope':'RONN R7 deterministic agent/freshness/risk/capability checks; not a benchmark of external provider intelligence.'}
