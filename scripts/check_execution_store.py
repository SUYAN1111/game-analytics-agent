"""Fast checks for migration, event ownership, partial log writes and late delivery."""
import json
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from web_api.store import Store
from web_api.service import Service
from task13_runtime.progress import ProgressReader

def main():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'web.sqlite3'
        store=Store(path)
        with store.connect() as db:
            db.execute("INSERT INTO sessions VALUES('s','owner','legacy','open',1)")
            db.execute("INSERT INTO jobs VALUES('j','s','t','idem','question','running',1,1,NULL,NULL)")
            db.execute("INSERT INTO events(job_id,status,at) VALUES('j','queued',1)")
            # Recreate the pre-migration event schema with a real historical event.
            db.execute('DROP INDEX progress_identity');db.execute('ALTER TABLE events DROP COLUMN detail');db.execute('ALTER TABLE events DROP COLUMN event_key');db.execute('PRAGMA user_version=1')
        store=Store(path)
        service=Service.__new__(Service);service.store=store;service.cv=threading.Condition(threading.RLock())
        event={'turn_id':'t','code':'tool_started','tool':'query_metric','operation':'one','secret':'must not leak'}
        service.progress('s','j','t',event);service.progress('s','j','t',event)
        service.progress('other','j','t',{**event,'operation':'cross-session'})
        service.progress('s','j','t',{**event,'turn_id':'old','operation':'cross-turn'})
        service.progress('s','j','t',{**event,'tool':'arbitrary','operation':'unknown-tool'})
        with store.connect() as db:
            row=db.execute("SELECT * FROM jobs WHERE id='j'").fetchone();job=Store.job(db,row)
            assert len(job['events'])==2 and job['events'][0]['kind']=='state'
            assert all(e['session_id']=='s' and e['job_id']=='j' and e['turn_id']=='t' for e in job['events'])
            assert 'secret' not in json.dumps(job)
            assert len(Store.job(db,row,job['events'][0]['seq'])['events'])==1
            Service.transition(db,'j','cancelled')
        service.progress('s','j','t',{**event,'operation':'late'})
        with store.connect() as db: assert db.execute('SELECT count(*) FROM events').fetchone()[0]==3
        folder=Path(directory);log=folder/'execution.jsonl';received=[];reader=ProgressReader(folder,'t',received.append)
        raw=json.dumps(event).encode();log.write_bytes(raw[:20]);reader.drain();assert not received
        with log.open('ab') as f:f.write(raw[20:]+b'\n'+json.dumps({**event,'turn_id':'other'}).encode()+b'\n')
        reader.drain();reader.drain();assert len(received)==1
    print('PASS: v1 migration, scoped/cursor events, deduplication, no late or private events, partial append recovery')

if __name__=='__main__':main()
