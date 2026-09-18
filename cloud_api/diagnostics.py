"""Redacted server errors and bounded offline reports; no raw configs or tool data."""
import json
import logging
import os
import re
import traceback
from pathlib import Path
from agent_runtime.common import redact


def scrub(value, secrets=()):
    known = tuple(v for k, v in os.environ.items() if v and re.search(
        r'key|secret|token|password|database_url|access_code', k, re.I))
    text = redact(str(value), (*known, *secrets))
    text = re.sub(r'task09-canary-[\w-]+', '[REDACTED]', text)
    text = re.sub(r'(?i)postgres(?:ql)?://[^\s\"\'<>]+', '[REDACTED_DATABASE_URL]', text)
    text = re.sub(r'(?i)(password|auth|access_code)\s*[:=]\s*[^\s,;}]+', r'\1=[REDACTED]', text)
    return text


def exception_record(exc, secrets=(), *, remaining=None, seen=None):
    """Bound nested cleanup errors and chained causes without losing the leaf error."""
    remaining = [12] if remaining is None else remaining
    seen = set() if seen is None else seen
    if remaining[0] <= 0 or id(exc) in seen:
        return {'truncated': True}
    remaining[0] -= 1;seen.add(id(exc))
    record = {'type': type(exc).__name__, 'code': getattr(exc, 'code', None),
              'message': scrub(exc, secrets)[:2000]}
    if isinstance(exc, BaseExceptionGroup):
        children = exc.exceptions
    else:
        cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
        children = [cause] if cause is not None else []
    if children:
        record['causes'] = [exception_record(child, secrets, remaining=remaining, seen=seen)
                            for child in children[:12] if remaining[0] > 0]
    return record


def runtime_context(home, driver=None, *, secrets=()):
    """Only private error logs, never stdout/model answers/configs or tool results."""
    result = {'logs': {}}
    if driver is not None:
        result['driver_exit_code'] = driver.process.poll()
        result['driver_closed'] = driver.closed
    session = Path(home) / 'session'
    for name in ('controller/stderr.log', 'driver_errors.jsonl', 'mcp/stderr.log'):
        path = session / name
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 8000))
                raw = stream.read(8000).decode('utf8', errors='replace')
            if raw:result['logs'][name] = scrub(raw, secrets)[-4000:]
        except OSError:
            pass
    return result


def log_failure(job_id, stage, exc, *, secrets=(), context=None):
    # Private platform logs retain the cause; public job responses stay generic.
    record = {'job_id': job_id, 'stage': stage, **exception_record(exc, secrets)}
    if context is not None:record['runtime'] = context
    logging.getLogger('cloud_api').error('analysis_failed %s', json.dumps(record, ensure_ascii=False))


def failure_details(home, exc, stage, *, secrets=()):
    report = {'stage': stage, 'type': type(exc).__name__, 'code': getattr(exc, 'code', None),
              'message': scrub(exc, secrets)[:4000],
              'traceback': scrub(''.join(traceback.format_exception(exc)), secrets)[-12000:], 'logs': {}}
    session = Path(home) / 'session'
    for name in ('controller/stderr.log', 'driver_errors.jsonl', 'mcp/stderr.log', 'phase.jsonl', 'plugin.jsonl'):
        path = session / name
        if path.is_file():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 16000))
                report['logs'][name] = scrub(stream.read().decode('utf8', errors='replace'), secrets)
    return report
