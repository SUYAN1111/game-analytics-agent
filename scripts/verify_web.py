"""Offline HTTP integration and restart checks with real owned DSH processes."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from product_core.paths import STATE
from web_api.scenarios import QUESTIONS, FAULTS


def check(ok, message):
    if not ok: raise AssertionError(message)

class Client:
    def __init__(self,port):
        self.base=f'http://127.0.0.1:{port}'
        self.jar=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
    def request(self,path,body=None,expected=200,headers=None):
        request=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8'),
            headers={'Origin':self.base,'Content-Type':'application/json',**(headers or {})})
        try: response=self.opener.open(request,timeout=8)
        except urllib.error.HTTPError as exc: response=exc
        text=response.read().decode('utf-8')
        check(response.status==expected,f'{path}: expected {expected}, got {response.status}: {text[:300]}')
        return json.loads(text) if text.startswith(('{','[')) else text
    def session(self): return self.request('/api/sessions',{},201)['id']
    def submit(self,sid,text,key=None): return self.request(f'/api/sessions/{sid}/turns',{'text':text,'idempotency_key':key or uuid4().hex},202)
    def wait(self,jid,terminal=True):
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            j=self.request('/api/jobs/'+jid)
            if (j['status'] not in ('queued','running','cancelling')) if terminal else j['status']=='running': return j
            time.sleep(.2)
        raise AssertionError('job deadline: '+jid)


def main():
    period='verify-'+uuid4().hex[:12]
    home=STATE/'web/offline'/period
    out=Path(os.environ.get('WEB_TEST_OUTPUT',str(STATE/'task15')));out.mkdir(parents=True,exist_ok=True)
    port=int(os.environ.get('WEB_TEST_PORT','8767'));client=Client(port); process=None; results=[]
    env=os.environ.copy();env.pop('DEEPSEEK_API_KEY',None);env.pop('PYTHONPATH',None)
    env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    log=(out/'http-test-process.log').open('w',encoding='utf-8')
    def start():
        nonlocal process
        process=subprocess.Popen([sys.executable,'-B','-m','web_api','--port',str(port),'--period',period,'--queue-limit','1'],cwd=ROOT,env=env,stdout=log,stderr=log)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try: return client.request('/api/health')
            except (OSError,AssertionError):
                if process.poll() is not None: raise AssertionError('service startup failed')
                time.sleep(.2)
        raise AssertionError('service startup timeout')
    def stop():
        if process and process.poll() is None:
            (home/'stop.request').write_text('stop')
            process.wait(45)
            check(process.returncode==0,'service cleanup failed')
    def passed(name,**detail):
        results.append({'name':name,'status':'PASS',**detail});print(name+': PASS',flush=True)
    try:
        start();other=Client(port);other.request('/api/health')
        sid=client.session();key=uuid4().hex;j=client.submit(sid,QUESTIONS[0],key)
        check('owner' not in client.request('/api/sessions/'+sid),'HttpOnly capability leaked in session DTO')
        check(all('owner' not in s for s in client.request('/api/sessions')),'owner leaked in history')
        check(client.submit(sid,QUESTIONS[0],key)['id']==j['id'],'duplicate admission')
        client.request(f'/api/sessions/{sid}/turns',{'text':QUESTIONS[1],'idempotency_key':key},409)
        client.request(f'/api/sessions/{sid}/turns',{'text':'x','idempotency_key':uuid4().hex,'mode':'live'},422)
        other.request('/api/jobs/'+j['id'],expected=404)
        client.request('/api/sessions',{},403,{'Origin':'https://example.org'})
        client.request('/api/sessions',{},403,{'Host':'evil.example'})
        check(all(c._rest.get('HttpOnly') is not False and c._rest.get('SameSite')=='strict' for c in client.jar),'cookie policy')
        answer=client.wait(j['id']);check(answer['status']=='succeeded','metric execution failed '+str(answer.get('error')))
        events=answer['events'];seqs=[e['seq'] for e in events]
        check(seqs==sorted(set(seqs)),'events duplicate or unordered')
        check(all((e['job_id'],e['session_id'],e['turn_id'])==(j['id'],sid,j['turn_id']) for e in events),'event identity differs')
        calls=[]
        for p in (home/'budget/runs').glob('*/sessions/*/mcp/tool_calls.jsonl'):
            calls += [json.loads(line) for line in p.read_text('utf-8').splitlines() if json.loads(line)['turn_id']==j['turn_id']]
        started=[e for e in events if e.get('code')=='tool_started'];finished=[e for e in events if e.get('code')=='tool_finished']
        check([e['tool'] for e in started]==[c['name'] for c in calls],'displayed stages differ from actual MCP calls')
        check(len(started)==len(finished)==4,'metric actual tool boundaries missing')
        check(any(e.get('code')=='checking' for e in events),'host validation boundary missing')
        for e in started:
            check(any(n.get('operation')==e['operation'] and n.get('tool')==e['tool'] and n['seq']>e['seq'] for n in finished),'tool completion differs')
        check(client.request('/api/jobs/'+j['id']+'?after_seq='+str(seqs[-1]))['events']==[],'cursor repeats history')
        check(not any(word in json.dumps(events) for word in ('arguments','DEEPSEEK_API_KEY','authkey','prompt')),'private progress payload')
        passed('real-execution-events-match-MCP-and-host',steps=len(started),events=len(events))
        count=client.request('/api/health')['budget']['request_count']
        check(client.submit(sid,QUESTIONS[0],key)['id']==j['id'],'terminal retry duplicated')
        check(client.request('/api/health')['budget']['request_count']==count,'retry changed ledger')
        passed('admission-idempotency-owner-origin-validation',requests=count)
        eid=answer['evidence'][0]['id'];uri=f"/api/sessions/{sid}/turns/{j['turn_id']}/evidence/{eid}"
        evidence=client.request(uri);other.request(uri,expected=404)
        sid2=client.session();client.request(uri.replace(sid,sid2),expected=404)
        client.request(uri.replace(j['turn_id'],'turnunknown'),expected=404)
        client.request('/assets/runtime/host.json',expected=404)
        client.request('/state/web/offline/default/budget/budget.json',expected=404)
        # A historical timeout must not poison a later real turn.
        old_bridge=next((home/'budget/runs').glob('*/sessions/*/internal_bridge.jsonl'))
        with old_bridge.open('a',encoding='utf-8') as f:
            f.write(json.dumps({'response':{'error':{'code':'tool_timeout'}},'offline_injection':'historical_previous_turn'})+'\n')
        follow=client.submit(sid,QUESTIONS[4]);check(client.wait(follow['id'])['status']=='succeeded','followup failed')
        check(client.request(uri)==evidence,'followup overwrote old evidence')
        runs=list((home/'budget/runs').glob('*/sessions/*'))
        check(len(runs)==1,'followup rebuilt DSH session')
        before=client.request('/api/health')['budget'];stop();start()
        check(client.request('/api/sessions/'+sid)['status']=='read_only','old context appeared resumable')
        check(client.request(uri)==evidence,'restart lost evidence')
        check(client.request('/api/jobs/'+j['id'])['events']==events,'restart changed execution history')
        check(client.request('/api/health')['budget']==before,'restart reset budget')
        check(client.submit(sid,QUESTIONS[0],key)['id']==j['id'],'restart lost idempotency')
        passed('followup-evidence-and-completed-restart')
        sid3=client.session();slow=client.submit(sid3,FAULTS[0]);client.wait(slow['id'],terminal=False)
        queue_sid=client.session();queued=client.submit(queue_sid,QUESTIONS[0]);
        client.request(f'/api/sessions/{client.session()}/turns',{'text':QUESTIONS[0],'idempotency_key':uuid4().hex},429)
        client.request('/api/jobs/'+queued['id']+'/cancel',{},202)
        check(client.wait(queued['id'])['status']=='cancelled','queued cancel failed')
        check(not any(e['kind']=='progress' for e in client.wait(queued['id'])['events']),'queued cancellation fabricated execution')
        check(client.request('/api/sessions/'+queue_sid)['status']=='open','queued cancel closed context')
        # Wait until a real model HTTP request has been reserved, then cancel it.
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            b=client.request('/api/health')['budget']
            if b['reserved_unknown_cny']>0:break
            time.sleep(.2)
        check(b['reserved_unknown_cny']>0,'slow request never reached actual provider')
        began=time.monotonic();client.request('/api/jobs/'+slow['id']+'/cancel',{},202)
        check(time.monotonic()-began<3,'cancel queued behind blocking turn')
        check(client.wait(slow['id'])['status']=='cancelled','running cancellation failed')
        client.request('/api/jobs/'+slow['id']+'/cancel',{},202)
        cancel_events=client.wait(slow['id'])['events'];time.sleep(1)
        check(client.wait(slow['id'])['events']==cancel_events,'late progress appeared after cancel')
        b=client.request('/api/health')['budget'];check(b['stopped'] and b['reserved_unknown_cny']>0,'unknown fee lost')
        check(client.request('/api/sessions/'+sid3)['status']=='closed','cancelled session still open')
        events=[]
        for p in (home/'budget/runs').glob('*/sessions/*/controller/lifecycle.jsonl'):
            events += [json.loads(line) for line in p.read_text('utf-8').splitlines()]
        check(any(e['event']=='terminated_owned_tree' and e['pids_after']==[] and len(e['pids_before'])>1 for e in events),'actual descendants not confirmed reclaimed')
        stop();start();check(client.request('/api/health')['budget']==b,'restart cleared stopped budget')
        client.request(f'/api/sessions/{client.session()}/turns',{'text':QUESTIONS[0],'idempotency_key':uuid4().hex},409)
        passed('bounded-queue-cancel-process-tree-stopped-budget-restart',budget=b)
        stop()
        # Separate explicit offline period: timeout and interrupted queue cannot contaminate live.
        period+='-timeout';home=STATE/'web/offline'/period;start()
        timeout_job=client.submit(client.session(),FAULTS[1]);check(client.wait(timeout_job['id'])['status']=='timed_out','timeout terminal wrong')
        passed('real-process-timeout')
        stop()
        period+='-interrupt';home=STATE/'web/offline'/period;start()
        running=client.submit(client.session(),FAULTS[0]);client.wait(running['id'],terminal=False)
        interrupted=client.submit(client.session(),QUESTIONS[0]);stop();start()
        check(client.request('/api/jobs/'+interrupted['id'])['status']=='interrupted','unfinished job was replayed')
        passed('unfinished-restart-no-resend')
    finally:
        stop();log.close()
        (out/'http-results.json').write_text(json.dumps({'period':period,'results':results,'real_api':'NOT_RUN'},ensure_ascii=False,indent=2),encoding='utf-8')
    return 0

if __name__=='__main__': raise SystemExit(main())
