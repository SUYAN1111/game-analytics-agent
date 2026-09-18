"""Postgres transactions, never a copied SQLite file. Dedicated schema per deployment."""
import threading
from contextlib import contextmanager
from web_api.store import Store


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


class Connection:
    def __init__(self, connection): self.connection = connection
    def execute(self, sql, params=()):
        # Only our fixed SQL templates enter here; all user values remain parameters.
        if sql.startswith('INSERT OR IGNORE '):
            sql = sql.replace('INSERT OR IGNORE ', 'INSERT ', 1) + ' ON CONFLICT DO NOTHING'
        return self.connection.execute(sql.replace('?', '%s'), params)


class PostgresStore:
    job = staticmethod(Store.job)
    def __init__(self, url):
        self.url, self.local = url, threading.local()

    @contextmanager
    def connect(self):
        if getattr(self.local, 'connection', None) is not None:
            yield self.local.connection
            return
        import psycopg
        # No credentials enter subprocess environments or public exception messages.
        with psycopg.connect(self.url, connect_timeout=10, row_factory=row_factory, prepare_threshold=None) as raw:
            with raw.transaction():
                # Transaction-local settings also work through Neon/PgBouncer.
                raw.execute('SET LOCAL search_path = agent_cloud')
                raw.execute('SET LOCAL statement_timeout = 15000')
                raw.execute('SET LOCAL lock_timeout = 10000')
                raw.execute('SELECT pg_advisory_xact_lock(1587001)')
                wrapper = Connection(raw)
                self.local.connection = wrapper
                try: yield wrapper
                finally: self.local.connection = None

    def check(self):
        with self.connect() as db:
            if db.execute('SELECT version FROM schema_version WHERE id=1').fetchone()[0] != 1:
                raise ValueError('cloud database schema mismatch')

    def ledger(self):
        import json
        with self.connect() as db:
            row = db.execute('SELECT payload FROM budgets WHERE id=1').fetchone()
            if not row: raise ValueError('cloud budget must be initialized explicitly')
            return json.loads(row['payload'])
