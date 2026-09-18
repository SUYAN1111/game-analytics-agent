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
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if (ROOT/'_core_vendor').exists():sys.path.insert(0,str(ROOT/'_core_vendor'))
from agent_runtime.common import HostError,clean_environment
from product_core import release
from product_core.paths import ASSETS,STATE
from cloud_api.asset_bundle import build_archive,install_archive,ARCHIVE_NAME


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
                if builder_omits('assets/'+name):continue
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
                message=rejected('legacy loose assets reproduce the production missing public data failure',assets=True)
                assert 'association/public/discovery_V1_V3.json' in message
                message=rejected('full build verification still rejects omitted inputs',full=True)
                assert 'missing/changed .gitignore' in message
                for label,relative in [('changed runtime code is rejected','cloud_api/service.py'),
                                       ('changed knowledge source is rejected','business_knowledge/cards/K01.json')]:
                    path=bundle/relative;original=path.read_bytes()
                    path.write_bytes(original+b'\n')
                    rejected(label)
                    path.write_bytes(original)
                manifest=bundle/'product_release.json';original=manifest.read_bytes()
                manifest.write_text('{}',encoding='utf8')
                rejected('source anchor still rejects a replaced release manifest')
                manifest.write_bytes(original)

            # The new function ships one archive and no loose assets directory.
            assert data.resolve().is_relative_to(root.resolve()) and data.name=='assets'
            shutil.rmtree(data)
            archive=build_archive(bundle,ASSETS)
            assert archive.name==ARCHIVE_NAME and not builder_omits(archive.name)
            data=install_archive(bundle,root/'installed-assets')
            with patch.object(release,'ROOT',bundle),patch.object(release,'ASSETS',data):
                release.verify()
                asset=data/'segmentation/model.json';original=asset.read_bytes()
                asset.unlink()
                assert 'segmentation/model.json' in rejected('missing installed analysis model is rejected',assets=True)
                asset.write_bytes(original+b'\n')
                assert 'segmentation/model.json' in rejected('changed installed analysis model is rejected',assets=True)
                asset.write_bytes(original)
            checks.append('all 60 assets including four public data files survive platform filtering in the archive')
            original_archive=archive.read_bytes()

            def bad_archive(label, edit):
                import io
                with zipfile.ZipFile(io.BytesIO(original_archive)) as source,zipfile.ZipFile(archive,'w') as output:
                    for info in source.infolist():
                        value=edit(info.filename,source.read(info))
                        if value is not None:output.writestr(info,value)
                cache=root/('invalid-'+str(len(checks)))
                try:install_archive(bundle,cache)
                except HostError:pass
                else:raise AssertionError('Unexpectedly accepted: '+label)
                assert not (cache/installed['asset_set_id']).exists(), 'failed install must not publish partial data'
                checks.append(label)
                archive.write_bytes(original_archive)

            bad_archive('archive missing public data is rejected before publishing',
                        lambda name,value:None if name=='association/public/discovery_V1_V3.json' else value)
            bad_archive('archive with changed public data is rejected before publishing',
                        lambda name,value:b'X'+value[1:] if name=='association/public/discovery_V1_V3.json' else value)
            with zipfile.ZipFile(archive,'a') as output:output.writestr('../escape.json','{}')
            try:install_archive(bundle,root/'invalid-path')
            except HostError:checks.append('unexpected traversal entries are rejected')
            else:raise AssertionError('Unsafe archive accepted')
            archive.write_bytes(original_archive)
            from concurrent.futures import ThreadPoolExecutor
            with patch('cloud_api.asset_bundle.zipfile.ZipFile',wraps=zipfile.ZipFile) as opened:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    paths=list(pool.map(lambda _:install_archive(bundle,root/'concurrent-cache'),range(2)))
                assert opened.call_count==1, 'concurrent cold starts must unpack only one copy'
            assert paths[0]==paths[1]
            assert install_archive(bundle,root/'concurrent-cache')==paths[0]
            checks.append('concurrent cold starts and verified warm-cache reuse retain a complete asset set')
            process_cache=root/'process-cache'
            code="from cloud_api.asset_bundle import install_archive; import sys; print(install_archive(sys.argv[1],sys.argv[2]))"
            processes=[subprocess.Popen([sys.executable,'-B','-c',code,str(bundle),str(process_cache)],
                        cwd=ROOT,env=clean_environment(),stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
            peak_stages=0;started=time.monotonic()
            try:
                while any(p.poll() is None for p in processes):
                    peak_stages=max(peak_stages,len(list(process_cache.glob('unpack-*'))))
                    assert time.monotonic()-started<90, 'concurrent asset installer timed out'
                    time.sleep(.01)
                for process in processes:
                    stdout,stderr=process.communicate()
                    assert process.returncode==0,stderr.decode('utf8','replace')
                assert peak_stages==1, 'independent workers allocated duplicate staging trees'
            finally:
                for process in processes:
                    if process.poll() is None:process.kill()
                    process.communicate()
            checks.append('independent worker processes share one extraction and cannot double asset staging space')
            damaged=paths[0]/'association/public/discovery_V1_V3.json'
            damaged.write_bytes(b'corrupted')
            try:install_archive(bundle,root/'concurrent-cache')
            except HostError:checks.append('corrupted warm assets are rejected rather than silently trusted')
            else:raise AssertionError('Corrupted cache accepted')

            code='''
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
vendor=Path.cwd()/'_core_vendor'
if vendor.is_dir():sys.path.insert(0,str(vendor))
temporary=Path.cwd().parent/'entrypoint-tmp';temporary.mkdir()
tempfile.tempdir=str(temporary)
os.environ.update(VERCEL='1',APP_ORIGIN='https://bundle-test.invalid',
                  APP_ACCESS_CODE='local-signing-secret-not-published',
                  DATABASE_URL='postgresql://unused@127.0.0.1:1/unused',
                  DEEPSEEK_API_KEY='local-placeholder-never-used')
assert not (Path.cwd()/'assets').exists()
import api.index
assert api.index.app.state.service.mode=='live'
from product_core.paths import ASSETS,STATE
from product_core.release import verify
from product_core.budget import Coordinator,GlobalBudget
from task13_runtime.host import Host
assert ASSETS==Path(os.environ['APP_ASSET_DIR']) and ASSETS.is_relative_to(temporary)
assert STATE==temporary/'player-agent' and not ASSETS.is_relative_to(STATE)
verify()
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
            checks.append('actual Vercel API entrypoint installs assets before imports and initializes the live Host without model calls')

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
