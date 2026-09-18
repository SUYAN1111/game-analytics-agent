"""Linux/Windows cloud adapter test with real DSH+MCP and a local model stub."""
import json
import os
import sys
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
    try:
        for name,text in cases:
            case={'case':name,'status':'running','diagnostics':[]};results.append(case)
            sid=service.sessions('runtime-check',True)['id']
            job=service.submit('runtime-check',sid,text,'cloud-runtime-'+name)
            claim=service.claim('runtime-check',job['id']);assert claim
            service.execute(claim,diagnostics=case['diagnostics'])
            value=service.job('runtime-check',job['id'])
            case.update(status=value['status'],error=value['error'],evidence=len(value['evidence']))
            print(json.dumps(case,ensure_ascii=False),flush=True)
            assert value['status']=='succeeded' and value['evidence'],case
            fresh=CloudService(url,mode='offline');assert fresh.session('runtime-check',sid)['jobs'][0]['answer']==value['answer']
            fresh.delete_session('runtime-check',sid)
        report['status']='PASS'
    except Exception as exc:
        report['error']={'type':type(exc).__name__,'message':scrub(exc)[:4000]}
        if results and results[-1]['status']=='running':results[-1]['status']='failed'
        raise
    finally:
        (STATE/'cloud-runtime-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        if archive_directory:archive_directory.cleanup()
if __name__=='__main__':main()
