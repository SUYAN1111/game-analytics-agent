"""Same-origin loopback API. Blocking work never runs on the ASGI event loop."""
import json
import re
import secrets
from contextlib import asynccontextmanager
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from product_core.paths import ROOT
from web_api.service import Service, APIError


class Turn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=16, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


def create_app(*, port=8765, **settings):
    authority = f'127.0.0.1:{port}'
    origins = {f'http://{authority}', 'http://127.0.0.1:5173'}

    @asynccontextmanager
    async def lifespan(app):
        from web_api.build import verify_build
        await run_in_threadpool(verify_build)
        app.state.service = await run_in_threadpool(Service, **settings)
        try: yield
        finally: await run_in_threadpool(app.state.service.close)

    async def endpoint(request: Request):
        service = request.app.state.service
        owner, path, method = request.state.owner, request.url.path, request.method
        ids = request.path_params
        body = None
        if method == 'POST':
            raw = await request.body()
            if len(raw) > 16384: raise APIError(413, 'body_limit', '请求过大。')
            try:
                def pairs(items):
                    out = {}
                    for k, v in items:
                        if k in out: raise ValueError('duplicate key')
                        out[k] = v
                    return out
                body = json.loads(raw, object_pairs_hook=pairs)
            except (ValueError, UnicodeError): raise APIError(422, 'invalid_request', '需要有效 JSON 请求。')
            if not path.endswith('/turns') and body != {}: raise APIError(422, 'invalid_request', '此接口只接受空 JSON 对象。')
        if path == '/api/health':
            result = await run_in_threadpool(service.health)
        elif path == '/api/sessions':
            result = await run_in_threadpool(service.sessions, owner, method == 'POST')
        elif path.endswith('/delete'):
            result = await run_in_threadpool(service.delete_session, owner, ids['sid'])
            return JSONResponse(result)
        elif path.endswith('/close'):
            result = await run_in_threadpool(service.close_session, owner, ids['sid'])
        elif path.endswith('/cancel'):
            result = await run_in_threadpool(service.cancel, owner, ids['jid'])
        elif path.endswith('/turns'):
            try: turn = Turn.model_validate(body)
            except ValidationError: raise APIError(422, 'invalid_request', '问题需为 1–4000 字符，提交标识需为 16–80 个字母、数字、短横线或下划线；不允许额外字段。')
            if not turn.text.strip(): raise APIError(422, 'invalid_request', '请输入问题。')
            result = await run_in_threadpool(service.submit, owner, ids['sid'], turn.text, turn.idempotency_key)
        elif 'eid' in ids:
            result = await run_in_threadpool(service.evidence, owner, ids['sid'], ids['tid'], ids['eid'])
        elif 'jid' in ids:
            value = request.query_params.get('after_seq', '0')
            if not re.fullmatch(r'\d{1,12}', value): raise APIError(422, 'invalid_request', '无效事件序号。')
            result = await run_in_threadpool(service.job, owner, ids['jid'], int(value))
        else:
            result = await run_in_threadpool(service.session, owner, ids['sid'])
        return JSONResponse(result, status_code=202 if method=='POST' and path != '/api/sessions' else 201 if method=='POST' else 200)

    async def api_error(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message}}, status_code=exc.status)

    async def unexpected(request, exc):
        return JSONResponse({'error': {'code': 'internal_error', 'message': '本地服务发生错误；请查看任务状态或重新启动服务。'}}, status_code=500)

    routes = [Route('/api/health', endpoint), Route('/api/sessions', endpoint, methods=['GET','POST']),
              Route('/api/sessions/{sid}', endpoint), Route('/api/sessions/{sid}/turns', endpoint, methods=['POST']),
              Route('/api/sessions/{sid}/delete', endpoint, methods=['POST']),
              Route('/api/sessions/{sid}/close', endpoint, methods=['POST']), Route('/api/jobs/{jid}', endpoint),
              Route('/api/jobs/{jid}/cancel', endpoint, methods=['POST']),
              Route('/api/sessions/{sid}/turns/{tid}/evidence/{eid}', endpoint)]
    if (ROOT / 'web/dist').exists(): routes.append(Mount('/', StaticFiles(directory=ROOT/'web/dist', html=True)))
    app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={APIError: api_error, Exception: unexpected}, max_body_size=16384)

    async def boundary(request, call_next):
        if request.headers.get('host') != authority:
            return JSONResponse({'error': {'code': 'host', 'message': '只允许本机指定地址。'}}, status_code=403)
        if request.method not in ('GET','HEAD'):
            if request.headers.get('origin') not in origins or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'error': {'code': 'origin', 'message': '请求来源不允许。'}}, status_code=403)
            if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                return JSONResponse({'error': {'code': 'content_type', 'message': '只接受 JSON。'}}, status_code=415)
        cookie = request.cookies.get('web_owner', '')
        fresh = not re.fullmatch(r'[0-9a-f]{64}', cookie)
        request.state.owner = secrets.token_hex(32) if fresh else cookie
        response = await call_next(request)
        if fresh: response.set_cookie('web_owner', request.state.owner, max_age=31536000, httponly=True, samesite='strict')
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=boundary)
    return app
