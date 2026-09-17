"""Loopback HTTP fixture, consumed by the REAL DSH DeepSeek adapter and loop.

Never imported by the live driver/plugin. Scripts are fixed before each test.
This server does not execute tools; it emits tool_calls and reads returned messages.
"""
import copy
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from agent_runtime.common import append, canonical, require


def tool_results(messages):
    results = []
    for message in messages:
        if message.get("role") != "tool": continue
        content = message.get("content")
        if isinstance(content, list): content = "".join(x.get("text", "") for x in content)
        try: value = json.loads(content)
        except (TypeError, ValueError): continue
        if isinstance(value, dict) and "tool_name" in value: results.append(value)
    return results


def find_result(results, selector):
    parts = selector.split(":")
    tool = parts[0]
    for result in reversed(results):
        if result["tool_name"] == tool and result["error"] is None and (len(parts) == 1 or result["validated_arguments"].get("cohort_id") == parts[1]):
            return result
    raise ValueError("script expected an actual prior tool result: "+selector)


def refs(value, results):
    if isinstance(value, str) and value.startswith("$evidence:"):
        return find_result(results, value[len("$evidence:"):])["evidence_id"]
    if isinstance(value, dict): return {k: refs(v, results) for k, v in value.items()}
    if isinstance(value, list): return [refs(v, results) for v in value]
    return value


def claim_for(result, field, identifier="c1", index=0):
    row = result["data"]["rows"][index]
    tool = result["tool_name"]
    if tool == "compare_results":
        value = row["count_differences"][field] if field not in ("rate_difference", "percentage_point_difference") else row[field]
        kind = "count_difference" if field not in ("rate_difference", "percentage_point_difference") else field
        path = "count_differences/"+field if kind == "count_difference" else field
        scope = {"left_version": row["left"]["version_id"], "right_version": row["right"]["version_id"],
                 "group_by": row["left"]["group_by"], "group_value": row["left"]["group_value"], "window_hours": 72}
    else:
        value, path = row[field], field
        if tool == "predict_registered":
            kind = "prediction_probability" if field == "mean_p" else "prediction_coverage" if field == "prediction_coverage" else "prediction_count"
            scope = {"version_id": row["version_id"], "model_id": "model_m03_lr_c0p1_frozen_v1", "time_mode": "frozen_t0_replay"}
        else:
            kind = "metric_rate" if field == "rate" else "observation_coverage" if field == "observation_coverage" else "count"
            scope = {"version_id": row["version_id"], "group_by": row["group_by"], "group_value": row["group_value"], "window_hours": 72}
    integer = kind in ("count", "count_difference", "prediction_count")
    return {"id": identifier, "meaning": field, "kind": kind, "evidence_id": result["evidence_id"],
            "content_fingerprint": result["runtime"]["content_fingerprint"], "pointer": f"/data/rows/{index}/"+path,
            "value": value, "raw_unit": "count" if integer else "percentage_point" if kind == "percentage_point_difference" else "ratio",
            "display_unit": "count" if integer else "percentage_point" if "difference" in kind else "percent",
            "precision": 0 if integer else 2, "scope": scope}


class ModelStub:
    def __init__(self, directory):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.actions, self.index, self.serial = [], 0, 0
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                try:
                    length = int(self.headers["Content-Length"])
                    received = self.rfile.read(length)
                    body = json.loads(received)
                    action = copy.deepcopy(owner.actions[owner.index]); owner.index += 1
                    step = owner.index
                    append(owner.directory/"requests.jsonl", {"request": body, "script_step": owner.index,
                        "received_bytes": len(received), "received_body_sha256": hashlib.sha256(received).hexdigest(),
                        "credential_received": bool(self.headers.get("Authorization")), "mode": "offline_scripted_provider"})
                    if action.get("delay"): time.sleep(action["delay"])
                    status = action.get("status", 200)
                    if status != 200:
                        self.send_response(status); self.end_headers(); self.wfile.write(b'{"error":{"message":"fixed offline HTTP error"}}'); return
                    results = tool_results(body["messages"])
                    frames = []
                    def frame(delta, finish=None):
                        return {"id": "offline-response-"+str(owner.serial), "object": "chat.completion.chunk",
                            "model": "deepseek-flash", "system_fingerprint": "offline-not-a-provider-weight",
                            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                    if "calls" in action:
                        for index, call in enumerate(action["calls"]):
                            args = call.get("raw_arguments", canonical(refs(call.get("arguments", {}), results)))
                            cid = "offline-call-"+str(owner.serial)+"-"+str(step)+"-"+str(index)
                            cut = max(1, len(args)//2)
                            frames.append(frame({"tool_calls": [{"index": index, "id": cid, "type": "function",
                                "function": {"name": call["name"], "arguments": args[:cut]}}]}))
                            frames.append(frame({"tool_calls": [{"index": index, "function": {"arguments": args[cut:]}}]}))
                        frames.append(frame({}, "tool_calls"))
                    else:
                        claims = [claim_for(find_result(results, c["selector"]), c["field"], "c"+str(i+1))
                                  for i, c in enumerate(action.get("claims", []))]
                        # Offline body-only attacks retain claims constructed from
                        # the actual returned evidence; never substitute an oracle.
                        body_text = "\n".join(["{{claim:"+c["id"]+"}}" for c in claims]+["{{note:causality}}"])
                        answer = action.get("answer", {"answer_markdown": action.get("answer_markdown", body_text), "claims": claims})
                        # Explicit new scripts may resolve ONLY current tool
                        # evidence IDs in semantic selections; no row lookup,
                        # pointer, numeric value or verifier is used here.
                        if action.get("resolve_answer_refs"):
                            answer = refs(answer, results)
                        # Fixed malformed-response replay is deliberately not
                        # corrected by the stub even when JSON mode is requested.
                        frames.append(frame({"content": action.get("raw_answer", canonical(answer))})); frames.append(frame({}, action.get("finish", "stop")))
                    if not action.get("omit_usage"):
                        # Two cumulative usage records deliberately exercise last-value accounting.
                        for usage in ({"prompt_tokens": 80, "prompt_cache_hit_tokens": 20, "prompt_cache_miss_tokens": 60, "completion_tokens": 10},
                                      action.get("usage", {"prompt_tokens": 100, "prompt_cache_hit_tokens": 25, "prompt_cache_miss_tokens": 75, "completion_tokens": 20})):
                            frames.append({"id": "offline-response-"+str(owner.serial), "model": "deepseek-flash", "choices": [], "usage": usage})
                    raw = "".join("data: "+canonical(f)+"\n\n" for f in frames)
                    if not action.get("incomplete"): raw += "data: [DONE]\n\n"
                    append(owner.directory/"responses.jsonl", {"frames": frames, "mode": "offline_scripted_provider"})
                    self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                    self.wfile.write(raw.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError): pass
                except Exception as exc:
                    append(owner.directory/"errors.jsonl", {"type": type(exc).__name__, "message": str(exc)})
                    try: self.send_error(500, "offline script failed")
                    except OSError: pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:"+str(self.server.server_address[1])

    def script(self, actions):
        self.actions = copy.deepcopy(actions); self.index = 0; self.serial += 1
        append(self.directory/"scripts.jsonl", {"serial": self.serial, "actions": actions, "fixed_before_request": True})

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
