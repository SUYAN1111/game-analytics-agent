"""Prove both dependency trees load in fresh interpreters with no site/PYTHONPATH."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_runtime.common import clean_environment
from cloud_api.core_bootstrap import MODULES
from cloud_api.diagnostics import scrub
from product_core.paths import STATE


def main():
    if os.environ.get('DEEPSEEK_API_KEY'):
        raise SystemExit('remove live credentials before offline tests')
    report = {'status': 'FAIL', 'platform': sys.platform, 'paid_calls': 0, 'checks': []}
    STATE.mkdir(parents=True, exist_ok=True)
    env = clean_environment()
    assert not any(key in env for key in ('PYTHONPATH', 'DEEPSEEK_API_KEY', 'DATABASE_URL', 'LD_PRELOAD'))

    def run(name, args, data=None):
        result = subprocess.run([sys.executable, '-S', '-m', *args], input=data,
            cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf8', timeout=45)
        item = {'check': name, 'returncode': result.returncode}
        report['checks'].append(item)
        if result.returncode:
            item['stderr'] = scrub(result.stderr)[-16000:]
            raise RuntimeError('child bootstrap failed: ' + name + '\n' + item['stderr'])
        return result.stdout

    try:
        core = json.loads(run('core imports', ['cloud_api.core_bootstrap', '--check']))
        assert core['packages']['pydantic'] == '2.13.4' and core['no_site'] and not core['credential_present']
        dsh = json.loads(run('SDK imports', ['cloud_api.dsh_bootstrap', '--environment-only'], '{}\n'))
        assert dsh['packages']['pydantic'] == '2.12.5'
        assert not any(name.lower().startswith('mcp') for name in dsh['packages'])
        for module in MODULES:
            run(module, ['cloud_api.core_bootstrap', module, '--help'])
        report.update(status='PASS', core_pydantic='2.13.4', sdk_pydantic='2.12.5')
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': scrub(exc)[:4000]}
        raise
    finally:
        (STATE / 'cloud-bootstrap-results.json').write_text(json.dumps(report, indent=2), 'utf8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
