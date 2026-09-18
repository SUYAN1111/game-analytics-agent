"""Exercise the installed runtime after Vercel's documented Python exclusions.

Copies only sealed source/assets, never .env, local history or credentials. Uses
a disposable tree and a live-mode Host without opening DSH or requesting a model.
"""
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if (ROOT/'_core_vendor').exists():sys.path.insert(0,str(ROOT/'_core_vendor'))
from agent_runtime.common import HostError,clean_environment
from product_core import release
from product_core.paths import ASSETS,STATE


def builder_omits(name):
    # Independent fixture from Vercel packages/python/src/index.ts predefinedExcludes:
    # .gitignore, **/public/**, **/package-lock.json, **/yarn.lock, **/pnpm-lock.yaml.
    parts=Path(name).parts
    return (name=='.gitignore' or 'public' in parts[:-1] or
            parts[-1] in ('package-lock.json','yarn.lock','pnpm-lock.yaml'))


def main():
    installed=release.verify(include_build_sources=True)
    report={'status':'FAIL','checks':[],'paid_calls':0}
    STATE.mkdir(parents=True,exist_ok=True)
    checks=report['checks']
    try:
        with tempfile.TemporaryDirectory(prefix='bundle-',dir=STATE) as directory:
            root=Path(directory);bundle=root/'app';data=bundle/'assets'
            omitted=[name for name in installed['source_files'] if builder_omits(name)]
            report['omitted_build_files']=len(omitted)
            assert '.gitignore' in omitted and 'web/package-lock.json' in omitted
            for name in [*installed['source_files'],'product_release.json','product_core/_release_anchor.py']:
                if name in omitted:continue
                target=bundle/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/name,target)
            for name in installed['asset_files']:
                target=data/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ASSETS/name,target)

            def rejected(label, *, full=False, assets=False):
                try:release.verify(assets,include_build_sources=full)
                except HostError as exc:
                    assert exc.code=='asset_integrity'
                    checks.append(label)
                    return str(exc)
                raise AssertionError('Unexpectedly accepted: '+label)

            with patch.object(release,'ROOT',bundle),patch.object(release,'ASSETS',data):
                release.verify()
                checks.append('runtime verifies all analysis source/assets after platform build-only exclusions')
                message=rejected('full build verification still rejects omitted inputs',full=True)
                assert 'missing/changed .gitignore' in message
                for label,relative in [('changed runtime code is rejected','cloud_api/service.py'),
                                       ('changed knowledge source is rejected','business_knowledge/cards/K01.json')]:
                    path=bundle/relative;original=path.read_bytes()
                    path.write_bytes(original+b'\n')
                    rejected(label)
                    path.write_bytes(original)
                asset=data/'segmentation/model.json';original=asset.read_bytes()
                asset.unlink()
                rejected('missing analysis model is rejected',assets=True)
                asset.write_bytes(original+b'\n')
                rejected('changed analysis model is rejected',assets=True)
                asset.write_bytes(original)
                manifest=bundle/'product_release.json';original=manifest.read_bytes()
                manifest.write_text('{}',encoding='utf8')
                rejected('source anchor still rejects a replaced release manifest')
                manifest.write_bytes(original)

            code='''
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
vendor=Path.cwd()/'_core_vendor'
if vendor.is_dir():sys.path.insert(0,str(vendor))
from product_core.paths import ASSETS,STATE
from product_core.release import verify
from product_core.budget import Coordinator,GlobalBudget
from task13_runtime.host import Host
ledger=GlobalBudget(STATE/'budget.json',limit=1)
coordinator=Coordinator(ledger,verify)
host=None
try:
    host=Host(STATE/'session',association_asset=ASSETS/'association',
              admission=coordinator.capability('bundle-test'),condition='H0',
              mode='live',budget_file=ledger.path)
    host.verify_frozen_asset()
    assert host.mode=='live' and host.driver is None
finally:
    if host:host.close()
    coordinator.close()
assert not json.loads(ledger.path.read_text())['attempts']
print('Packaged live-mode Host initialized; model calls: 0')
'''
            env=clean_environment()
            env.update(APP_ASSET_DIR=str(data),APP_STATE_DIR=str(root/'run'),APP_DEBUG='0')
            # Installed dependencies stay outside the fixture; only package modules
            # are added, never the original app source, so missing files cannot fall back.
            bootstrap="import sys; sys.path.insert(0,"+repr(str(ROOT/'_core_vendor'))+")\n" if (ROOT/'_core_vendor').is_dir() else ''
            child=subprocess.run([sys.executable,'-B','-c',bootstrap+code],cwd=bundle,env=env,
                                 text=True,encoding='utf8',capture_output=True,timeout=90)
            if child.returncode:
                from cloud_api.diagnostics import scrub
                raise AssertionError('Packaged Host failed: '+scrub(child.stderr)[-4000:])
            assert 'model calls: 0' in child.stdout
            checks.append('live-mode Host loads real frozen models and knowledge from the packaged tree without API calls')

        from cloud_api.diagnostics import log_failure
        stream=io.StringIO();handler=logging.StreamHandler(stream)
        logger=logging.getLogger('cloud_api');logger.addHandler(handler)
        before=logger.propagate;logger.propagate=False
        secret='test-key-never-publish';url='postgresql://user:test-password@localhost/test'
        try:
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':secret,'DATABASE_URL':url}):
                log_failure('bundle-test-job','prepare',HostError('asset_integrity',
                    'missing/changed .gitignore '+secret+' '+url+' task09-canary-probe'))
        finally:
            logger.removeHandler(handler);logger.propagate=before
        logs=stream.getvalue()
        assert 'bundle-test-job' in logs and 'missing/changed .gitignore' in logs
        assert secret not in logs and url not in logs and 'task09-canary-' not in logs
        checks.append('private runtime logs identify the failed job and file without credentials or canaries')
        report['status']='PASS'
    except Exception as exc:
        from cloud_api.diagnostics import scrub
        report['error']={'type':type(exc).__name__,'message':scrub(exc)[:4000]}
        raise
    finally:
        (STATE/'cloud-bundle-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
