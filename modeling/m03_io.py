"""Standard-library boundaries, identities and append-only execution evidence."""

import hashlib
import importlib.metadata
import json
import math
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from features.contract import FIELDS, canonical, digest, sha, write_json, write_rows

ROOT = Path(__file__).resolve().parents[1]
DATASET = "m035c1fae9c52860eb04c4565ca"
FEATURE = "m03f86fba0d54aeb2d2793c09008"
FULL_FEATURE = "86fba0d54aeb2d2793c09008bdbb6f4b0157c662c05bd819c4c5dc19e7dbaad6"
IDS = ("baseline_prior", "lr_c0p1", "lr_c1", "lr_c10", "tree_d2", "tree_d3", "tree_d4")
CATEGORIES = ("region_id", "language", "client")
NUMERIC = tuple(k for k in FIELDS if k not in CATEGORIES)
MISSING = ("hours_since_last_completed_session_28d", "mean_session_minutes_28d",
           "session_45min_share_28d", "prior_started_72h_rate")



class ModelError(ValueError):
    pass


def require(ok, code, detail):
    if not ok:
        raise ModelError(f"{code}: {detail}")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def probabilities(values):
    result = [float(p) for p in values]
    require(all(math.isfinite(p) and 0 <= p <= 1 for p in result), "probability", "必须有限且在[0,1]；不裁剪")
    return result


def environment():
    result = {"python": sys.version, "implementation": platform.python_implementation(),
              "os": platform.platform(), "machine": platform.machine(), "packages": {}}
    for name in ("scikit-learn", "numpy", "scipy", "joblib", "threadpoolctl"):
        try:
            result["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result["packages"][name] = None
    return result


def validate_environment(env):
    require(all(env["packages"].values()), "dependency_missing", canonical(env["packages"]))
    require(env["packages"]["scikit-learn"] == "1.8.0", "dependency_version", "需要scikit-learn==1.8.0")








