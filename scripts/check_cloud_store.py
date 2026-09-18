"""PostgreSQL contract checks against a disposable local PGlite socket instance."""
import json
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
if (ROOT/'_core_vendor').exists():sys.path.insert(0,str(ROOT/'_core_vendor'))
sys.path.insert(0,str(ROOT/'state/cloud-test/python'))
from cloud_api.service import CloudService
from cloud_api.budget import CloudBudget
from cloud_api.auth import issue,valid
from web_api.service import APIError
from agent_runtime.common import HostError

def rejected(fn,code):
    try:fn()
    except (APIError,HostError) as exc:assert exc.code==code,(exc.code,code);return
    raise AssertionError('expected rejection: '+code)

def main():
    url=os.environ.get('CLOUD_TEST_DATABASE_URL','postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable')
    assert '@127.0.0.1:55432/' in url,'this script only uses disposable local test storage'
    s=CloudService(url);other=CloudService(url)
    s.store.check()
    with s.store.connect() as db:
        assert not db.execute('SELECT 1 FROM sessions').fetchone(),'use a fresh test engine'
    a=s.sessions('alice',True)['id'];b=s.sessions('bob',True)['id']
    greeting=s.submit('alice',a,'你好','greeting-0000000001');assert greeting['status']=='guidance'
    job=s.submit('alice',a,'比较两个版本的剧情开始情况','compare-000000001')
    assert other.submit('alice',a,job['text'],'compare-000000001')['id']==job['id']
    rejected(lambda:s.submit('alice',a,'不同问题','compare-000000001'),'idempotency_conflict')
    rejected(lambda:other.job('bob',job['id']),'not_found')
    rejected(lambda:other.submit('bob',b,job['text'],'compare-000000002'),'queue_full')
    claim=s.claim('alice',job['id']);assert claim and other.claim('alice',job['id']) is None
    token=claim[3]
    from product_core.paths import STATE
    STATE.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=STATE) as temp:
        ledger=CloudBudget(s.store,Path(temp)/'budget.json',job['id'],token,a)
        attempt=ledger.reserve_for('physical-a',job['turn_id'],100,request_sha256='a'*64)
        usage={'prompt_tokens':100,'completion_tokens':20,'prompt_cache_hit_tokens':25,'prompt_cache_miss_tokens':75}
        ledger.settle(attempt['attempt_id'],usage=usage)
        assert other.job('alice',job['id'])['usage']['input_tokens']==100
        pending=ledger.reserve_for('physical-a',job['turn_id'],100,request_sha256='b'*64)
        s.cancel('alice',job['id'])
        rejected(lambda:ledger.reserve_for('physical-a',job['turn_id'],100,request_sha256='c'*64),'session_closed')
        rejected(lambda:s.delete_session('alice',a),'delete_pending')
        with s.store.connect() as db:db.execute('UPDATE executions SET deadline=? WHERE job_id=?',(time.time()-1,job['id']))
        other.sweep()
        state=other.store.ledger();assert state['stopped']
        assert state['attempts'][-1]['reserved_cny']==pending['reserved_cny'] and 'actual_cny' not in state['attempts'][-1]
        assert other.job('alice',job['id'])['status']=='interrupted'
        assert s.claim('alice',job['id']) is None
        before=json.dumps(s.store.ledger(),sort_keys=True)
        assert s.delete_session('alice',a)['deleted']
        assert json.dumps(other.store.ledger(),sort_keys=True)==before
        rejected(lambda:other.session('alice',a),'not_found')
        assert other.session('bob',b)['id']==b
    secret='test-access-code-at-least-16';cookie=issue(secret)
    assert valid(cookie,secret) and not valid(cookie+'x',secret) and not valid(cookie,'other-secret')
    print('Cloud Postgres: idempotency, owner isolation, admission, durable usage, cancellation, lost worker, no replay, true deletion: PASS')
if __name__=='__main__':main()
