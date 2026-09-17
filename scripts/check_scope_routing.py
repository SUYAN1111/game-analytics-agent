"""Contract and store tests; no provider/network requests."""
import json
import sys
import tempfile
import threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from web_api.capabilities import route,model_control,catalog
from web_api.scenarios import planned_script
from web_api.service import Service,APIError
from web_api.store import Store
from task13_runtime.answers import verify_answer


def main():
    cases=[('你好','guidance'),('帮我看看今天的天气','out_of_scope'),
        ('你好，帮我看看后一次更新的剧情未开始比例','execute'),
        ('V5 的剧情未开始比例是多少？','execute'),('对比 V3 和 V4 的剧情开始情况','execute'),
        ('查看前一次更新的剧情参与预测','execute'),('看看不同玩家的游戏习惯','execute'),
        ('玩地图探索的玩家，也会玩支线体验吗？','execute'),
        ('剧情开始情况怎么样','clarification'),('预测玩家流失','out_of_scope'),
        ('分析我上传的文件','out_of_scope'),('V7 的剧情开始情况','out_of_scope'),
        ('V6 北京地区的剧情开始比例','clarification'),('V6 剧情开始比例，只看新玩家','clarification'),
        ('不要查询 V6 的剧情开始比例','clarification'),('哪些玩法经常一起玩','clarification')]
    for text,kind in cases:
        actual=route(text,'offline');assert actual['kind']==kind,(text,actual)
        if kind=='execute':assert planned_script(actual['plan'])[-1]['resolve_answer_refs']
    q=route('剧情开始情况怎么样','offline')
    reply=route('后一次更新','offline',{'routing':q})
    assert reply['plan']['versions']==['V6']
    previous=route('查看前一次更新的玩家分组','offline')
    follow=route('那第二组呢？','offline',{'routing':previous})
    assert follow['plan']=={'kind':'cluster','snapshot':'replay_V5main','group':'G02'}
    partial=route('比较前一次和后一次更新的剧情开始情况，为什么会这样？','offline')
    assert partial['kind']=='execute' and partial['limitations']
    mixed=route('查询 V6 剧情未开始比例，顺便看看天气','offline')
    assert mixed['kind']=='execute' and mixed['limitations']
    assert route('帮我看看新玩家在后一次更新的剧情开始比例','live')['kind']=='live'
    assert route('测试：慢响应与取消','offline')['plan']['kind']=='fault'
    assert route('测试:慢响应与取消','offline')['plan']['question']=='测试：慢响应与取消'
    assert route('测试：错误模型回复','offline')['plan']['kind']=='fault'
    assert route('测试：慢响应与取消','live')['kind']=='out_of_scope'
    assert route('V6 剧情开始比例，付费玩家','offline')['kind']=='out_of_scope'
    mixed=route('查看 V6 剧情开始比例，顺便看 V5 的付费收入','offline')
    assert mixed['kind']=='execute' and mixed['plan']['versions']==['V6'] and mixed['limitations']
    assert route('对比 V6 与 V5 的剧情开始情况','offline')['plan']['versions']==['V5','V6']
    knowledge=route('剧情比例怎么算，顺便看看今天的天气','offline')
    assert knowledge['plan']['kind']=='knowledge' and knowledge['limitations'] and '天气' not in knowledge['plan']['query']
    for payload in [{'response_type':'clarification','reason':'scope'},{'response_type':'out_of_scope','reason':'no_data'}]:
        result=verify_answer(json.dumps(payload),None,None,None,None,'turn')
        assert result['status']=='control_checked' and not result['claims']
    for payload in [{'response_type':'clarification','reason':'invented numbers'}, {'response_type':'out_of_scope','reason':'no_data','answer':'123'}]:
        try:model_control(payload)
        except ValueError:pass
        else:raise AssertionError('free model text accepted')
    with tempfile.TemporaryDirectory() as directory:
        s=Service.__new__(Service);s.store=Store(Path(directory)/'web.sqlite3');s.cv=threading.Condition(threading.RLock())
        s.mode='offline';s.stopping=False;s.queue_limit=1;s.budget=lambda:{'stopped':False}
        session=s.sessions('owner',True);sid=session['id']
        greeting=s.submit('owner',sid,'你好','a'*20)
        assert greeting['status']=='guidance' and greeting['events'][0]['status']=='guidance'
        assert not greeting['evidence'] and s.session('owner',sid)['status']=='open'
        assert s.submit('owner',sid,'你好','a'*20)['id']==greeting['id']
        for owner,text,idem,code in [('other','你好','c'*20,'not_found'),('owner','天气','a'*20,'idempotency_conflict')]:
            try:s.submit(owner,sid,text,idem)
            except APIError as exc:assert exc.code==code
            else:raise AssertionError('invalid submission admitted')
        s.submit('owner',sid,'剧情开始情况怎么样','b'*20)
        queued=s.submit('owner',sid,'后一次更新','c'*20)
        assert queued['routing']['plan']['versions']==['V6'] and queued['text']=='后一次更新'
        with s.store.connect() as db:
            Service.transition(db,queued['id'],'succeeded',answer={'status':'test'})
            assert db.execute('PRAGMA user_version').fetchone()[0]==3
            db.execute('DELETE FROM events');db.execute('DELETE FROM jobs')
            assert db.execute('SELECT count(*) FROM routing').fetchone()[0]==0
        s.budget=lambda:{'stopped':True}
        assert s.submit('owner',sid,'你好','d'*20)['status']=='guidance'
    out=ROOT/'state/scope-routing';out.mkdir(exist_ok=True)
    (out/'contract-results.json').write_text(json.dumps({'status':'PASS','cases':len(cases),'checks':['catalog from registered assets','parameterized calls, no precomputed numbers','unknown qualifiers preserved','clarification and scoped follow-up','partial scope limitations','strict live control protocol','ownership/idempotency','schema 3 and routing cascade deletion','local replies stay open and bypass provider admission']},ensure_ascii=False,indent=2),encoding='utf8')
    print('Scope and control contracts: PASS')

if __name__=='__main__':main()
