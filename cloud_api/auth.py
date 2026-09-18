"""A small invite-code gate for the shared, bounded demonstration budget."""
import hashlib
import hmac
import secrets
import time


def issue(secret):
    payload=f'{int(time.time())+86400}.{secrets.token_hex(16)}'
    return payload+'.'+hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()


def valid(cookie, secret):
    try:
        expiry,nonce,signature=cookie.split('.')
        if len(nonce)!=32 or not int(time.time())<int(expiry)<=int(time.time())+86401:return False
        expected=hmac.new(secret.encode(),f'{expiry}.{nonce}'.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature,expected)
    except (ValueError,AttributeError):return False


PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/access.css"><title>玩家洞察 · 访问验证</title><body><main><span class="brand">玩家洞察</span><h1>开始了解玩家</h1><p>请输入分享者提供的访问码。</p><form method="post" action="/_auth"><label>访问码 <input name="code" type="password" maxlength="128" required autocomplete="current-password" autofocus></label><button type="submit">进入分析 <span aria-hidden="true">↗</span></button></form><small>访问码用于保护共享的模型调用额度。</small></main></body></html>'''
