"""One connection per transaction, guarded by the service state lock."""
import json
import sqlite3
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, 3): raise ValueError('unsupported web schema')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                turn_id TEXT UNIQUE NOT NULL, idem TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, answer TEXT, error TEXT, UNIQUE(session_id,idem));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
                status TEXT NOT NULL, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                turn_id TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS routing(job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE, payload TEXT NOT NULL);

            ''')
            columns = {r[1] for r in db.execute('PRAGMA table_info(events)')}
            if 'detail' not in columns: db.execute('ALTER TABLE events ADD COLUMN detail TEXT')
            if 'event_key' not in columns: db.execute('ALTER TABLE events ADD COLUMN event_key TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS progress_identity ON events(job_id,event_key) WHERE event_key IS NOT NULL')
            db.execute('PRAGMA user_version=3')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db: yield db
        finally: db.close()

    @staticmethod
    def job(db, row, after=0):
        result = dict(row)
        result.pop('idem', None)
        result['answer'] = json.loads(result['answer']) if result['answer'] else None
        result['error'] = json.loads(result['error']) if result['error'] else None
        routing=db.execute('SELECT payload FROM routing WHERE job_id=?',(row['id'],)).fetchone()
        result['routing']=json.loads(routing['payload']) if routing else None
        result['events'] = []
        for event in db.execute('SELECT seq,status,at,detail FROM events WHERE job_id=? AND seq>? ORDER BY seq', (row['id'], after)):
            result['events'].append({**{k:event[k] for k in ('seq','status','at')},
                'kind':'progress' if event['detail'] else 'state', **(json.loads(event['detail']) if event['detail'] else {}),
                'job_id':row['id'], 'session_id':row['session_id'], 'turn_id':row['turn_id']})
        result['evidence'] = [{**{k:r[k] for k in ('id','kind','label')}, 'fact':json.loads(r['payload']).get('fact')} for r in
            db.execute('SELECT id,kind,label,payload FROM evidence WHERE session_id=? AND turn_id=?', (row['session_id'], row['turn_id']))]
        return result
