"""Offline fault injection into real local sessions; do not use a live key."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from product_core.paths import STATE
from product_core.session import Runtime
from product_core.offline_stub import ModelStub
from product_core.smoke import check, expect_error
from agent_runtime.common import read


def main():
    out=STATE/'task15';out.mkdir(parents=True,exist_ok=True)
    stub=ModelStub(out/'cleanup-provider')
    runtime=Runtime()
    try:
        first=runtime.session(offline_base_url=stub.url)
        second=runtime.session(offline_base_url=stub.url)
        driver=first.host.driver
        with patch.object(driver,'close',side_effect=OSError('offline injected first cleanup failure')):
            failure=expect_error(runtime.close)
        check(first.status=='close_failed' and not first.closed,'failed close reported success')
        check(not (first.directory/'closed.json').exists(),'false successful close record')
        check(first.id in read(runtime.ledger.path)['closed_sessions'],'admission close skipped after driver failure')
        check(second.closed and runtime.coordinator.closed,'other sessions/coordinator skipped')
        check(bool(driver.job.pids()),'fault injection did not retain a real process for retry')
        expect_error(lambda:runtime.session(offline_base_url=stub.url))
        runtime.close();runtime.close();first.close()
        check(first.closed and driver.process.poll() is not None and runtime.status=='closed','retry cleanup failed')
        (out/'lifecycle-results.json').write_text(json.dumps({'status':'PASS','failure_type':failure['type'],
            'checks':['real sessions opened','all cleanup phases attempted','close_failed truthful','no false success file',
                      'other session reclaimed','coordinator closed','new session rejected','cleanup retry reclaims owned process','repeated close stable']},indent=2),encoding='utf-8')
        print('lifecycle failure/retry: PASS')
    finally:
        runtime.close();stub.close()

if __name__=='__main__':main()
