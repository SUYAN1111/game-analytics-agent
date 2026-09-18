"""Runs ONLY in the isolated host venv. Real DSH owns conversation/tool loops."""
import argparse
import dataclasses
import importlib.metadata
import json
import os
import sys
import time
import traceback
from pathlib import Path
from task13_runtime.common import CONFIG, ROOT, append, canonical, clean_environment, now, read, redact, replace, require, sha, write


def environment():
    return {'python':sys.version,'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}


def serialize(value):
    if dataclasses.is_dataclass(value): return {k: serialize(v) for k, v in dataclasses.asdict(value).items()}
    if hasattr(value, "model_dump"): return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict): return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [serialize(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--environment-only", action="store_true")
    args = parser.parse_args()
    # The controller attaches the job before admitting this boot message.
    boot = json.loads(sys.stdin.readline())
    if args.environment_only:
        print(canonical(environment()), flush=True); return
    cfg = read(boot["config"])
    directory = Path(cfg["directory"])
    from task13_runtime.boundary import install
    install(directory)
    secret = os.environ.get("DEEPSEEK_API_KEY") if cfg["mode"] == "live" else os.environ.get("TASK09_OFFLINE_CREDENTIAL")
    require(bool(secret), "credential", "DEEPSEEK_API_KEY is missing; no fallback credential store")
    if cfg['mode']=='offline':
        require('DEEPSEEK_API_KEY' not in os.environ and secret.startswith('task09-canary-'),
                'credential','offline driver may only receive a local development canary')
    write(directory/'credential_policy.json',{'mode':cfg['mode'],
        'real_api_key_in_incoming_environment':'DEEPSEEK_API_KEY' in os.environ,
        'credential_source':'offline_generated_canary' if cfg['mode']=='offline' else 'explicit_process_environment'})
    safe = clean_environment()
    safe.update(DEEPSEEK_API_KEY=secret, TASK13_BRIDGE_CONFIG=str(Path(boot["config"]).resolve()),
                DSH_SYSTEM_PROMPT=(ROOT/"task12_runtime/prompts/knowledge_assistant_v1.md").read_text(encoding="utf-8")+cfg['public_adaptation']+(ROOT/'web_api/scope_prompt.md').read_text(encoding='utf-8'))
    os.environ.clear(); os.environ.update(safe)
    home, workspace = directory/"dsh_home", directory/"blank_workspace"
    home.mkdir(); workspace.mkdir()
    if cfg["mode"] == "offline" and cfg.get("workspace_canary"):
        (workspace/"AGENTS.md").write_text(cfg["workspace_canary"], encoding="utf-8")
    write(directory/"host_environment.json", environment())
    # Relative source lookup belongs to the controller, not DSH's blank workspace.
    from deepseek_harness import DeepSeekHarness
    began = time.monotonic()
    try:
        with DeepSeekHarness(dsh_home=str(home), cwd=str(workspace), runtime_cwd=str(workspace),
            profile="sdk-minimal", patches=(str(ROOT/"task13_runtime/dsh_profile/task13.patch.yml"),),
            provider="deepseek-official", model="deepseek-flash", reasoning_effort="off", max_tokens=4096,
            base_url="https://api.deepseek.com" if cfg["mode"] == "live" else cfg["offline_base_url"],
            initialize_timeout_seconds=60, request_timeout_seconds=900, shutdown_timeout_seconds=5) as harness:
            session = harness.start_session()
            write(directory/"dsh_start.json", {"session_id": session.id, "seconds": time.monotonic()-began,
                "driver_pid": os.getpid(), "provider": "deepseek-official", "model": "deepseek-flash", "mode": cfg["mode"]})
            print(canonical({"ready": True, "session_id": session.id}), flush=True)
            for line in sys.stdin:
                command = json.loads(line)
                if command.get("op") == "close": break
                if command == {"op": "offline_new_session"}:
                    require(cfg["mode"] == "offline", "mode", "live history cannot be reset by a check command")
                    previous = session.id
                    session = harness.start_session()
                    append(directory/"sessions.jsonl", {"previous": previous, "session_id": session.id,
                        "reason": "explicit independent offline case; same owned MCP connection"})
                    print(canonical({"new_session": session.id}), flush=True)
                    continue
                require(set(command) == {"op", "turn_id", "text", "require_rule_discovery"}
                        and command["op"] in ("turn", "repair") and type(command["text"]) is str
                        and type(command['require_rule_discovery']) is bool,
                        "command", "driver accepts plain-text turns and a boolean host discovery prerequisite only")
                require(secret not in command["text"], "credential", "credential text cannot enter DSH messages")
                replace(cfg["turn_file"], {"turn_id": command["turn_id"], "stopped": False,
                                        "answer_repair": command['op']=='repair',
                                        "require_rule_discovery": command['require_rule_discovery']})
                start = time.monotonic()
                def notify(notification):
                    append(directory/"notifications.jsonl", {"turn_id": command["turn_id"], "notification": serialize(notification)}, (secret,))
                try:
                    result = session.run(command["text"], on_notification=notify)
                except Exception as exc:
                    from task13_runtime.common import lines
                    failures=[r for r in lines(directory/'http.jsonl') if r.get('event')=='blocked_or_failed' and r.get('turn_id')==command['turn_id']]
                    last=failures[-1] if failures else {}
                    if last.get('code') not in ('model_limit','tool_limit','session_budget','body_limit'):
                        raise
                    record={'turn_id':command['turn_id'],'content_failure':{'code':last['code'],'message':str(exc)},
                            'seconds':time.monotonic()-start,'mode':cfg['mode'],'producer':'actual_DSH_Session.run_exception'}
                    append(directory/'turns.jsonl',record,(secret,))
                    print(canonical(redact(record,(secret,))),flush=True)
                    continue
                record = {"turn_id": command["turn_id"], "result": serialize(result), "seconds": time.monotonic()-start,
                          "mode": cfg["mode"], "producer": "actual_DSH_Session.run"}
                append(directory/"turns.jsonl", record, (secret,))
                print(canonical(redact(record, (secret,))), flush=True)
    except BaseException as exc:
        append(directory/"driver_errors.jsonl", {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}, (secret,))
        print(canonical({"error": redact({"type": type(exc).__name__, "message": str(exc)}, (secret,))}), flush=True)
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


if __name__ == "__main__": main()
