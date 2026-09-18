"""Offline ASGI regression against a disposable local Postgres; no model calls."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
for path in (ROOT/'_core_vendor',ROOT/'state/cloud-test/python'):
    if path.exists():sys.path.insert(0,str(path))
from starlette.testclient import TestClient
from cloud_api.app import create_app

def main():
    url=os.environ['CLOUD_TEST_DATABASE_URL']
    if urlsplit(url).hostname not in ('127.0.0.1','localhost'):raise SystemExit('Use a disposable local database')
    origin='http://testserver'
    app=create_app(test_settings={'APP_ORIGIN':origin,'APP_ACCESS_MODE':'invite','APP_ACCESS_CODE':'test-access-code-at-least-16','DATABASE_URL':url})
    headers={'Origin':origin}
    with TestClient(app) as client,TestClient(app) as other:
        assert client.get('/api/sessions').status_code==401
        assert client.post('/_auth',headers=headers,data={'code':'wrong'}).status_code==401
        login=client.post('/_auth',headers=headers,data={'code':'test-access-code-at-least-16'})
        assert login.status_code==200
        owner=client.cookies['web_owner']
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda p:client.get(p),['/api/health','/api/sessions']))
        assert all(r.status_code==200 and 'set-cookie' not in r.headers for r in responses)
        assert client.cookies['web_owner']==owner
        assert client.post('/api/sessions',headers={'Origin':'https://other.invalid'},json={}).status_code==403
        assert client.post('/api/sessions',headers=headers,json={'unexpected':True}).status_code==422
        sid=client.post('/api/sessions',headers=headers,json={}).json()['id']
        result=client.post(f'/api/sessions/{sid}/turns',headers=headers,json={'text':'你好','idempotency_key':'cloud-http-greeting-001'})
        assert result.json()['status']=='guidance'
        other.post('/_auth',headers=headers,data={'code':'test-access-code-at-least-16'})
        assert other.get(f'/api/sessions/{sid}').status_code==404
        assert client.post(f'/api/sessions/{sid}/delete',headers=headers,json={}).status_code==200
        assert client.get(f'/api/sessions/{sid}').status_code==404
        client.cookies.delete('web_owner')
        assert client.get('/').status_code==200 and client.cookies['web_owner']!=owner
    print('Cloud HTTP authentication, initial parallel identity, origin, validation, local routing, isolation, deletion: PASS')

if __name__=='__main__':main()
