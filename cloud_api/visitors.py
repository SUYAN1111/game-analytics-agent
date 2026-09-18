"""Durable public admission limits; no schema migration or raw IP storage."""
import hashlib
import hmac
import ipaddress
import time

from web_api.service import APIError

BROWSER_ANALYSES = 10
NETWORK_ANALYSES = 30
NETWORK_SUBMISSIONS = 60
DAY = 86400


def network_key(request, secret, *, vercel=False):
    # Only trust this header behind Vercel's managed edge. Local headers are untrusted.
    raw = request.headers.get('x-vercel-forwarded-for', '') if vercel else (
        request.client.host if request.client else '')
    try:
        address = str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        address = 'unknown'  # One conservative bucket, never a fresh arbitrary value.
    return hmac.new(secret.encode(),('public-network-v1:'+address).encode(),hashlib.sha256).hexdigest()


def admit(db, owner, network, *, analysis):
    """Called inside the same locked transaction that creates the job.

    Any rejection rolls back the job and all counter updates. Completed/cancelled
    jobs and deleted conversations never refund admission. This does not reserve
    model fees: CloudBudget still reserves before each actual model request.
    """
    now = time.time()
    db.execute('DELETE FROM login_limits WHERE key LIKE ? AND expires<=?', ('public:v1:%',now))
    limits = [(f'public:v1:network:{network}:submissions', NETWORK_SUBMISSIONS, 600,
               '提交得有些频繁，请稍后再试。')]
    if analysis:
        limits += [(f'public:v1:browser:{owner}:analysis', BROWSER_ANALYSES, DAY,
                    '本浏览器的分析次数暂时用完了，请明天再来。已有结果仍可查看。'),
                   (f'public:v1:network:{network}:analysis', NETWORK_ANALYSES, DAY,
                    '当前网络的分析次数暂时用完了，请明天再来。已有结果仍可查看。')]
    for key, limit, window, message in limits:
        row = db.execute('SELECT attempts,expires FROM login_limits WHERE key=?', (key,)).fetchone()
        if row and row['attempts'] >= limit:
            raise APIError(429, 'public_limit', message)
        count, expiry = (row['attempts']+1, row['expires']) if row else (1, now+window)
        db.execute('INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET attempts=EXCLUDED.attempts,expires=EXCLUDED.expires',
                   (key, count, expiry))
