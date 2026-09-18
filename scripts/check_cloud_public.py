"""Public visitor admission against disposable local Postgres. No model requests."""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
for directory in (ROOT/'_core_vendor',ROOT/'state/cloud-test/python'):
    if directory.exists():sys.path.insert(0,str(directory))
from starlette.requests import Request
from starlette.testclient import TestClient
from cloud_api.app import create_app
from cloud_api import auth,visitors


def main():
    url=os.environ['CLOUD_TEST_DATABASE_URL']
    if urlsplit(url).hostname not in ('127.0.0.1','localhost'):raise SystemExit('Use a disposable local database')
    origin='http://testserver'
    secret='local-public-test-signing-key'
    settings={'APP_ORIGIN':origin,'APP_ACCESS_CODE':secret,'DATABASE_URL':url}
    app=create_app(test_settings=settings)  # No mode override: public must be the default.
    service=app.state.service
    headers={'Origin':origin}
    checks=[]
    created=[]
    before=service.store.ledger()

    def session(client):
        response=client.post('/api/sessions',headers=headers,json={})
        assert response.status_code==201,response.text
        sid=response.json()['id'];created.append((client.cookies['web_owner'],sid));return sid

    def turn(client,sid,idem,text='比较两个版本的剧情开始情况',extra=None):
        return client.post(f'/api/sessions/{sid}/turns',headers={**headers,**(extra or {})},
                           json={'text':text,'idempotency_key':idem})

    def counters():
        with service.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM login_limits WHERE key LIKE ? ORDER BY key',('public:v1:%',))]

    try:
        with TestClient(app) as a,TestClient(app) as b,TestClient(app) as forged:
            assert a.post('/api/sessions',headers=headers,json={}).status_code==401
            first=a.get('/api/health');assert first.status_code==200,first.text
            owner=a.cookies['web_owner']
            assert auth.valid_owner(owner,a.cookies['web_owner_signature'],secret)
            assert 'app_access' not in a.cookies and all('HttpOnly' in h for h in first.headers.get_list('set-cookie'))
            with ThreadPoolExecutor(max_workers=2) as pool:
                parallel=list(pool.map(lambda p:a.get(p),['/api/health','/api/sessions']))
            assert all(r.status_code==200 and 'set-cookie' not in r.headers for r in parallel)
            assert a.cookies['web_owner']==owner
            assert 'name="code"' not in b.get('/').text
            assert b.get('/_auth',follow_redirects=False).status_code==303
            assert b.cookies['web_owner']!=owner
            checks.append('default public entry establishes a signed anonymous identity without a code')
            checks.append('health bootstrap completes before parallel APIs; identity is stable')

            sid=session(a);other=session(b)
            assert a.get(f'/api/sessions/{sid}').status_code==200
            assert b.get(f'/api/sessions/{sid}').status_code==404
            forged.cookies.set('web_owner',owner,domain='testserver.local',path='/')
            forged.cookies.set('web_owner_signature','0'*64,domain='testserver.local',path='/')
            assert forged.get(f'/api/sessions/{sid}').status_code==401
            forged.get('/api/health')
            assert forged.cookies['web_owner']!=owner
            assert forged.get(f'/api/sessions/{sid}').status_code==404
            assert a.post('/api/sessions',headers={'Origin':'https://other.invalid'},json={}).status_code==403
            assert a.get('/api/health',headers={'Host':'other.invalid'}).status_code==403
            assert a.post('/api/sessions',headers=headers,json={'unexpected':1}).status_code==422
            checks.append('forged cookies, cross-browser history and cross-origin writes are rejected')

            assert turn(a,sid,'public-greeting-001','你好').json()['status']=='guidance'
            assert not any(r['key'].endswith(':analysis') for r in counters())
            job=turn(a,sid,'public-compare-001').json();assert job['status']=='queued',job
            saved=counters()
            assert turn(a,sid,'public-compare-001').json()['id']==job['id']
            assert counters()==saved
            assert turn(a,sid,'public-compare-001','别的问题').status_code==409
            assert turn(b,other,'public-queue-001').status_code==429
            assert counters()==saved
            service.cancel(owner,job['id'])
            assert counters()==saved
            checks.append('local greeting is not an analysis; idempotency and queue rejection do not double count')

            browser_key=f'public:v1:browser:{owner}:analysis'
            with service.store.connect() as db:
                db.execute('UPDATE login_limits SET attempts=? WHERE key=?',(visitors.BROWSER_ANALYSES,browser_key))
            saved=counters()
            rejected=turn(a,sid,'public-exhausted-001')
            assert rejected.status_code==429 and rejected.json()['error']['code']=='public_limit'
            assert counters()==saved
            service.delete_session(owner,sid)
            fresh=session(a)
            assert turn(a,fresh,'public-deleted-001').status_code==429
            assert counters()==saved
            checks.append('browser analysis cap rejects atomically and survives history deletion')

            with service.store.connect() as db:
                db.execute('UPDATE login_limits SET attempts=? WHERE key LIKE ?',(visitors.NETWORK_ANALYSES,'public:v1:network:%:analysis'))
            saved=counters()
            assert turn(b,other,'public-network-001',extra={'X-Forwarded-For':'203.0.113.77','X-Vercel-Forwarded-For':'203.0.113.88'}).status_code==429
            assert counters()==saved
            checks.append('network analysis cap survives a new browser and untrusted forwarded headers')

            with service.store.connect() as db:
                db.execute('UPDATE login_limits SET expires=? WHERE key LIKE ?',(time.time()-1,'public:v1:%'))
            next_job=turn(b,other,'public-next-window-001').json()
            assert next_job['status']=='queued',next_job
            service.cancel(b.cookies['web_owner'],next_job['id'])
            assert all(r['attempts']==1 for r in counters())
            with service.store.connect() as db:
                db.execute('UPDATE login_limits SET attempts=? WHERE key LIKE ?',(visitors.NETWORK_SUBMISSIONS,'public:v1:network:%:submissions'))
            assert turn(b,other,'public-local-flood-001','你好').status_code==429
            checks.append('expired counters renew and local-message flooding is bounded')

            with service.store.connect() as db:
                db.execute('DELETE FROM login_limits WHERE key LIKE ?',('public:v1:%',))
                db.execute('UPDATE budgets SET payload=? WHERE id=1',(json.dumps({**before,'stopped':True}),))
            stopped=turn(b,other,'public-budget-stop-001')
            assert stopped.status_code==409 and stopped.json()['error']['code']=='budget_stopped'
            assert counters()==[]
            assert turn(b,other,'public-budget-guide-001','你好').json()['status']=='guidance'
            with service.store.connect() as db:
                db.execute('UPDATE budgets SET payload=? WHERE id=1',(json.dumps(before),))
            checks.append('global budget stop remains enforced; local guidance still works')

            with service.store.connect() as db:
                db.execute('UPDATE login_limits SET attempts=? WHERE key LIKE ?',
                           (visitors.NETWORK_SUBMISSIONS-1,'public:v1:network:%:submissions'))
            independent=create_app(test_settings=settings)
            with TestClient(independent) as concurrent:
                concurrent.cookies.update(b.cookies)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    requests=[pool.submit(turn,a,fresh,'public-race-a-001','你好'),
                              pool.submit(turn,concurrent,other,'public-race-b-001','你好')]
                    statuses=sorted(r.result().status_code for r in requests)
                assert statuses==[202,429],statuses
            checks.append('two service instances cannot spend the same final admission slot')

        private=create_app(test_settings={**settings,'APP_ACCESS_MODE':'invite'})
        with TestClient(private) as invited,TestClient(app) as migrated:
            assert 'name="code"' in invited.get('/').text
            assert invited.get('/api/health').status_code==401
            assert invited.post('/_auth',headers=headers,data={'code':secret}).status_code==200
            legacy=session(invited);legacy_owner=invited.cookies['web_owner']
            migrated.cookies.update(invited.cookies)
            assert migrated.get('/api/health').status_code==200
            assert migrated.cookies['web_owner']==legacy_owner
            assert auth.valid_owner(legacy_owner,migrated.cookies['web_owner_signature'],secret)
            assert migrated.get(f'/api/sessions/{legacy}').status_code==200
            checks.append('optional invite mode and existing authenticated history migration still work')

        request=Request({'type':'http','client':('198.51.100.5',1234),
                         'headers':[(b'x-vercel-forwarded-for',b'203.0.113.5')]})
        assert visitors.network_key(request,secret,vercel=False)!=visitors.network_key(request,secret,vercel=True)
        assert '203.0.113.5' not in visitors.network_key(request,secret,vercel=True)
        assert service.store.ledger()==before
        checks.append('network keys are HMACs and the budget ledger is unchanged')

        with patch.dict(os.environ, {**settings,'APP_ORIGIN':'https://public-test.invalid',
                                     'DEEPSEEK_API_KEY':'local-placeholder-never-used',
                                     'CLOUD_TEST_MODE':'offline'},clear=True):
            assert create_app().state.service.mode=='live'
        checks.append('production always uses the live model even if a test-mode variable is present')
    finally:
        for owner,sid in created:
            try:service.delete_session(owner,sid)
            except Exception:pass
        with service.store.connect() as db:
            db.execute('UPDATE budgets SET payload=? WHERE id=1',(json.dumps(before),))
            db.execute('DELETE FROM login_limits WHERE key LIKE ?',('public:v1:%',))

    from product_core.paths import STATE
    STATE.mkdir(parents=True,exist_ok=True)
    report={'status':'PASS','checks':checks,'paid_calls':0}
    (STATE/'cloud-public-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
