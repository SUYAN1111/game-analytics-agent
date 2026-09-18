"""Standard-library file, identity and credential boundaries; no model imports."""
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "agent_runtime/configs/task09_deepseek_v1.json"
TOOLS = ("inspect_context", "check_quality", "query_metric", "compare_results",
         "predict_registered", "read_model_card", "get_evidence")


class HostError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(value, code, message):
    if not value:
        raise HostError(code, message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value) + "\n")


COMMIT_RETRY_DELAYS = (.02, .04, .08, .16, .20)  # Six attempts, at most 0.50s scheduled waiting.


class FileCommitError(HostError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__("file_commit", "local atomic file commit failed: " + canonical(detail))


def replace(path, value):
    """One serialization, unique sibling temp, then bounded local rename retries.

    Caller owns any transaction lock. A failed temp is retained as uncommitted
    evidence. No caller operation, HTTP request or accounting action is replayed.
    """
    path = Path(path)
    temporary, attempts, conflicts = None, 0, []
    try:
        payload = canonical(value) + "\n"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                dir=path.parent, prefix=path.name+".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # The handle is closed before every replacement attempt, on Windows too.
        for attempt in range(len(COMMIT_RETRY_DELAYS)+1):
            attempts = attempt+1
            try:
                os.replace(temporary, path)
                return {"path": str(path), "temporary": str(temporary), "attempts": attempts,
                        "conflicts": conflicts, "scheduled_wait_seconds": sum(COMMIT_RETRY_DELAYS[:attempt])}
            except OSError as exc:
                winerror = getattr(exc, "winerror", None)
                if winerror not in (5, 32, 33) or attempt == len(COMMIT_RETRY_DELAYS):
                    raise
                conflicts.append({"attempt": attempts, "winerror": winerror, "message": str(exc)})
                time.sleep(COMMIT_RETRY_DELAYS[attempt])
    except OSError as exc:
        raise FileCommitError({"path": str(path), "temporary": str(temporary) if temporary else None,
            "attempts": attempts, "max_attempts": len(COMMIT_RETRY_DELAYS)+1,
            "scheduled_wait_seconds": sum(COMMIT_RETRY_DELAYS[:max(0, attempts-1)]),
            "conflicts": conflicts, "type": type(exc).__name__, "winerror": getattr(exc, "winerror", None),
            "errno": exc.errno, "message": str(exc), "original_ledger_preserved": True}) from exc


def redact(value, secrets=()):
    """Never include credential values or fragments in diagnostics."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"authorization|api.?key|access.?token|secret", k, re.I)
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value, flags=re.I)
        return value
    return value


def append(path, value, secrets=()):
    path = Path(path)
    debug = {'notifications.jsonl','mcp_wire.jsonl'}
    if path.name in debug:
        if os.environ.get('APP_DEBUG')!='1':return
        if path.exists() and path.stat().st_size>=8*1024*1024:return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical(redact(value, secrets)) + "\n")


def lines(path):
    path = Path(path)
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)


def clean_environment():
    # An allowlist, not removal of one key from an otherwise inherited environment.
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432",
               "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "OS", "APP_ASSET_DIR", "APP_STATE_DIR", "APP_DEBUG", "APP_READ_AUDIT"}
    # The hosted Python executable/native extensions may need its library path.
    # Never inherit PYTHONPATH, LD_PRELOAD, database or model credentials here.
    if os.name != 'nt': allowed.add('LD_LIBRARY_PATH')
    from product_core.paths import STATE
    temporary=STATE/"temporary"/str(os.getpid());temporary.mkdir(parents=True,exist_ok=True)
    return {k: v for k, v in os.environ.items() if k.upper() in allowed} | {
        "TEMP":str(temporary),"TMP":str(temporary),
        **({'HOME':str(temporary),'TMPDIR':str(temporary)} if os.name != 'nt' else {}),
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def within_run(path):
    from product_core.paths import within_state
    return within_state(path)


def verify_task08(config):
    fixed = {"provider": "deepseek-official", "model": "deepseek-flash", "base_url": "https://api.deepseek.com",
        "reasoning_effort": "off", "thinking": {"type": "disabled"}, "temperature": 0, "max_output_tokens": 4096,
        "retry_policy": {"mode": "normal", "maxRetries": 0}, "role": "analysis_demo", "default_mode": "offline",
        "sdk_version": "0.1.5rc1", "runtime_version": "0.1.5rc1",
        "limits": {"budget_cny": 5, "live_api_attempts": 32, "model_requests_per_turn": 6, "tools_per_turn": 12,
                   "request_body_bytes": 262144, "turn_seconds": 900, "model_seconds": 180,
                   "tool_seconds": 600, "handshake_seconds": 60, "heartbeat_seconds": 30}}
    for key, expected in fixed.items():
        require(config.get(key) == expected, "configuration", "fixed Task09 configuration differs: "+key)
    from product_core.release import host
    value=host()
    for key in ('dataset_id','feature_set_id','experiment_id','selected_candidate_id'):
        require(value['definition']['identities'][key]==config[key],'identity','frozen identity differs: '+key)
    return value
