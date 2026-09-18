"""Linux/Windows cloud adapter test with real DSH+MCP and a local model stub."""
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
if (ROOT/'_core_vendor').exists():sys.path.insert(0,str(ROOT/'_core_vendor'))
local=ROOT/'state/cloud-test/python'
if local.exists():sys.path.insert(0,str(local))
archive_directory=None
if os.environ.get('CLOUD_TEST_ASSET_ARCHIVE')=='1':
    import tempfile
    from cloud_api.asset_bundle import install_archive
    archive_directory=tempfile.TemporaryDirectory(prefix='cloud-assets-')
    # Configure before CloudService or any runtime path module is imported.
    os.environ['APP_ASSET_DIR']=str(install_archive(ROOT,Path(archive_directory.name)))
from cloud_api.service import CloudService
from cloud_api.diagnostics import scrub

def main():
    url=os.environ['CLOUD_TEST_DATABASE_URL']
    if urlsplit(url).hostname not in ('127.0.0.1','localhost'):raise SystemExit('tests require a local disposable PostgreSQL')
    if os.environ.get('DEEPSEEK_API_KEY'):raise SystemExit('remove live credentials before offline tests')
    service=CloudService(url,mode='offline');results=[]
    cases=[('compare','比较两个版本的剧情开始情况'),('knowledge','剧情开始情况是怎么算出来的？'),
           ('prediction','查看示例数据中的剧情参与预测'),('clusters','不同玩家的游戏习惯有什么区别？'),
           ('association','玩休闲小游戏的玩家，也会玩协作玩法吗？')]
    from product_core.paths import STATE
    report={'status':'FAIL','platform':sys.platform,'cases':results,'paid_calls':0,
            'assets_from_archive':archive_directory is not None}
    STATE.mkdir(parents=True,exist_ok=True)
    report_path=Path(os.environ.get('CLOUD_TEST_REPORT_PATH',STATE/'cloud-runtime-results.json'))
    report_path.parent.mkdir(parents=True,exist_ok=True)
    done=threading.Event();peak={'files_bytes':0,'native_cache_bytes':0}
    existing={p for p in STATE.glob('cloud-*') if p.is_dir()}
    existing_temporary=set((STATE/'temporary').glob('*'))
    monitor_errors=[]
    def sample_storage():
        size=cache_size=0;largest=[]
        # A developer's STATE may also contain old reports, fixtures and local
        # browser history. Measure only assets and scratch owned by this run.
        roots=([Path(archive_directory.name)] if archive_directory else [])
        roots += [p for p in STATE.glob('cloud-*') if p.is_dir() and p not in existing]
        roots += [p for p in (STATE/'temporary').glob('*') if p not in existing_temporary]
        for root in roots:
            for path in root.rglob('*'):
                try:
                    if path.is_file():
                        value=path.stat()
                        allocated=value.st_blocks*512 if hasattr(value,'st_blocks') else ((value.st_size+4095)//4096)*4096
                        size+=allocated
                        if 'native-cache' in path.parts:cache_size+=allocated
                        if allocated>=1024*1024:largest.append((allocated,str(path.relative_to(root))))
                except FileNotFoundError:pass  # Owned scratch may be deleted during sampling.
        peak['files_bytes']=max(peak['files_bytes'],size)
        peak['native_cache_bytes']=max(peak['native_cache_bytes'],cache_size)
        current={'files_bytes':size,'native_cache_bytes':cache_size}
        if limit:
            used=shutil.disk_usage(tempfile.gettempdir()).used
            peak['filesystem_used_bytes']=max(peak.get('filesystem_used_bytes',0),used)
            current['filesystem_used_bytes']=used
        current['largest_files']=[{'bytes':n,'path':p} for n,p in sorted(largest,reverse=True)[:6]]
        return current
    def monitor():
        try:
            while not done.wait(.05):sample_storage()
        except Exception as exc:monitor_errors.append(str(exc))
    limit=os.environ.get('CLOUD_TEST_DISK_LIMIT')
    if limit:
        assert shutil.disk_usage(tempfile.gettempdir()).total<=int(limit), 'test must run on a genuinely limited filesystem'
        report['filesystem_capacity_bytes']=shutil.disk_usage(tempfile.gettempdir()).total
    baseline=sample_storage();report['storage_baseline']=baseline
    watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
    try:
        # Repeat the disk-heavy path on the warm instance, not just one cold job.
        for name,text in cases+[('compare_again',cases[0][1])]:
            case={'case':name,'status':'running','diagnostics':[]};results.append(case)
            sid=service.sessions('runtime-check',True)['id']
            job=service.submit('runtime-check',sid,text,'cloud-runtime-'+name)
            claim=service.claim('runtime-check',job['id']);assert claim
            service.execute(claim,diagnostics=case['diagnostics'])
            value=service.job('runtime-check',job['id'])
            case.update(status=value['status'],error=value['error'],evidence=len(value['evidence']))
            case['storage_after']=sample_storage()
            print(json.dumps(case,ensure_ascii=False),flush=True)
            assert value['status']=='succeeded' and value['evidence'],case
            fresh=CloudService(url,mode='offline');assert fresh.session('runtime-check',sid)['jobs'][0]['answer']==value['answer']
            fresh.delete_session('runtime-check',sid)
            assert not [p for p in STATE.glob('cloud-*') if p.is_dir() and p not in existing], 'completed request left scratch directories behind'
            assert not [p for p in (STATE/'temporary').glob('*') if p not in existing_temporary], 'descendants leaked PID-based temporary directories'
            assert case['storage_after']['native_cache_bytes']==0, 'native runtime cache survived request cleanup'
            if limit:
                assert case['storage_after']['filesystem_used_bytes']<=baseline['filesystem_used_bytes']+1024*1024, 'warm requests retain disk space after cleanup'
            # Keep completed results outside the quota in Linux CI even if a
            # later request consumes every remaining byte of the test volume.
            report['peak_storage']=dict(peak)
            report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        assert not monitor_errors, monitor_errors
        assert peak['files_bytes']<450*1024*1024, peak
        report['status']='PASS'
    except Exception as exc:
        report['error']={'type':type(exc).__name__,'message':scrub(exc)[:4000]}
        if results and results[-1]['status']=='running':results[-1]['status']='failed'
        raise
    finally:
        done.set();watcher.join(5);sample_storage()
        report['peak_storage']=peak
        try:report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        finally:
            if archive_directory:archive_directory.cleanup()
if __name__=='__main__':main()
