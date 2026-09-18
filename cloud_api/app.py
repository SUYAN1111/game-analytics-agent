"""Vercel ASGI entry. Work stays inside a streaming request, never fire-and-forget."""
import asyncio
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError
from web_api.app import Turn
from web_api.service import APIError
from cloud_api.service import CloudService
from cloud_api import auth


def create_app(*, test_settings=None):
    settings=test_settings or os.environ
    test=bool(test_settings)
    origin=settings.get('APP_ORIGIN','').rstrip('/')
    secret=settings.get('APP_ACCESS_CODE','')
    access_mode=settings.get('APP_ACCESS_MODE','public')
    public=access_mode=='public'
    url=settings.get('DATABASE_URL','')
    configured=bool(access_mode in ('public','invite') and origin and url and 16<=len(secret)<=128 and (test or settings.get('DEEPSEEK_API_KEY')))
    origins={origin}
    if settings.get('VERCEL_URL'):origins.add('https://'+settings['VERCEL_URL'])
    if not test and (urlsplit(origin).scheme!='https' or urlsplit(origin).path):configured=False
    service=CloudService(url,mode=settings.get('CLOUD_TEST_MODE','offline') if test else 'live') if configured else None

    def error(code,message,status):return JSONResponse({'error':{'code':code,'message':message}},status_code=status,headers={'Cache-Control':'no-store'})

    def browser_owner(request):
        owner=request.cookies.get('web_owner','')
        if not re.fullmatch('[0-9a-f]{64}',owner):return None
        if not public or auth.valid_owner(owner,request.cookies.get('web_owner_signature',''),secret):return owner
        # Keep existing private-mode history when a previously authenticated browser migrates.
        if auth.valid(request.cookies.get('app_access',''),secret):return owner
        return None

    def set_owner(response,owner):
        response.set_cookie('web_owner',owner,httponly=True,secure=not test,samesite='strict',max_age=31536000,path='/')
        if public:
            response.set_cookie('web_owner_signature',auth.owner_signature(owner,secret),httponly=True,
                                secure=not test,samesite='strict',max_age=31536000,path='/')
        return response

    def ensure_owner(request,response):
        # Establish identity before the page makes parallel API requests.
        owner=browser_owner(request)
        if not owner or (public and not auth.valid_owner(owner,request.cookies.get('web_owner_signature',''),secret)):
            set_owner(response,owner or secrets.token_hex(32))
        return response

    async def api(request):
        if not configured:return error('not_configured','云端配置尚未完成，请联系管理员。',503)
        if request.headers.get('host') not in {urlsplit(o).netloc for o in origins}:
            return error('host','请求地址不允许。',403)
        if request.method not in ('GET','HEAD') and request.headers.get('origin') not in origins:
            return error('origin','请求来源不允许。',403)
        if request.headers.get('sec-fetch-site')=='cross-site' and request.method=='POST':
            return error('origin','请求来源不允许。',403)
        try:
            if request.url.path=='/_auth':
                if public:return ensure_owner(request,RedirectResponse('/',status_code=303,headers={'Cache-Control':'no-store'}))
                if request.method=='GET':return HTMLResponse(auth.PAGE)
                raw=await limited_body(request,2048)
                code=parse_qs(raw.decode('utf8')).get('code',[''])[0]
                with service.store.connect() as db:
                    record=db.execute("SELECT * FROM login_limits WHERE key='all'").fetchone()
                    now=time.time()
                    if record and record['expires']>now and record['attempts']>=40:
                        return error('rate_limit','尝试次数过多，请十分钟后再试。',429)
                    count=record['attempts']+1 if record and record['expires']>now else 1
                    expiry=record['expires'] if record and record['expires']>now else now+600
                    db.execute("INSERT INTO login_limits VALUES('all',?,?) ON CONFLICT(key) DO UPDATE SET attempts=EXCLUDED.attempts,expires=EXCLUDED.expires",(count,expiry))
                if not hmac.compare_digest(code.encode(),secret.encode()):return error('access','访问码不正确。',401)
                response=RedirectResponse('/',status_code=303)
                response.set_cookie('app_access',auth.issue(secret),httponly=True,secure=not test,samesite='strict',max_age=86400,path='/')
                return ensure_owner(request,response)
            if not public and not auth.valid(request.cookies.get('app_access',''),secret):
                return error('access','请刷新页面并输入访问码。',401)
            owner=browser_owner(request)
            if public and not owner and request.url.path!='/api/health':
                return error('visitor_required','请刷新页面后重试，并允许此网站保存 Cookie。',401)
            fresh=not owner
            owner=owner or secrets.token_hex(32)
            await run_in_threadpool(service.sweep)
            path,method,ids=request.url.path,request.method,request.path_params
            body=None
            if method=='POST':
                if request.headers.get('content-type','').split(';')[0]!='application/json':return error('content_type','只接受 JSON。',415)
                raw=await limited_body(request,16384)
                def pairs(items):
                    value={}
                    for k,v in items:
                        if k in value:raise ValueError('duplicate JSON key')
                        value[k]=v
                    return value
                body=json.loads(raw,object_pairs_hook=pairs)
                if not path.endswith('/turns') and body!={}:return error('invalid_request','此接口只接受空 JSON。',422)
            if path=='/api/health':value=await run_in_threadpool(service.health)
            elif path=='/api/sessions':value=await run_in_threadpool(service.sessions,owner,method=='POST')
            elif path.endswith('/turns'):
                turn=Turn.model_validate(body)
                if not turn.text.strip():return error('invalid_request','请输入问题。',422)
                from cloud_api.visitors import network_key
                network=network_key(request,secret,vercel=bool(settings.get('VERCEL'))) if public else None
                value=await run_in_threadpool(service.submit,owner,ids['sid'],turn.text,turn.idempotency_key,public_network=network)
            elif path.endswith('/run'):
                claim=await run_in_threadpool(service.claim,owner,ids['jid'])
                if not claim:return JSONResponse({'accepted':False})
                async def stream():
                    task=asyncio.create_task(asyncio.to_thread(service.execute,claim))
                    try:
                        while not task.done():
                            yield b'{"running":true}\n'
                            await asyncio.wait({task},timeout=2)
                        await task
                        yield b'{"finished":true}\n'
                    finally:
                        if not task.done():
                            await asyncio.shield(asyncio.to_thread(service.cancel,owner,ids['jid']))
                            # Request cancellation is recorded; a hard platform termination
                            # is recovered by the durable deadline, without replaying work.
                return StreamingResponse(stream(),media_type='application/x-ndjson',headers={'Cache-Control':'no-store'})
            elif path.endswith('/cancel'):value=await run_in_threadpool(service.cancel,owner,ids['jid'])
            elif path.endswith('/close'):value=await run_in_threadpool(service.close_session,owner,ids['sid'])
            elif path.endswith('/delete'):value=await run_in_threadpool(service.delete_session,owner,ids['sid'])
            elif 'eid' in ids:value=await run_in_threadpool(service.evidence,owner,ids['sid'],ids['tid'],ids['eid'])
            elif 'jid' in ids:
                seq=request.query_params.get('after_seq','0')
                if not re.fullmatch(r'\d{1,12}',seq):return error('invalid_request','无效事件序号。',422)
                value=await run_in_threadpool(service.job,owner,ids['jid'],int(seq))
            else:value=await run_in_threadpool(service.session,owner,ids['sid'])
            response=JSONResponse(value,status_code=201 if path=='/api/sessions' and method=='POST' else 202 if path.endswith('/turns') else 200)
            if fresh or (public and not auth.valid_owner(owner,request.cookies.get('web_owner_signature',''),secret)):
                set_owner(response,owner)
            response.headers['Cache-Control']='no-store'
            return response
        except APIError as exc:return error(exc.code,exc.message,exc.status)
        except (ValueError,UnicodeError,ValidationError):return error('invalid_request','请求内容无效或云端配置未完成。',422)
        except Exception as exc:
            if test: print('Cloud test error:',type(exc).__name__,getattr(exc,'sqlstate',None),flush=True)
            return error('service_unavailable','云端服务暂时不可用，请稍后刷新查看任务状态。',503)

    async def home(request):
        if not configured:return HTMLResponse('<h1>玩家洞察</h1><p>云端配置尚未完成。</p>',status_code=503)
        if not public and not auth.valid(request.cookies.get('app_access',''),secret):return HTMLResponse(auth.PAGE,headers={'Cache-Control':'no-store'})
        from product_core.paths import ROOT
        return ensure_owner(request,HTMLResponse((ROOT/'web/dist/index.html').read_text('utf8'),headers={'Cache-Control':'no-cache'}))

    routes=[Route('/',home),Route('/_auth',api,methods=['GET','POST']),Route('/api/health',api),
        Route('/api/sessions',api,methods=['GET','POST']),Route('/api/sessions/{sid}',api),
        Route('/api/sessions/{sid}/turns',api,methods=['POST']),Route('/api/sessions/{sid}/close',api,methods=['POST']),
        Route('/api/sessions/{sid}/delete',api,methods=['POST']),Route('/api/jobs/{jid}',api),
        Route('/api/jobs/{jid}/run',api,methods=['POST']),Route('/api/jobs/{jid}/cancel',api,methods=['POST']),
        Route('/api/sessions/{sid}/turns/{tid}/evidence/{eid}',api)]
    from product_core.paths import ROOT
    async def access_css(request):return FileResponse(ROOT/'web/dist/access.css',media_type='text/css')
    routes.append(Route('/access.css',access_css))
    for name in ('assets','fonts'):
        if (ROOT/'web/dist'/name).exists():routes.append(Mount('/'+name,StaticFiles(directory=ROOT/'web/dist'/name)))
    app=Starlette(routes=routes,max_body_size=16384)
    app.state.service=service
    return app


async def limited_body(request, limit):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>limit:raise APIError(413,'body_limit','请求过大。')
    return bytes(data)
