"""Small extraction-risk checks. Loopback provider only; real DSH and MCP."""
import copy,json,os,sys,time,traceback,threading,shutil
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from product_core.paths import ROOT,ASSETS,STATE
from product_core.release import verify,asset_trust
from agent_runtime.common import read,write,lines,sha,canonical,HostError

def check(ok,message):
    if not ok:raise AssertionError(message)
def expect_error(f):
    try:f()
    except Exception as e:return {'type':type(e).__name__,'message':str(e)}
    raise AssertionError('expected rejection did not occur')
def envelope(body='{{note:causality}}',**fields):
    return {'answer_markdown':body,'claims':[],'knowledge_selections':[],'cluster_selections':[],'rule_selections':[],**fields}
def main():
    home=STATE/('validation-'+uuid4().hex);home.mkdir(parents=True)
    results=[]
    def run(name,f):
        print(name+': starting',flush=True);start=time.monotonic()
        try:detail=f();r={'name':name,'status':'PASS','detail':detail}
        except Exception as e:r={'name':name,'status':'FAIL','type':type(e).__name__,'message':str(e),'traceback':traceback.format_exc()}
        r['seconds']=time.monotonic()-start;results.append(r);write(home/(name+'.json'),r)
        print(name+': '+r['status']+' '+str(round(r['seconds'],2))+'s',flush=True)
        return r['status']=='PASS'
    def installation():
        m=verify()
        check(Path(sys.prefix).resolve()!=Path(sys.base_prefix).resolve(),'requires fresh core venv')
        check(not os.environ.get('PYTHONPATH'),'PYTHONPATH must be cleared')
        import importlib.metadata as im
        packages={d.metadata['Name'].lower().replace('_','-'):d.version for d in im.distributions()}
        for line in (ROOT/'requirements-core.lock').read_text().splitlines():
            n,v=line.split('==');check(packages.get(n)==v,'locked dependency differs '+n)
        return {'release_id':m['release_id'],'python':sys.executable,'packages':packages}
    def budgets():
        from product_core.budget import GlobalBudget
        from agent_runtime import common
        b=GlobalBudget(home/'budget_faults/recover.json');original=common.os.replace;calls=[]
        def rename(src,dst):
            if Path(dst)==b.path and len(calls)<2:
                calls.append('conflict');e=PermissionError('offline Windows sharing conflict');e.winerror=32;raise e
            return original(src,dst)
        with patch.object(common.os,'replace',rename):a=b.reserve_for('s','t',80,request_sha256='0'*64)
        check(len(read(b.path)['attempts'])==1 and len(calls)==2,'reservation repeated')
        usage={'prompt_tokens':100,'prompt_cache_hit_tokens':25,'prompt_cache_miss_tokens':75,'completion_tokens':20}
        b.settle(a['attempt_id'],usage);before=sha(b.path)
        duplicate=expect_error(lambda:b.settle(a['attempt_id'],usage))
        check(sha(b.path)==before,'duplicate settlement changed ledger')
        p=GlobalBudget(home/'budget_faults/permanent.json');a=p.reserve_for('s','t',80,request_sha256='1'*64);before=p.path.read_bytes()
        def denied(src,dst):
            if Path(dst)==p.path:
                e=PermissionError('offline persistent Windows access conflict');e.winerror=5;raise e
            return original(src,dst)
        with patch.object(common.os,'replace',denied):failure=expect_error(lambda:p.settle(a['attempt_id'],usage))
        check(p.path.read_bytes()==before and p.failure_path.exists(),'failed commit changed authoritative ledger')
        stopped=expect_error(lambda:p.reserve_for('s','next',80,request_sha256='2'*64))
        u=GlobalBudget(home/'budget_faults/unknown.json');a=u.reserve_for('s','t',80,request_sha256='3'*64)
        u.close_session('s');state=read(u.path)
        check(state['stopped'] and state['attempts'][0]['reserved_cny']>0 and 'actual_cny' not in state['attempts'][0],'unknown fee lost')
        return {'recovered_conflicts':2,'settlement_duplicate':duplicate,'permanent':failure,'stopped':stopped,'unknown':state,'HTTP_requests':0}
    def frozen():
        from product_core import release
        from segmentation.assets import FrozenStore
        copyroot=home/'tamper_assets';shutil.copytree(ASSETS,copyroot)
        records=[]
        # External source release remains fixed while the installed asset root is changed.
        with patch.object(release,'ASSETS',copyroot):
            store=FrozenStore(copyroot/'segmentation',asset_trust('segmentation'))
            a,_=store.get('fit_V3main');_,hit=store.get('fit_V3main');check(hit and store.fit_count==0,'frozen cache/fit boundary')
            model=copyroot/'segmentation/model.json';manifest=copyroot/'segmentation/asset_manifest.json';raw=model.read_bytes();mr=manifest.read_bytes()
            model.write_bytes(raw+b' ')
            records.append(expect_error(lambda:store.get('fit_V3main')))
            m=read(manifest);m['files']['model.json']=sha(model);manifest.write_text(canonical(m),'utf-8')
            records.append(expect_error(lambda:FrozenStore(copyroot/'segmentation',asset_trust('segmentation'))))
            model.write_bytes(raw);manifest.write_bytes(mr)
            target=copyroot/'segmentation/snapshots/fit_V3main.json';saved=target.read_bytes();target.unlink()
            records.append(expect_error(lambda:store.get('fit_V3main')));target.write_bytes(saved)
            release.verify()
            joblib=next(copyroot.rglob('*.joblib'));saved=joblib.read_bytes();joblib.write_bytes(saved+b' ')
            records.append(expect_error(lambda:release.verify()));joblib.write_bytes(saved)
            table=next(copyroot.rglob('players.jsonl'));saved=table.read_bytes();table.write_bytes(saved+b' ')
            records.append(expect_error(lambda:release.verify()));table.write_bytes(saved)
            release.verify()
        # Test copy only; kept until external delivery cleanup for review.
        return {'normal_count':a['counts'],'cache_hit':hit,'fit_count':store.fit_count,'rejections':records,'copy_directory':str(copyroot)}
    def integration():
        from product_core.session import Runtime
        from product_core.offline_stub import ModelStub
        base=read(ROOT/'product_core/fixtures/sealed_examples.json')
        definition=read(ASSETS/'runtime/host.json')['definition'];case=definition['case_id']
        query={**base['query_metric']['arguments']};query2={**query,'cohort_id':'cohort_V5'}
        qname='query_metric:'+query['cohort_id']
        seg=read(ASSETS/'segmentation/model.json')['segmentation_model_id'];rule=read(ASSETS/'association/rules.json')['rule_set_id']
        def call(n,a):return {'name':n,'arguments':a}
        scope={'version_id':'V6','group_by':'none','group_value':None,'window_hours':72}
        answer=envelope('{{claim:c1}}\n{{cluster:s1}}\n{{rule:r1}}',
            claims=[{'id':'c1','evidence_id':'$evidence:'+qname,'field':'rate','scope':scope}],
            cluster_selections=[{'id':'s1','evidence_id':'$evidence:assign_segments','field':'assigned_count','scope':{'segmentation_model_id':seg,'snapshot_id':'fit_V3main','segment_id':None}}],
            rule_selections=[{'id':'r1','evidence_id':'$evidence:query_association_rules','field':'eligible_basket_count','scope':{'rule_set_id':rule,'evaluation_id':'discovery_V1_V3','rule_id':None}}])
        stub=ModelStub(home/'provider');other=ModelStub(home/'provider_other')
        try:
            with Runtime() as runtime:
                with runtime.session(offline_base_url=stub.url) as s:
                    stub.script([{'calls':[call('inspect_context',{'case_id':case,'metric_id':definition['metric_id']})]},
                        {'calls':[call('query_metric',query),call('query_metric',query2),call('check_quality',base['check_quality']['arguments']),
                            call('predict_registered',base['predict_registered']['arguments']),call('read_model_card',{'case_id':case,'model_id':definition['model_id']}),
                            call('search_knowledge',{'query':'M03 分子 分母 72小时'}),call('assign_segments',{'segmentation_model_id':seg,'snapshot_id':'fit_V3main'}),
                            call('query_association_rules',{'rule_set_id':rule,'evaluation_id':'discovery_V1_V3'})]},
                        {'calls':[call('compare_results',{'left_evidence_id':'$evidence:query_metric:cohort_V5','right_evidence_id':'$evidence:'+qname}),
                                  call('get_evidence',{'evidence_id':'$evidence:'+qname})]},
                        {'answer':answer,'resolve_answer_refs':True}])
                    actual=s.turn('Offline extraction check: query approved V5/V6 and frozen analysis.');write(home/'verified_answer.json',actual)
                    calls=list(lines(s.directory/'mcp/tool_calls.jsonl'));by={c['name']:c['result'] for c in calls}
                    check(len(by)==10 and all(c['result'].get('error') is None for c in calls),'ten actual tools must succeed')
                    q=next(c['result'] for c in calls if c['name']=='query_metric' and c['arguments']==query)
                    check(q['data']==base['query_metric']['data'],'sealed M03 differs')
                    check(by['predict_registered']['data']==base['predict_registered']['data'],'sealed frozen prediction differs')
                    check(by['check_quality']['data']==base['check_quality']['data'],'sealed quality differs')
                    check(by['inspect_context']['data']==base['inspect_context']['data'],'sealed public context differs')
                    comparison=by['compare_results']['data']['rows'][0]
                    check(abs(comparison['rate_difference']-(1578/4018-1405/3706))<1e-12,'comparison arithmetic differs')
                    from task12_knowledge.corpus import Corpus
                    expected=Corpus().search({'query':'M03 分子 分母 72小时'})
                    check(by['search_knowledge']['hits']==expected['hits'],'knowledge differs from pinned corpus')
                    check(by['assign_segments']['data']['counts']==read(ASSETS/'segmentation/results/fit_V3main.json')['counts'],'segmentation differs')
                    check(by['query_association_rules']['data']['counts']==read(ASSETS/'association/public/discovery_V1_V3.json')['counts'],'rules differ')
                    check(by['get_evidence']['data']['content']['data']==q['data'],'returned evidence content differs')
                    check(by['read_model_card']['data']==read(ASSETS/'runtime/host.json')['cards']['analysis_demo'],'published model cards differ')
                    first_session=q['session_id'];first_evidence=q['evidence_id']
                    # Follow-up uses the same real DSH session, with a fresh forced context.
                    stub.script([{'calls':[call('inspect_context',{'case_id':case})]},{'answer':envelope()}])
                    follow=s.turn('Can the prior comparison establish causality?');write(home/'followup.json',follow)
                    requests=list(lines(home/'provider/requests.jsonl'))
                    check(all(r['request']['response_format']=={'type':'json_object'} for r in requests),'JSON mode missing')
                    check(requests[-2]['request']['tool_choice']['function']['name']=='inspect_context' and requests[-1]['request']['tool_choice']=='auto','turn context reset failed')
                    with runtime.session(offline_base_url=other.url,summary=True) as s2:
                        other.script([{'calls':[call('inspect_context',{'case_id':case})]},{'answer':envelope('{{note:limitations}}')}])
                        s2.turn('Independent session: explain scope limitations.')
                        c2=list(lines(s2.directory/'mcp/tool_calls.jsonl'))
                        check(c2[0]['result']['session_id']!=first_session,'MCP session leaked')
                        check(first_evidence not in canonical(list(lines(home/'provider_other/requests.jsonl'))),'first evidence leaked to second session')
                    ledger=read(runtime.ledger.path)
                    check(all(a['status']=='settled' for a in ledger['attempts']),'unsettled offline request')
                    out={'tools':sorted(by),'M03':q['data']['rows'],'prediction':by['predict_registered']['data']['rows'],
                        'model_fit_count':by['assign_segments']['execution']['fit_count'],'rule_mine_count':by['query_association_rules']['execution']['mine_count'],
                        'requests':len(ledger['attempts']),'state':str(runtime.directory),'real_api_calls':0}
                    return out
        finally:stub.close();other.close()
    def lifecycle():
        from product_core.session import Runtime
        from product_core.offline_stub import ModelStub
        stub=ModelStub(home/'slow_provider');out=[]
        try:
            for cancellation in (False,True):
                with Runtime() as runtime:
                    s=runtime.session(offline_base_url=stub.url);stub.script([{'delay':10,'answer':envelope()}])
                    if cancellation:
                        errors=[]
                        def work():
                            try:s.turn('Cancellation check',timeout=30)
                            except BaseException as e:errors.append(type(e).__name__)
                        t=threading.Thread(target=work);t.start()
                        deadline=time.monotonic()+15
                        while stub.index==0 and time.monotonic()<deadline:time.sleep(.05)
                        s.cancel();t.join(15);check(not t.is_alive(),'cancelled turn thread alive')
                    else:errors=[expect_error(lambda:s.turn('Timeout check',timeout=2))]
                    events=list(lines(s.directory/'controller/lifecycle.jsonl'))
                    check(any(e['event']=='terminated_owned_tree' and e['pids_after']==[] for e in events),'owned job not empty')
                    ledger=read(runtime.ledger.path)
                    check(ledger['stopped'] and all(a.get('actual_cny') is None and a['reserved_cny']>0 for a in ledger['attempts']),'cancel unknown reserve lost')
                    out.append({'cancellation':cancellation,'errors':errors,'ledger':ledger})
            return out
        finally:stub.close()
    run('installation',installation);run('budget_faults',budgets);run('frozen_integrity',frozen)
    ok=run('real_dsh_mcp',integration)
    if ok:run('lifecycle',lifecycle)
    else:results.append({'name':'lifecycle','status':'NOT_RUN','reason':'integration must initialize successfully first'})
    summary={'results':results,'real_api_calls':0,'platform':'Windows only','path':str(home)}
    write(home/'results.json',summary)
    text=['# Product extraction offline verification','',*['- '+r['name']+': '+r['status'] for r in results],
          '', 'Real model API: NOT_RUN. No data generation, training, KMeans fit or rule mining.']
    (home/'acceptance.md').write_text('\n'.join(text)+'\n','utf-8')
    print('Report:',home/'acceptance.md',flush=True)
    return 0 if all(r['status']=='PASS' for r in results) else 1
