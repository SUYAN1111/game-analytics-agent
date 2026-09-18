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


def log_failure(job_id, stage, exc, *, secrets=()):
    # Private platform logs retain the cause; public job responses stay generic.
    record = {'job_id': job_id, 'stage': stage, 'type': type(exc).__name__,
              'code': getattr(exc, 'code', None), 'message': scrub(exc, secrets)[:2000]}
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
