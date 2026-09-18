"""Linux/Windows cloud adapter test with real DSH+MCP and a local model stub."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
if (ROOT/'_core_vendor').exists():sys.path.insert(0,str(ROOT/'_core_vendor'))
local=ROOT/'state/cloud-test/python'
if local.exists():sys.path.insert(0,str(local))
from cloud_api.service import CloudService

def main():
    url=os.environ['CLOUD_TEST_DATABASE_URL']
    if '127.0.0.1' not in url and 'localhost' not in url:raise SystemExit('tests require a local disposable PostgreSQL')
    if os.environ.get('DEEPSEEK_API_KEY'):raise SystemExit('remove live credentials before offline tests')
    service=CloudService(url,mode='offline');results=[]
    cases=[('compare','比较两个版本的剧情开始情况'),('knowledge','剧情开始情况是怎么算出来的？'),
           ('prediction','查看示例数据中的剧情参与预测'),('clusters','不同玩家的游戏习惯有什么区别？'),
           ('association','玩休闲小游戏的玩家，也会玩协作玩法吗？')]
    for name,text in cases:
        sid=service.sessions('runtime-check',True)['id']
        job=service.submit('runtime-check',sid,text,'cloud-runtime-'+name)
        claim=service.claim('runtime-check',job['id']);assert claim
        service.execute(claim)
        value=service.job('runtime-check',job['id'])
        results.append({'case':name,'status':value['status'],'error':value['error'],'evidence':len(value['evidence'])})
        print(json.dumps(results[-1]),flush=True)
        assert value['status']=='succeeded' and value['evidence'],results[-1]
        fresh=CloudService(url,mode='offline');assert fresh.session('runtime-check',sid)['jobs'][0]['answer']==value['answer']
        fresh.delete_session('runtime-check',sid)
    from product_core.paths import STATE
    (STATE/'cloud-runtime-results.json').write_text(json.dumps({'status':'PASS','platform':sys.platform,'cases':results,'paid_calls':0},indent=2),'utf8')
if __name__=='__main__':main()
