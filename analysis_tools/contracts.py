"""Small concrete tool contract; strict JSON and no request-time registration."""

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS = frozenset(("invalid_arguments", "unauthorized", "integrity_error", "data_error",
                    "not_found", "timeout", "cancelled", "internal_error"))
GROUPS = ("none", "region_id", "language", "client", "new_player")


class ToolError(ValueError):
    def __init__(self, code, reason):
        if code not in ERRORS:
            raise ValueError("unknown error classification")
        self.code, self.reason = code, reason
        super().__init__(f"{code}: {reason}")


def require(condition, code, reason):
    if not condition:
        raise ToolError(code, reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")


def append(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")


def validate(schema, value):
    """Only the published concrete object/string/enum contract, without coercion."""
    require(type(value) is dict, "invalid_arguments", "arguments must be an object")
    require(set(value) <= set(schema["properties"]) and set(schema["required"]) <= set(value),
            "invalid_arguments", "missing or additional arguments")
    for key, item in value.items():
        rule = schema["properties"][key]
        require(type(item) is str and bool(item.strip()), "invalid_arguments", "string argument required")
        if "enum" in rule:
            require(item in rule["enum"], "invalid_arguments", "unsupported enumerated argument")
    return dict(value)


def status(rows_):
    if not rows_ or sum(r["candidate_count"] for r in rows_) == 0:
        return "empty"
    if any(r["Q0"] or r["Q2"] or r["Q3"] for r in rows_):
        return "partial"
    if sum(r["denominator"] for r in rows_) == 0:
        return "not_computable"
    return "ok"


def prediction_summary(predictions, expected, versions):
    result = []
    for version in list(versions) + (["+".join(versions)] if len(versions) > 1 else []):
        selected = [p for p in predictions if p["version_id"] in version.split("+")]
        n_expected = sum(expected[v] for v in version.split("+"))
        require(len(selected) == n_expected, "integrity_error", "prediction cohort coverage mismatch")
        bins = []
        for i in range(5):
            bucket = [p["p_not_started_72h"] for p in selected
                      if min(int(p["p_not_started_72h"] * 5), 4) == i]
            bins.append({"lower": i / 5, "upper": (i + 1) / 5, "right_inclusive": i == 4,
                         "count": len(bucket), "mean_p": math.fsum(bucket) / len(bucket) if bucket else None})
        result.append({"version_id": version, "expected_qualified_count": n_expected,
                       "predicted_count": len(selected), "missing_count": n_expected-len(selected),
                       "prediction_coverage": len(selected)/n_expected if n_expected else None,
                       "mean_p": math.fsum(p["p_not_started_72h"] for p in selected)/len(selected) if selected else None,
                       "bins": bins})
    return result
