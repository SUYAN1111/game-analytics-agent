"""Compare compact session lookups to the pre-fix results, including all users.

No model calls. The golden digest was captured from the old full-row SQLite
index for the sealed asset set; it covers each user's normalized, ordered rows.
"""
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from features.contract import TABLE_FIELDS, canonical, validate_row
from features.observed import ObservedIndex
from product_core.paths import ASSETS, STATE
from product_core.release import verify


def main():
    manifest=verify()
    STATE.mkdir(parents=True,exist_ok=True)
    checks=[];report={'status':'FAIL','checks':checks,'paid_calls':0}
    try:
        with tempfile.TemporaryDirectory(prefix='observed-storage-',dir=STATE) as temporary:
            directory=Path(temporary);observed=directory/'observed';observed.mkdir()
            fixture={name:[] for name in TABLE_FIELDS}
            for number in range(20):
                uid=f'玩家-{number:02}'
                fixture['players'].append(dict(user_id=uid,registered_at='2024-01-01T00:00:00Z',
                    cohort_version='V1',available_at='2024-01-01T00:00:00Z'))
                fixture['session_uploads'].append(dict(user_id=uid,upload_id=f'上传-{number:02}',
                    session_id='共同会话' if number<2 else f'会话-{number:02}',source_id='来源',
                    start_at='2024-01-02T08:00:00+00:00',end_at='2024-01-02T09:00:00+00:00',
                    available_at='2024-01-02T10:00:00+00:00'))
            fixture['session_uploads'].reverse()  # Input order must not determine output.
            for name,rows in fixture.items():
                lines=[json.dumps(row,ensure_ascii=False).encode('utf8') for row in rows]
                # CRLF, multibyte identifiers, and an unterminated final row.
                (observed/(name+'.jsonl')).write_bytes(b'\r\n'.join(lines))
            index=ObservedIndex(observed,directory/'fixture.sqlite',{},progress=lambda _:None)
            try:
                normalized=[validate_row('session_uploads',r) for r in fixture['session_uploads']]
                for uid in [p['user_id'] for p in fixture['players']]+['玩家-00','missing-user']:
                    lids={r['session_id'] for r in normalized if r['user_id']==uid}
                    expected=sorted((r for r in normalized if r['session_id'] in lids),key=lambda r:(r['session_id'],r['upload_id']))
                    assert index.sessions(uid)==expected
                assert len(index.sessions('玩家-00'))==2, 'cross-owner logical IDs must remain visible to validation'
                shared=index.sessions('玩家-00')
                assert len(index.user_cache)<=16
            finally:index.close()
            assert index.session_source.closed
            checks.append('UTF-8, CRLF, final line, normalization, logical-ID ownership, ordering and cache eviction')
            memory=ObservedIndex(None,directory/'memory.sqlite',{},fixture=fixture,progress=lambda _:None)
            try:assert memory.sessions('玩家-00')==shared
            finally:memory.close()
            checks.append('explicit small in-memory fixtures retain the same results')

            sessions=observed/'session_uploads.jsonl';original=sessions.read_bytes()
            sessions.write_bytes(original+b'\n'+original.splitlines()[0])
            try:ObservedIndex(observed,directory/'duplicate.sqlite',{},progress=lambda _:None)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('duplicate upload was accepted')
            sessions.write_bytes(original)
            checks.append('duplicate upload IDs are still rejected and failed constructors release source handles')

            source=ASSETS/next(n for n in manifest['asset_files'] if n.endswith('/session_uploads.jsonl'))
            connect=sqlite3.connect
            def limited(*args,**kwargs):
                db=connect(*args,**kwargs);db.execute('PRAGMA max_page_count=8');return db
            with patch('features.observed.sqlite3.connect',side_effect=limited):
                try:ObservedIndex(source.parent,directory/'full.sqlite',{},progress=lambda _:None)
                except sqlite3.OperationalError as exc:assert 'full' in str(exc)
                else:raise AssertionError('quota failure was not reproduced')
            # The failure is local to the derived index, not the surrounding ledger.
            probe=directory/'budget-probe.json';probe.write_text('{"preserved":true}',encoding='utf8')
            assert json.loads(probe.read_text('utf8'))['preserved']
            checks.append('SQLite quota exhaustion closes the source and leaves surrounding storage writable')

            index=ObservedIndex(source.parent,directory/'complete.sqlite',{},progress=lambda _:None)
            try:
                hashes={uid:hashlib.sha256(canonical(index.sessions(uid)).encode('utf8')).hexdigest()
                        for uid in sorted(index.by_user['players'])}
                rows=index.db.execute('SELECT count(*) FROM sessions').fetchone()[0]
                assert manifest['asset_set_id']=='asset143f285f40e8357711e76382ff'
                assert len(hashes)==5000 and rows==690103
                assert hashlib.sha256(canonical(hashes).encode('utf8')).hexdigest()=='5bf82acb0193626237d877bf786afd48bd2f92f805bfd2b9cbb86078565868bd'
                assert index.db.execute('SELECT count(*) FROM sessions WHERE row IS NOT NULL').fetchone()[0]==0
                size=index.database.stat().st_size
                assert size<150*1024*1024, size
                report.update(index_bytes=size,legacy_index_bytes=358129664,session_rows=rows,players=len(hashes),
                    asset_bytes=sum(e['size'] for e in manifest['asset_files'].values()))
            finally:index.close()
            checks.append('all 690103 rows and 5000 player lookups equal the original index; compact index below 150 MiB')
        report['status']='PASS'
    finally:
        (STATE/'observed-storage-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
