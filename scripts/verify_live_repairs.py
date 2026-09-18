"""Regression from live failures, using only a loopback model and real tools."""
import copy,json,sys
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from task13_runtime.request_scope import contract,validate_selections,validate_context
from web_api.capabilities import route
from agent_runtime.common import HostError

def reject(fn,code):
    try:fn()
    except HostError as e:assert e.code==code,(e.code,code)
    else:raise AssertionError('Expected rejection: '+code)

def main():
    for text in ['只看第六次更新中北京地区玩家的剧情未开始比例，别用全部玩家代替。','杭州地区剧情开始情况','只看火星区域的玩家']:
        assert route(text,'live')['kind']=='clarification'
    for text in ['给我讲个笑话吧','讲个段子','tell me a joke','我想闲聊','帮我看看今天的天气']:
        assert route(text,'live')['kind']=='out_of_scope'
    assert route('第六次更新达到剧情开启条件后三天还没动静的占几成','live')['kind']=='live'
    def answer(value='R1',version='V6',dimension='region_id'):
        return {'selections':{'claims':[{'scope':{'version_id':version,'group_by':dimension,'group_value':value}}], 'cluster_selections':[],'rule_selections':[]}}
    reject(lambda:validate_selections(answer(),contract('北京玩家的剧情比例')),'scope_authority')
    reject(lambda:validate_selections(answer(None,dimension='none'),contract('北京地区的剧情比例')),'scope_authority')
    validate_selections(answer(),contract('第六次更新 R1 地区剧情比例'))
    reject(lambda:validate_selections(answer('R2'),contract('第六次更新 R1 地区剧情比例')),'scope_authority')
    reject(lambda:validate_selections(answer(version='V5'),contract('第六次更新 R1 地区剧情比例')),'scope_authority')
    previous=contract('第六次更新 R1 地区剧情比例')
    assert contract('对比第五次和第六次更新')['versions']==['5','6']
    assert contract('V7 剧情比例')['versions']==['7']
    assert route('那第五次更新呢？沿用刚才的区域和统计口径。','live',{'routing':{'scope_contract':previous}})['kind']=='live'
    validate_selections(answer(version='V5'),contract('那第五次更新呢，沿用刚才范围',previous))
    validate_selections(answer(version='V5'),contract('那第五次更新呢？沿用刚才的区域和统计口径。',previous))
    reject(lambda:validate_selections(answer(),contract('不看 R1 地区')),'scope_authority')
    validate_selections(answer('R2'),contract('第六次更新按地区比较剧情比例'))
    calls=[{'turn_id':'t','name':'inspect_context','result':{'error':{'code':'unauthorized'}}},
           {'turn_id':'t','name':'inspect_context','result':{'error':None,'status':'ok','evidence_id':'e'}}]
    validate_context(calls,'t')
    reject(lambda:validate_context([calls[0],{'turn_id':'t','name':'query_metric'}]+calls[1:],'t'),'context')
    reject(lambda:validate_context([calls[0],calls[0],calls[1]],'t'),'context')
    reject(lambda:validate_context(calls,'different'),'context')
    import tempfile,threading
    from web_api.service import Service
    from web_api.store import Store
    with tempfile.TemporaryDirectory() as directory:
        s=Service.__new__(Service);s.store=Store(Path(directory)/'web.sqlite3');s.cv=threading.Condition(threading.RLock())
        s.usage_attempts=lambda:[]
        s.mode='live';s.stopping=False;s.queue_limit=1;s.stub=None;s.timeout=10
        s.opening=set();s.executing=set();s.cores={};s.budget=lambda:{'stopped':False}
        sid=s.sessions('owner',True)['id']
        class Mismatched:
            status='open'
            def turn(self,*args,**kwargs):
                s.stopping=True
                raise HostError('scope_authority','No literal authority for guessed group')
            def close(self):raise AssertionError('Clarification must preserve conversation')
        s.cores[sid]=Mismatched()
        job=s.submit('owner',sid,'北京玩家剧情未开始比例是多少','a'*20)
        s.work()
        final=s.job('owner',job['id'])
        assert final['status']=='clarification' and not final['evidence']
        assert s.session('owner',sid)['status']=='open'
    print('Scope authority, context ordering and local routing: PASS',flush=True)
    if '--integration' not in sys.argv:return
    from product_core.session import Runtime
    from product_core.offline_stub import ModelStub
    from web_api.scenarios import planned_script
    out=ROOT/'state'/('repair-offline-'+uuid4().hex[:10]);out.mkdir(parents=True)
    with Runtime(5) as runtime:
        stub=ModelStub(out/'provider')
        with runtime.session(mode='offline',offline_base_url=stub.url) as session:
            actions=planned_script({'kind':'metric','versions':['V5','V6']})
            good=actions[-1];bad=copy.deepcopy(good)
            bad['answer']['claims'][-1]['field']='rate'
            stub.script(actions[:-1]+[bad,good])
            result=session.turn('对比第五次和第六次更新的剧情开始比例',turn_id='repair_compare')
            assert result['status']=='reference_checked_candidate'
            assert (session.directory/'repair_compare_repair.json').exists()
            ledger=json.loads(runtime.ledger.path.read_text(encoding='utf8'))
            attempts=[a for a in ledger['attempts'] if a['turn_id']=='repair_compare']
            assert len(attempts)==5 and all(a['status']=='settled' for a in attempts)
            requests=[json.loads(l)['request'] for l in (out/'provider/requests.jsonl').read_text(encoding='utf8').splitlines()]
            assert requests[-1]['tool_choice']=='none'
            print('Real DSH answer-only correction: PASS (same turn, five requests)',flush=True)
        with runtime.session(mode='offline',offline_base_url=stub.url) as session:
            stub.script([{'calls':[{'name':'inspect_context','arguments':{'case_id':'case_activity_week_v1'}}]},
                             {'calls':[{'name':'inspect_context','arguments':{'case_id':'case_m03_main_v1'}}]},
                             {'answer':{'claims':[],'knowledge_selections':[],'cluster_selections':[],'rule_selections':[],'answer_markdown':'{{note:limitations}}'}}])
            result=session.turn('玩法关联的说明',turn_id='context_correction')
            assert result['status']=='reference_checked_candidate'
            print('Real DSH context parameter correction: PASS',flush=True)
        stub.close()
    (out/'result.json').write_text(json.dumps({'status':'PASS','runtime':str(runtime.directory)}),encoding='utf8')
    print('Evidence: '+str(out),flush=True)

if __name__=='__main__':main()
