"""Before-attempt reservations shared by all DSH sessions in one run.

Input estimate: one token per UTF-8 request byte plus 1024 overhead tokens,
all charged at uncached peak price; reserve the full 4096 output tokens.
This is a conservative local estimate, not a vendor billing hard limit.
"""
import os
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from agent_runtime.common import FileCommitError, HostError, append, now, read, replace, require, write


def cost(uncached, cached, output):
    for value in (uncached, cached, output):
        require(type(value) is int and value >= 0, "usage", "token counts must be nonnegative integers")
    return float((Decimal(uncached)*2 + Decimal(cached)*Decimal("0.04") + Decimal(output)*8) / 1000000)


def raw_cost(usage):
    require(type(usage) is dict, "usage", "provider usage missing")
    for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        require(type(usage.get(key)) is int and usage[key] >= 0, "usage", "provider usage field missing or invalid: " + key)
    require(usage["prompt_tokens"] == usage["prompt_cache_hit_tokens"] + usage["prompt_cache_miss_tokens"],
            "usage", "cache and uncached usage do not reconcile")
    return cost(usage["prompt_cache_miss_tokens"], usage["prompt_cache_hit_tokens"], usage["completion_tokens"])


class Budget:
    def __init__(self, path, limit=5, max_attempts=32):
        self.path = Path(path)
        self.failure_path = self.path.with_name(self.path.name+".commit_failed.json")
        self.commit_error = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            write(self.path, {"limit_cny": limit, "max_attempts": max_attempts, "attempts": [], "stopped": False})

    @contextmanager
    def locked(self, operation="update"):
        require(self.commit_error is None and not self.failure_path.exists(), "budget_write",
                "预算文件此前提交失败，后续请求已停止；原账本及费用预留保持，见 " + str(self.failure_path))
        lock = self.path.with_suffix(".lock")
        started = time.monotonic()
        while True:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                require(time.monotonic()-started < 10, "budget_lock", "budget ledger is locked; no attempt admitted")
                time.sleep(.02)
        keep_lock = False
        try:
            require(not self.failure_path.exists(), "budget_write", "预算文件提交失败标记已存在，禁止继续")
            state = read(self.path)
            yield state
            try:
                commit = replace(self.path, state)
            except FileCommitError as exc:
                self.commit_error = {"code": "budget_write", "operation": operation, "at": now(),
                    "file_error": exc.detail, "requests_stopped": True,
                    "uncommitted_state": state,
                    "note": "未提交状态只供审计；原账本及已有费用预留仍为权威，不重发HTTP或重复记费。"}
                try:
                    write(self.failure_path, self.commit_error)
                except OSError as marker_error:
                    # If the separate stop record also cannot be written, retain
                    # the lock as a fail-closed barrier across Budget instances.
                    keep_lock = True
                    self.commit_error["stop_marker_error"] = str(marker_error)
                raise HostError("budget_write", "预算文件提交失败，已停止后续请求；原账本及预留保留。" +
                                str(self.failure_path) + "; " + str(exc)) from exc
            if commit["conflicts"]:
                append(self.path.with_name(self.path.name+".commits.jsonl"),
                       {"event": "local_commit_recovered", "operation": operation, **commit})
        finally:
            os.close(descriptor)
            if not keep_lock: lock.unlink()

    def reserve(self, byte_count, turn_id, max_tokens=4096):
        require(type(byte_count) is int and 0 <= byte_count <= 262144, "body_limit", "request UTF-8 body exceeds 262144 bytes")
        require(max_tokens == 4096, "output_limit", "output cap must be 4096")
        amount = cost(byte_count+1024, 0, max_tokens)
        with self.locked("reserve") as state:
            require(not state["stopped"], "stopped", "prior network failure stopped this run")
            attempts = state["attempts"]
            require(len(attempts) < state["max_attempts"], "attempt_limit", "global API attempt limit reached")
            require(sum(a["turn_id"] == turn_id for a in attempts) < 6, "model_limit", "six model attempts per user turn reached")
            committed = sum(a.get("actual_cny", a["reserved_cny"]) for a in attempts)
            require(committed+amount <= state["limit_cny"], "budget_limit", "next API reservation exceeds local budget")
            item = {"attempt_id": uuid4().hex, "turn_id": turn_id, "request_bytes": byte_count,
                    "reserved_cny": amount, "status": "reserved_fee_unknown"}
            attempts.append(item)
        return item

    def settle(self, attempt_id, usage=None, error=None):
        # Missing/incomplete usage retains the reservation; never charge an invented zero.
        with self.locked("settle") as state:
            matches = [a for a in state["attempts"] if a["attempt_id"] == attempt_id]
            require(len(matches) == 1 and matches[0]["status"] == "reserved_fee_unknown", "attempt_id", "unknown or duplicate settlement")
            item = matches[0]
            item["raw_usage"] = usage
            if error is None:
                try:
                    item["actual_cny"] = raw_cost(usage)
                    require(usage["completion_tokens"] <= 4096, "output_limit", "provider exceeded output cap")
                    item["status"] = "settled"
                except ValueError as exc:
                    error = str(exc)
            if error is not None:
                state["stopped"] = True
                item["status"] = "failed_fee_unknown" if "actual_cny" not in item else "failed_usage_recorded"
                item["error"] = error
            if sum(a.get("actual_cny", a["reserved_cny"]) for a in state["attempts"]) > state["limit_cny"]:
                state["stopped"] = True
                item["budget_estimate_exceeded"] = True
                error = "observed usage exceeded the local budget estimate"
                item["error"] = error
                item["status"] = "failed_usage_recorded"
        append(self.path.with_suffix(".jsonl"), item)
        require(error is None, "network_stop", error or "network attempt failed")
        return item

    def stop(self, reason):
        if self.commit_error is not None or self.failure_path.exists():
            # Never overwrite the preserved pre-failure ledger during cleanup.
            return {"stopped": True, "reason": "budget_write", "failure_record": str(self.failure_path)}
        with self.locked("stop") as state:
            state["stopped"] = True
            state["controller_stop_reason"] = reason
            for item in state["attempts"]:
                if item["status"] == "reserved_fee_unknown":
                    item["status"] = "stopped_fee_unknown"
                    item["error"] = reason
                    # A locally cancelled remote request may still incur billing.
                    # Its original conservative reservation remains committed.
        append(self.path.with_suffix(".jsonl"), {"event": "controller_stopped", "reason": reason})
