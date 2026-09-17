"""Frozen Task06 alignment and explicit staged reads. No feature reconstruction."""

from datetime import timedelta

from features.contract import FIELDS, SPLITS, SNAPSHOTS, time, validate_x
from modeling.m03_io import DATASET,digest,require,ModelError


def x_rows(values):
    try:
        return [validate_x(row) for row in values]
    except ValueError as exc:
        raise ModelError(f"X_contract: {exc}") from exc


def align(x, y, mapping, split, previous=(), *, dataset_id=DATASET):
    x = x_rows(x)
    require(len(x) == len(mapping) and (y is None or len(y) == len(x)), "alignment_count", split)
    seen = set(previous)
    last_key = None
    for i, m in enumerate(mapping):
        require(set(m) == {"row_number", "sample_id", "user_id", "story_id", "version_id", "t0", "split"}, "row_map_fields", str(i))
        require(type(m["row_number"]) is int and m["row_number"] == i, "row_number", str(i))
        require(all(isinstance(m[k], str) and m[k].strip() for k in ("sample_id", "user_id", "story_id")), "row_map_id", str(i))
        require(m["sample_id"] not in seen, "sample_duplicate", m["sample_id"])
        seen.add(m["sample_id"])
        require(m["sample_id"] == "s"+digest([dataset_id, m["user_id"], m["story_id"]]), "sample_key", m["sample_id"])
        require(m["version_id"] in SPLITS and SPLITS[m["version_id"]] == m["split"] == split, "split_contract", str(i))
        key = (m["version_id"], m["user_id"], m["story_id"])
        require(last_key is None or last_key < key, "row_order", str(i))
        last_key = key
        require(time(m["t0"])+timedelta(hours=72) <= time(SNAPSHOTS[m["version_id"]]), "sample_time", m["sample_id"])
        if y is not None:
            require(isinstance(y[i], dict) and set(y[i]) == {"target_not_started_72h"}
                    and type(y[i]["target_not_started_72h"]) is int
                    and y[i]["target_not_started_72h"] in (0, 1), "label_value", str(i))
    return {"X": x, "y": None if y is None else [r["target_not_started_72h"] for r in y], "row_map": mapping}




