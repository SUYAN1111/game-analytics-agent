"""Verify temporary/cache ownership survives real, credential-free child hops."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from agent_runtime.common import HostError, clean_environment
from product_core.paths import STATE


def child(depth):
    expected=os.environ['APP_RUNTIME_TMP']
    safe=clean_environment()
    assert safe['APP_RUNTIME_TMP']==expected, 'a child replaced request ownership with its PID'
    assert safe['TEMP']==safe['TMP']==expected
    assert Path(safe['PKG_NATIVE_CACHE_PATH'])==Path(expected)/'native-cache'
    assert Path(safe['XDG_CACHE_HOME'])==Path(expected)/'cache'
    if os.name!='nt':assert safe['HOME']==safe['TMPDIR']==expected
    assert not {'DEEPSEEK_API_KEY','DATABASE_URL','PYTHONPATH','LD_PRELOAD'} & safe.keys()
    cache=Path(safe['PKG_NATIVE_CACHE_PATH'])/str(os.getpid())
    cache.mkdir(parents=True);(cache/'native-library-probe').write_bytes(b'x'*65536)
    if depth:
        subprocess.run([sys.executable,'-B',__file__,'--child',str(depth-1)],
                       env=safe,cwd=ROOT,check=True,timeout=20)


def main():
    STATE.mkdir(parents=True,exist_ok=True)
    checks=[]
    with tempfile.TemporaryDirectory(prefix='runtime-temporary-',dir=STATE) as directory:
        home=Path(directory);scratch=home/'session/temporary'
        legacy=set((STATE/'temporary').glob('*'))
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'offline-test-not-a-key','DATABASE_URL':'not-a-real-database',
                'PKG_NATIVE_CACHE_PATH':str(home/'unowned-cache'),'XDG_CACHE_HOME':str(home/'unowned-cache')}):
            safe=clean_environment(temporary_root=scratch)
        assert not {'DEEPSEEK_API_KEY','DATABASE_URL'} & safe.keys()
        subprocess.run([sys.executable,'-B',__file__,'--child','2'],env=safe,cwd=ROOT,check=True,timeout=30)
        assert len(list((scratch/'native-cache').glob('*/native-library-probe')))==3
        assert not (home/'unowned-cache').exists()
        assert set((STATE/'temporary').glob('*'))==legacy
        checks.append('three actual child processes share request-owned temp and native caches without PID-directory leaks')
        checks.append('ambient model/database credentials and external cache settings are not inherited')
        for bad in (STATE,STATE.parent,ROOT):
            try:clean_environment(temporary_root=bad)
            except HostError as exc:assert exc.code=='environment'
            else:raise AssertionError('unsafe temporary root was accepted')
        checks.append('state root itself and paths outside state are rejected')
    assert not home.exists()
    report={'status':'PASS','checks':checks,'platform':sys.platform,'paid_calls':0}
    (STATE/'runtime-temporary-results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':child(int(sys.argv[2]))
    else:main()
