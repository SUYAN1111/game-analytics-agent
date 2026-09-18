"""Reproduce driver/cleanup/watch failures without paid requests or production DB."""
import contextlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
for directory in (ROOT/'_core_vendor',ROOT/'state/cloud-test/python'):
    if directory.exists():sys.path.insert(0,str(directory))
from agent_runtime.common import HostError,clean_environment
from agent_runtime.processes import DriverProcess
from cloud_api.diagnostics import exception_record,runtime_context
from cloud_api.service import CloudService
from product_core.paths import STATE
from product_core.budget import Coordinator
from product_core.offline_stub import ModelStub
from task13_runtime.host import Host


def main():
    url=os.environ['CLOUD_TEST_DATABASE_URL']
    if urlsplit(url).hostname not in ('127.0.0.1','localhost') or os.environ.get('DEEPSEEK_API_KEY'):
        raise SystemExit('Requires disposable local PostgreSQL and no live model key')
    checks=[];report={'status':'FAIL','checks':checks,'paid_calls':0,'platform':sys.platform}
    STATE.mkdir(parents=True,exist_ok=True)
    try:
        # A real child exit must carry its observed return code, not only EOF.
        with tempfile.TemporaryDirectory(dir=STATE) as temporary:
            home=Path(temporary)
            driver=DriverProcess([sys.executable,'-B','-c',
                "import sys; sys.stdin.readline(); print('exit probe',file=sys.stderr,flush=True); sys.exit(23)"],
                ROOT,clean_environment(),home/'session/controller')
            try:
                driver.send({})
                driver.process.wait(10)
                try:driver.receive(5)
                except HostError as exc:
                    assert exc.code=='driver_exit' and 'exit_code=23' in str(exc)
                else:raise AssertionError('Unexpected completed response')
                driver.stderr_thread.join(2)
                context=runtime_context(home,driver)
                assert context['driver_exit_code']==23
                assert 'exit probe' in context['logs']['controller/stderr.log']
            finally:driver.close()
        checks.append('real child EOF includes the pre-cleanup exit code and private stderr')

        secret='cleanup-private-value-never-publish'
        nested=ExceptionGroup('outer',[ExceptionGroup('inner',[HostError('cancel','failure '+secret)])])
        record=exception_record(nested,(secret,))
        assert record['causes'][0]['causes'][0]['code']=='cancel' and secret not in json.dumps(record)
        checks.append('nested cleanup exceptions expose redacted leaf causes')

        service=CloudService(url,mode='offline')
        owner='cleanup-check';created=[]
        before=service.store.ledger()
        coordinator_close,stub_close=Coordinator.close,ModelStub.close
        closed=[];homes=[];stopped=threading.Event()
        stream=io.StringIO();handler=logging.StreamHandler(stream)
        logger=logging.getLogger('cloud_api');logger.addHandler(handler)

        def close_coordinator(value):
            coordinator_close(value);closed.append('coordinator')

        def close_stub(value):
            stub_close(value);closed.append('stub')

        class FailedDriver:
            closed=False
            class Process:
                @staticmethod
                def poll():return -9
            process=Process()
            def close(self):
                stopped.set()
                raise HostError('cancel','owned descendants probe '+secret)

        def open_host(host):
            homes.append(host.directory.parent)
            host.driver=FailedDriver()
            directory=host.directory/'controller';directory.mkdir()
            (directory/'stderr.log').write_text('driver stderr '+host.canary+' '+secret+' '+url,'utf8')
            (host.directory/'config-private-probe.json').write_text('DO_NOT_LOG_CONFIG','utf8')

        def fail_turn(host,*args,**kwargs):
            raise HostError('driver_exit','DSH exit probe '+secret)

        def execute_case(name,turn):
            sid=service.sessions(owner,True)['id'];created.append(sid)
            job=service.submit(owner,sid,'比较两个版本的剧情开始情况','cleanup-check-'+name)
            claim=service.claim(owner,job['id']);assert claim
            diagnostics=[]
            with patch.object(Host,'open',open_host),patch.object(Host,'turn',turn),\
                 patch.object(Coordinator,'close',close_coordinator),patch.object(ModelStub,'close',close_stub),\
                 patch.dict(os.environ,{'APP_ACCESS_CODE':secret}):
                service.execute(claim,diagnostics=diagnostics)
            return sid,job,diagnostics

        try:
            sid,job,diagnostics=execute_case('driver',fail_turn)
            value=service.job(owner,job['id'])
            assert value['status']=='close_failed' and not value['answer']
            assert service.session(owner,sid)['status']=='closing'
            assert '结束对话' not in value['error']['message']
            assert [r['stage'] for r in diagnostics]==['analysis','cleanup_host']
            assert closed==['coordinator','stub'],closed
            logs=[json.loads(line.split('analysis_failed ',1)[1]) for line in stream.getvalue().splitlines()]
            assert [r['stage'] for r in logs]==['analysis','cleanup_host']
            assert logs[0]['code']=='driver_exit' and logs[0]['runtime']['driver_exit_code']==-9
            assert logs[0]['runtime']['stop_reasons']==[]
            assert logs[1]['causes'][0]['code']=='cancel'
            assert secret not in stream.getvalue() and url not in stream.getvalue()
            assert 'task09-canary-' not in stream.getvalue() and 'DO_NOT_LOG_CONFIG' not in stream.getvalue()
            assert 'DSH exit probe' not in json.dumps(value) and 'stderr' not in json.dumps(value)
            checks.append('primary failure and cleanup failure are separately logged; public response stays generic')
            checks.append('coordinator and stub close even when host cleanup fails')
            assert service.close_session(owner,sid)['status']=='closing'
            with service.store.connect() as db:
                assert not db.execute('SELECT finished FROM executions WHERE job_id=?',(job['id'],)).fetchone()[0]
                db.execute('UPDATE executions SET deadline=? WHERE job_id=?',(time.time()-1,job['id']))
            service.sweep()
            assert service.job(owner,job['id'])['status']=='interrupted'
            assert service.claim(owner,job['id']) is None
            service.delete_session(owner,sid)
            checks.append('close does not falsely finish an unresolved execution; expiry interrupts without replay')

            # Reproduce an automatic stop from a failed DB watcher, with no user cancel.
            stream.seek(0);stream.truncate(0);stopped.clear()
            original_connect=service.store.connect
            @contextlib.contextmanager
            def watch_database_failure():
                if threading.current_thread().name.startswith('cloud-watch-'):
                    raise OSError('watch database probe '+url)
                with original_connect() as db:yield db
            def await_watch(host,*args,**kwargs):
                assert stopped.wait(8),'watcher should request host shutdown'
                raise HostError('driver_exit','watch closed driver')
            with patch.object(service.store,'connect',watch_database_failure):
                sid,job,diagnostics=execute_case('watch',await_watch)
            logs=[json.loads(line.split('analysis_failed ',1)[1]) for line in stream.getvalue().splitlines()]
            stages=[r['stage'] for r in logs]
            assert 'watch' in stages and 'watch_cleanup' in stages and 'analysis' in stages and 'cleanup_host' in stages
            assert 'failed' in next(r for r in logs if r['stage']=='analysis')['runtime']['stop_reasons']
            assert url not in stream.getvalue()
            checks.append('automatic watcher failure is logged before its downstream driver exit')
            with service.store.connect() as db:
                db.execute('UPDATE executions SET deadline=? WHERE job_id=?',(time.time()-1,job['id']))
            service.sweep();service.delete_session(owner,sid)
            after=service.store.ledger()
            assert before['attempts']==after['attempts'] and before['limit_cny']==after['limit_cny']
            checks.append('failure tests make no model reservations and do not change budget limits')
        finally:
            logger.removeHandler(handler);handler.close()
            import shutil
            for home in homes:
                if home.exists() and home.resolve().parent==STATE.resolve() and home.name.startswith('cloud-'):
                    shutil.rmtree(home)
        report['status']='PASS'
    finally:
        (STATE/'cloud-cleanup-results.json').write_text(json.dumps(report,indent=2),'utf8')
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
