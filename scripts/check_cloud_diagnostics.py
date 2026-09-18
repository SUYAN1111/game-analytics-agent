"""A failed offline startup still yields a redacted report and generic public DTO."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import check_cloud_runtime
from agent_runtime.common import HostError
from cloud_api.service import CloudService
from product_core.paths import STATE
from task13_runtime.host import Host


def main():
    url = os.environ['CLOUD_TEST_DATABASE_URL']
    if urlsplit(url).hostname not in ('127.0.0.1', 'localhost') or os.environ.get('DEEPSEEK_API_KEY'):
        raise SystemExit('requires local disposable PostgreSQL and no live model key')
    service = CloudService(url, mode='offline')
    with service.store.connect() as db:
        assert not db.execute("SELECT id FROM sessions WHERE owner='runtime-check'").fetchone(), 'use a clean runtime test database'
    private = 'diagnostic-access-code-never-display'
    spawned = []

    def fail(host):
        spawned.append(host.directory.parent)
        controller = host.directory / 'controller'
        controller.mkdir()
        (controller / 'stderr.log').write_text('startup probe ' + host.canary + ' ' + private + ' ' + url, 'utf8')
        raise HostError('diagnostic_probe', 'injected startup failure ' + host.canary + ' ' + private + ' ' + url)

    with patch.object(Host, 'open', fail), patch.dict(os.environ, {'APP_ACCESS_CODE': private}), contextlib.redirect_stdout(io.StringIO()):
        try:
            check_cloud_runtime.main()
        except AssertionError:
            pass
        else:
            raise AssertionError('injected startup failure must fail acceptance')
    path = STATE / 'cloud-runtime-results.json'
    raw = path.read_text('utf8')
    value = json.loads(raw)
    assert value['status'] == 'FAIL' and value['paid_calls'] == 0
    failure = value['cases'][0]['diagnostics'][0]
    assert failure['stage'] == 'host_open' and failure['code'] == 'diagnostic_probe'
    assert 'controller/stderr.log' in failure['logs']
    assert '[REDACTED]' in raw and private not in raw and url not in raw and 'task09-canary-' not in raw
    assert spawned and not spawned[0].exists(), 'temporary runtime should still be cleaned'
    with service.store.connect() as db:
        rows = db.execute("SELECT id FROM sessions WHERE owner='runtime-check'").fetchall()
    for row in rows:
        public = service.session('runtime-check', row['id'])
        assert 'diagnostic_probe' not in json.dumps(public), 'internal details must not enter public DTOs'
        service.delete_session('runtime-check', row['id'])
    assert not service.store.ledger()['attempts'], 'startup failure must not call a model'
    path.replace(STATE / 'cloud-diagnostics-probe.json')
    print('Offline failure artifact, redaction, cleanup and public error isolation: PASS')


if __name__ == '__main__':
    main()
