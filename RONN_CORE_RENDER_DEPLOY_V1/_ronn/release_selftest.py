import re
import json
import py_compile
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent

CORE_PY=[
    'app.py','launcher.py','r5_intelligence.py','project_indexer.py','quality_gate.py','r5_benchmarks.py',
    'cognitive_os.py','intelligence_core.py','goal_engine.py','task_engine.py','provider_engine.py','brevity_engine.py','r6_intelligence.py','r6_benchmarks.py','r7_impact.py','r7_benchmarks.py','knowledge_base.py','snapshot_engine.py','task_queue.py','core_api.py','core_store.py','core_store_pg.py','memory_store_pg.py','r20_controller.py','r20_web_tools.py','r20_tool_hub.py','owner_auth.py','ecosystem_store.py','ecosystem_api.py','routine_scheduler.py'
]

def run():
    rows=[]
    def check(name,fn):
        try:
            detail=fn(); rows.append({'name':name,'passed':bool(detail if not isinstance(detail,dict) else detail.get('passed',True)),'detail':detail})
        except Exception as exc: rows.append({'name':name,'passed':False,'detail':str(exc)[:500]})

    def compile_python():
        for name in CORE_PY: py_compile.compile(str(BASE/name),doraise=True)
        return f'{len(CORE_PY)} core Python files compiled'
    check('python_compile',compile_python)

    def html_js_ids():
        html=(BASE/'static/index.html').read_text(encoding='utf-8')
        js=(BASE/'static/app.js').read_text(encoding='utf-8')
        ids=set(re.findall(r'id=["\']([^"\']+)',html))
        refs=set(re.findall(r'\$\(["\']([^"\']+)["\']\)',js))
        missing=sorted(refs-ids)
        if missing: raise RuntimeError('Missing DOM ids: '+', '.join(missing))
        return {'passed':True,'html_ids':len(ids),'direct_js_refs':len(refs),'missing':[]}
    check('dom_reference_integrity',html_js_ids)

    def css_balance():
        css=(BASE/'static/style.css').read_text(encoding='utf-8')
        if css.count('{')!=css.count('}'): raise RuntimeError('CSS brace mismatch')
        required=['.chatViewport','.jumpLatest','.composerDock','.aiBubble','.brandMark img','.voiceMini','.toggleGroup','.plusMenu','.sectionTabs','.cinematicTagline']
        missing=[x for x in required if x not in css]
        if missing: raise RuntimeError('Missing required CSS selectors: '+', '.join(missing))
        return {'passed':True,'rules':css.count('{'),'required_selectors':required}
    check('css_structure',css_balance)

    def static_files():
        req=['static/index.html','static/app.js','static/style.css','static/ronn_app_icon.png','integrity_manifest.json','../mobile/App.js','../mobile/package.json','../mobile/app.json','../mobile/README.md']
        missing=[x for x in req if not (BASE/x).exists()]
        if missing: raise RuntimeError('Missing files: '+', '.join(missing))
        return {'passed':True,'files':req}
    check('static_files',static_files)

    def cinematic_interactions():
        html=(BASE/'static/index.html').read_text(encoding='utf-8')
        js=(BASE/'static/app.js').read_text(encoding='utf-8')
        css=(BASE/'static/style.css').read_text(encoding='utf-8')
        required_html=[
            'data-view="chat"','data-view="projects"','data-view="brain"','data-view="settings"',
            'id="plusMenu"','id="plusAttach"','id="plusNewChat"','id="plusProject"','id="plusMemory"',
            'data-view-target="memory"','data-view-target="diagnostics"'
        ]
        missing_html=[x for x in required_html if x not in html]
        required_js=['plusMenu?.classList.toggle','$("plusAttach").onclick','$("plusNewChat").onclick','qsa("[data-view-target]")']
        missing_js=[x for x in required_js if x not in js]
        required_css=['.plusMenu{','.sectionTabs{','.cinematicTagline{','.composerWrap{']
        missing_css=[x for x in required_css if x not in css]
        if missing_html or missing_js or missing_css:
            raise RuntimeError(f'Cinematic UI wiring missing html={missing_html}, js={missing_js}, css={missing_css}')
        return {'passed':True,'sidebar_tabs':4,'plus_actions':4,'subnavs':2}
    check('cinematic_interactions',cinematic_interactions)

    def config_recovery():
        import tempfile, shutil
        import launcher as launch
        original = {
            'ROOT': launch.ROOT,
            'ENV_FILE': launch.ENV_FILE,
            'candidate_roots': launch._candidate_roots,
            'shared_config_path': launch.shared_config_path,
        }
        tmp = Path(tempfile.mkdtemp(prefix='ronn-config-test-'))
        try:
            current = tmp/'new'/'RONN_NEW'
            current.mkdir(parents=True)
            env = current/'.env'
            env.write_text('CLOUD_API_KEY=PASTE_YOUR_GROQ_API_KEY_HERE\n',encoding='utf-8')
            old = tmp/'archive'/'RONN_OLD'/'inner'
            old.mkdir(parents=True)
            (old/'.env').write_text('CLOUD_API_BASE=https://api.groq.com/openai/v1\nCLOUD_API_KEY=gsk_test_recovery_key\n',encoding='utf-8')
            shared = tmp/'shared'/'config.env'
            launch.ROOT = current
            launch.ENV_FILE = env
            launch._candidate_roots = lambda: [tmp]
            launch.shared_config_path = lambda: shared
            result = launch.ensure_env()
            vals = launch._parse_env_values(env)
            if not result.get('configured') or vals.get('CLOUD_API_KEY') != 'gsk_test_recovery_key' or not shared.exists():
                raise RuntimeError('provider config migration/persistence failed')
            return {'passed':True,'placeholder_recovered':True,'persistent_config_created':True}
        finally:
            launch.ROOT = original['ROOT']
            launch.ENV_FILE = original['ENV_FILE']
            launch._candidate_roots = original['candidate_roots']
            launch.shared_config_path = original['shared_config_path']
            shutil.rmtree(tmp,ignore_errors=True)
    check('provider_config_recovery',config_recovery)

    def core_api_contract():
        import core_api, core_store
        required={
            '/api/v1/health','/api/v1/meta','/api/v1/session','/api/v1/status','/api/v1/capabilities','/api/v1/chat','/api/v1/research',
            '/api/v1/chat/complete','/api/v1/chat/sse','/api/v1/conversations','/api/v1/projects','/api/v1/memory','/api/v1/tasks','/api/v1/files/index','/api/v1/providers','/api/v1/providers/check','/api/v1/repair-plan','/api/v1/diagnostics','/api/v1/settings'
        }
        paths={r.path for r in core_api.router.routes}
        missing=sorted(required-paths)
        if missing: raise RuntimeError('Missing Core API v1 routes: '+', '.join(missing))
        owner='selftest_core_owner'
        p=core_store.create_project(owner,'Selftest project','Core API contract test')
        c=core_store.create_conversation(owner,p['project_id'],'Selftest chat')
        core_store.add_message(owner,c['conversation_id'],'user','hello')
        loaded=core_store.get_conversation(owner,c['conversation_id'],True)
        settings=core_store.update_settings(owner,{'response_style':'concise','reasoning_mode':'deep','agent_mode':True})
        if not loaded or len(loaded.get('messages',[]))!=1 or settings.get('response_style')!='concise':
            raise RuntimeError('Core persistence contract failed')
        core_store.delete_conversation(owner,c['conversation_id'])
        core_store.delete_project(owner,p['project_id'])
        return {'passed':True,'api_version':core_api.API_VERSION,'core_version':core_api.CORE_VERSION,'route_count':len(paths),'persistence':True}
    check('core_api_v1_contract',core_api_contract)

    def ecosystem_contract():
        import ecosystem_api, ecosystem_store
        required={
            '/api/v1/owner/status','/api/v1/owner/unlock','/api/v1/owner/recovery-codes','/api/v1/devices','/api/v1/devices/register',
            '/api/v1/sync/pull','/api/v1/sync/push','/api/v1/actions','/api/v1/vault','/api/v1/handoffs','/api/v1/clipboard',
            '/api/v1/notifications','/api/v1/workflows','/api/v1/workflows/{workflow_id}/run','/api/v1/routines','/api/v1/shortcuts',
            '/api/v1/workspaces','/api/v1/feature-flags','/api/v1/backups','/api/v1/plugins','/api/v1/ecosystem/status',
            '/api/v1/sandbox/analyze','/api/v1/share/intake','/api/v1/quick-actions'
        }
        paths={r.path for r in ecosystem_api.router.routes}
        missing=sorted(required-paths)
        if missing: raise RuntimeError('Missing ecosystem routes: '+', '.join(missing))
        owner='selftest_ecosystem_owner'
        device='selftest-device'
        ecosystem_store.register_device(owner,device,'Selftest phone','test','0.1',False)
        ecosystem_store.set_permission(owner,device,'camera',True)
        perms=ecosystem_store.list_permissions(owner,device)
        ecosystem_store.record_sync(owner,'mobile_draft','draft1','upsert',{'text':'hello'})
        sync=ecosystem_store.pull_sync(owner,0,50)
        wid=ecosystem_store.workflow_save(owner,'Selftest workflow',[{'type':'prompt','prompt':'test'}])
        rid=ecosystem_store.routine_save(owner,'Selftest routine',60,prompt='test')
        ecosystem_store.shortcut_set(owner,'selftest','test prompt')
        workspace=ecosystem_store.workspace_create(owner,'Selftest workspace')
        if not perms or not sync.get('events') or not ecosystem_store.workflow_get(owner,wid) or not rid or not workspace:
            raise RuntimeError('ecosystem persistence contract failed')
        return {'passed':True,'route_count':len(paths),'device_permissions':True,'sync':True,'workflow':True,'routine':True,'workspace':True}
    check('ecosystem_contract',ecosystem_contract)

    def owner_verifier_storage():
        cfg=json.loads((BASE/'owner_bootstrap.json').read_text(encoding='utf-8'))
        flat=json.dumps(cfg).lower()
        if 'plaintext' in flat or 'password' in cfg or 'secret' in cfg:
            raise RuntimeError('Owner bootstrap contains a plaintext credential field')
        required={'owner_display_name','algorithm','iterations','salt_b64','hash_b64'}
        if not required.issubset(cfg): raise RuntimeError('Owner verifier metadata incomplete')
        if cfg.get('algorithm')!='pbkdf2_sha256' or int(cfg.get('iterations',0))<300000:
            raise RuntimeError('Owner verifier work factor is too weak')
        return {'passed':True,'salted_verifier_only':True,'iterations':int(cfg['iterations'])}
    check('owner_verifier_storage',owner_verifier_storage)

    def vault_encryption():
        import ecosystem_store
        owner='selftest_vault_owner'; sentinel='RONN_SELFTEST_VAULT_PLAINTEXT_SENTINEL_7842'
        item=ecosystem_store.vault_put(owner,'Selftest',sentinel)
        loaded=ecosystem_store.vault_get(owner,item['id'])
        raw=ecosystem_store.DB.read_bytes()
        ecosystem_store.vault_delete(owner,item['id'])
        if not loaded or loaded.get('text')!=sentinel: raise RuntimeError('Vault decrypt roundtrip failed')
        if sentinel.encode() in raw: raise RuntimeError('Vault plaintext appeared in SQLite bytes')
        return {'passed':True,'roundtrip':True,'plaintext_not_in_database':True}
    check('vault_encryption_at_rest',vault_encryption)

    def mobile_foundation():
        app=(ROOT/'mobile/App.js').read_text(encoding='utf-8')
        pkg=json.loads((ROOT/'mobile/package.json').read_text(encoding='utf-8'))
        cfg=json.loads((ROOT/'mobile/app.json').read_text(encoding='utf-8'))
        markers=['/api/v1/chat/complete','expo-secure-store','expo-local-authentication','KeyboardAvoidingView','X-RONN-OP-Session','/owner/unlock']
        missing=[m for m in markers if m not in app and m not in json.dumps(pkg)]
        if missing: raise RuntimeError('Native mobile shell missing: '+', '.join(missing))
        if cfg.get('expo',{}).get('ios',{}).get('bundleIdentifier')!='com.ronn.ai':
            raise RuntimeError('Native mobile bundle identifier missing')
        return {'passed':True,'native_input':True,'secure_owner_token':True,'biometric_gate':True,'safari_independent':True}
    check('mobile_client_foundation',mobile_foundation)

    def r21_finishline():
        import brevity_engine, r20_tool_hub, memory_store_pg
        appjs=(BASE/'static/app.js').read_text(encoding='utf-8')
        css=(BASE/'static/style.css').read_text(encoding='utf-8')
        policy=brevity_engine.response_length_policy("who's jolyne kujo","balanced",0,False,False,False)
        directive=brevity_engine.brevity_directive(policy)
        if policy.get('tier')!='quick' or int(policy.get('max_tokens') or 999)>180:
            raise RuntimeError('Simple identity questions are not forced into quick-answer mode')
        if 'Do not use headings, bullets' not in directive:
            raise RuntimeError('Quick-answer anti-list directive missing')
        tools=r20_tool_hub.plan("what's the weather in Seattle",needs_live=True)
        if 'weather' not in tools:
            raise RuntimeError('Weather tool is not automatically selected')
        if not app_module.looks_like_internal_tool_payload('{"tool":"groq_web_search","args":{"query":"x"}}'):
            raise RuntimeError('Raw tool payload guard failed')
        for marker in ('renderMetaCards','weatherCard','sourceCards','c.messages.push({role,content,requestId,audit,meta})'):
            if marker not in appjs and marker not in css:
                raise RuntimeError('Rich answer presentation missing '+marker)
        pg=memory_store_pg.status()
        return {'passed':True,'short_answers':True,'tool_hub':True,'tool_leak_guard':True,'rich_cards':True,'memory_backend':pg.get('backend')}
    check('r21_finishline',r21_finishline)

    from evaluation_engine import run_internal_eval
    from r5_benchmarks import run_r5_benchmarks
    from r6_benchmarks import run_r6_benchmarks
    from r7_benchmarks import run_r7_benchmarks
    import app as app_module
    from app import verify_package_integrity

    def brainfix_extractors():
        a=app_module._final_text([{"type":"text","text":"Hello"},{"text":" world"}])
        b=app_module.extract_stream_text({"choices":[{"delta":{"content":[{"type":"text","text":"RONN_OK"}]}}]})
        c=app_module.likely_live_ranking("who are the best 10 streamers")
        if a != "Hello world" or b != "RONN_OK" or not c:
            raise RuntimeError(f"brainfix parser/routing mismatch: {a!r}, {b!r}, {c!r}")
        return {"passed":True,"structured_content":True,"live_ranking_route":True}
    check('brainfix_parsing_and_routing',brainfix_extractors)

    def empty_stream_recovery():
        class FakeResponse:
            ok=True; status_code=200; text=''
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def iter_lines(self):
                return iter([b'data: {"choices":[{"delta":{}}]}', b'data: [DONE]'])
        old_nonstream=app_module.nonstream_with_fallback
        old_save=app_module.save_message
        old_audit=app_module.answer_audit
        old_static=app_module.static_code_checks
        old_quality=app_module.quality_report
        try:
            app_module.nonstream_with_fallback=lambda *a,**k:("Recovered final answer","backup-test-model")
            app_module.save_message=lambda *a,**k:None
            app_module.answer_audit=lambda *a,**k:{}
            app_module.static_code_checks=lambda *a,**k:{}
            app_module.quality_report=lambda *a,**k:{}
            out=list(app_module.stream_response(FakeResponse(),"test-owner","hello","knowledge","bad-model",profile="knowledge",retry_messages=[{"role":"user","content":"hello"}]))
            joined=''.join(out)
            if "Recovered final answer" not in joined or "empty response" in joined:
                raise RuntimeError("empty stream did not recover through fallback")
            return {"passed":True,"automatic_empty_stream_recovery":True}
        finally:
            app_module.nonstream_with_fallback=old_nonstream
            app_module.save_message=old_save
            app_module.answer_audit=old_audit
            app_module.static_code_checks=old_static
            app_module.quality_report=old_quality
    check('brainfix_empty_stream_recovery',empty_stream_recovery)

    core=run_internal_eval(); r5=run_r5_benchmarks(); r6=run_r6_benchmarks(); r7=run_r7_benchmarks(); integrity=verify_package_integrity()
    rows.append({'name':'core_regression','passed':core.get('score')==100,'detail':{'passed':core.get('passed'),'total':core.get('total'),'score':core.get('score')}})
    rows.append({'name':'r5_regression','passed':r5.get('score')==100,'detail':{'passed':r5.get('passed'),'total':r5.get('total'),'score':r5.get('score')}})
    rows.append({'name':'r6_regression','passed':r6.get('score')==100,'detail':{'passed':r6.get('passed'),'total':r6.get('total'),'score':r6.get('score')}})
    rows.append({'name':'r7_regression','passed':r7.get('score')==100,'detail':{'passed':r7.get('passed'),'total':r7.get('total'),'score':r7.get('score')}})
    rows.append({'name':'package_integrity','passed':bool(integrity.get('verified')),'detail':integrity})
    passed=sum(1 for x in rows if x['passed'])
    return {'passed':passed,'total':len(rows),'ok':passed==len(rows),'checks':rows}

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
