"""Owner/turn isolation, restart, unknown fees and deletion against a real SQLite store."""
import json,sys,tempfile,threading
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from web_api.service import Service,APIError
from web_api.store import Store

def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=root/'budget.json'
        def attempt(turn,cost=None):
            row={'turn_id':turn,'session':'core-'+turn,'reserved_cny':.1,'status':'reserved_fee_unknown'}
            if cost is not None:row.update(actual_cny=cost,status='settled',raw_usage={'prompt_tokens':100,'completion_tokens':20,'prompt_cache_hit_tokens':40,'prompt_cache_miss_tokens':60})
            return row
        state={'attempts':[attempt('t1',.01),attempt('t1',.02),attempt('t2'),attempt('other',2.0)],'stopped':False,'limit_cny':5}
        ledger.write_text(json.dumps(state))
        def service():
            s=Service.__new__(Service);s.mode='live';s.period='test';s.queue_limit=8
            s.cv=threading.Condition(threading.RLock());s.store=Store(root/'web.sqlite3')
            s.runtime=SimpleNamespace(ledger=SimpleNamespace(path=ledger,failure_path=root/'missing',commit_error=None))
            s.cores={};s.opening=set();s.executing=set();s.controllers=[]
            return s
        s=service()
        with s.store.connect() as db:
            for sid,owner in [('a','alice'),('b','bob')]:db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(sid,owner,'title','read_only',1))
            for jid,sid,tid in [('j1','a','t1'),('j2','a','t2'),('j3','b','other')]:
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,sid,tid,jid,'question','succeeded',1,2,None,None))
        a=s.session('alice','a');assert a['usage']['estimated_cny']==.03 and a['usage']['request_count']==3
        assert a['usage']['pending_reserved_cny']==.1 and a['usage']['pending_requests']==1
        assert a['usage']['input_tokens']==200 and a['usage']['output_tokens']==40
        assert s.job('alice','j1')['usage']['estimated_cny']==.03
        assert s.job('alice','j2')['usage']['estimated_cny']==0 and s.job('alice','j2')['usage']['pending_requests']==1
        try:s.job('alice','j3');raise AssertionError('Cross-owner usage leaked')
        except APIError as e:assert e.status==404
        assert s.health()['budget']=={'stopped':False}
        restarted=service();assert restarted.session('alice','a')['usage']['estimated_cny']==.03
        state['attempts'][2]=attempt('t2',.04);ledger.write_text(json.dumps(state))
        updated=s.session('alice','a')['usage'];assert updated['estimated_cny']==.07 and updated['pending_requests']==0
        before=ledger.read_bytes();s.delete_session('alice','a');assert ledger.read_bytes()==before
        assert s.session('bob','b')['usage']['estimated_cny']==2
        s.mode='offline';u=s.session('bob','b')['usage'];assert u['request_count']==0 and u['estimated_cny']==0
        print('Public usage isolation, settlement updates, restart, deletion, offline exclusion: PASS')

if __name__=='__main__':main()
