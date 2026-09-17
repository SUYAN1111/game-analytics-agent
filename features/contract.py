"""Frozen Task06 field constants and strict observed-input boundary."""

import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path

from analysis_core.temporal import InputError, format_utc, parse_utc

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "completed_sessions_7d", "completed_active_dates_7d", "observed_days_7d",
    "completed_sessions_28d", "completed_active_dates_28d", "observed_days_28d",
    "hours_since_last_completed_session_28d", "mean_session_minutes_28d",
    "session_45min_share_28d", "prior_complete_story_count", "prior_started_72h_count",
    "prior_started_72h_rate", "account_age_days", "new_player", "hours_since_region_open",
    "expected_story_minutes", "region_id", "language", "client",
)
NULLABLE = frozenset(FIELDS[i] for i in (6, 7, 8, 11))
INTEGERS = frozenset(FIELDS[i] for i in (0, 1, 3, 4, 9, 10, 13))
TABLE_FIELDS = {
    "players": "user_id registered_at cohort_version available_at",
    "player_attributes": "attribute_id user_id valid_from valid_to region_id language client available_at",
    "story_calendar": "story_id version_id region_id region_open_at expected_story_minutes available_at",
    "source_catalog": "source_id region_id event_kind available_at",
    "session_uploads": "upload_id session_id user_id source_id start_at end_at available_at",
    "story_start_uploads": "upload_id event_id user_id story_id session_id source_id event_time available_at",
    "qualification_checks": "record_id user_id story_id checked_at state prereq_met_at available_at",
    "collection_checks": "record_id source_id interval_id start_at end_at state checked_at available_at",
    "watermark_checks": "record_id source_id watermark_at checked_at available_at",
}
VERSIONS = tuple("V" + str(n) for n in range(1, 7))
SPLITS = dict(zip(VERSIONS, ("train", "train", "train", "selection", "test", "test")))
SNAPSHOTS = dict(zip(VERSIONS, ("2025-01-20T14:00:00Z", "2025-02-17T14:00:00Z",
    "2025-03-17T14:00:00Z", "2025-04-14T14:00:00Z", "2025-05-12T14:00:00Z", "2025-06-09T14:00:00Z")))
OBSERVATION_START = "2024-11-06T01:00:00Z"


class FeatureError(InputError):
    pass


def require(condition, code, detail):
    if not condition:
        raise FeatureError(f"{code}: {detail}")


def time(value):
    return parse_utc(value, "feature_time")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")


def write_rows(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(canonical(value) + "\n")


def read_rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            require(isinstance(row, dict), "row_structure", f"{path}:{number}")
            yield row


def validate_x(row):
    require(isinstance(row, dict) and set(row) == set(FIELDS), "feature_whitelist", "X必须且仅有19列")
    for key in FIELDS:
        value = row[key]
        if value is None:
            require(key in NULLABLE, "feature_null", key)
        elif key in ("region_id", "language", "client"):
            allowed = {"region_id": ("R1", "R2", "R3"), "language": ("L1", "L2"), "client": ("PC", "Mobile")}
            require(value in allowed[key], "feature_category", key)
        else:
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "feature_numeric", key)
            if key in INTEGERS:
                require(type(value) is int, "feature_integer", key)
    require(row["new_player"] in (0, 1) and row["expected_story_minutes"] == 45, "feature_contract", "年龄标志/剧情时长")
    for key in ("session_45min_share_28d", "prior_started_72h_rate"):
        require(row[key] is None or 0 <= row[key] <= 1, "feature_rate", key)
    require(row["prior_started_72h_count"] <= row["prior_complete_story_count"], "feature_count", "历史剧情计数")
    for days in (7, 28):
        require(row[f"completed_active_dates_{days}d"] <= row[f"completed_sessions_{days}d"], "feature_count", "日期数不能多于会话数")
        require(row[f"observed_days_{days}d"] <= days, "feature_observation", "实际观察时长不能超过配置窗口")
    for key in ("mean_session_minutes_28d", "session_45min_share_28d", "hours_since_last_completed_session_28d"):
        require((row[key] is None) == (row["completed_sessions_28d"] == 0), "feature_null", key+"仅N28=0时为空")
    require((row["prior_started_72h_rate"] is None) == (row["prior_complete_story_count"] == 0), "feature_null", "历史比例空值")
    return {key: row[key] for key in FIELDS}


def read_x(path):
    """No numeric-column inference; returns the explicit 19-column whitelist."""
    for row in read_rows(path):
        yield validate_x(row)


def load_contract():
    value = json.loads((ROOT / "business_configs/m03_features_v1.json").read_text(encoding="utf-8"))
    require(value["feature_order"] == list(FIELDS) and value["observation_start"] == OBSERVATION_START,
            "feature_contract", "字段顺序/观测起点")
    require(value["label_snapshots"] == SNAPSHOTS and value["splits"] == SPLITS and
            value["session_windows_days"] == [7, 28] and value["label_window_hours"] == 72,
            "feature_contract", "窗口或时间切分改变")
    return value


def validate_row(table, raw):
    require(isinstance(raw, dict) and set(raw) == set(TABLE_FIELDS[table].split()), "observed_whitelist", table)
    row = dict(raw)
    for field, value in row.items():
        if field.endswith("_at") or field in ("event_time", "valid_from", "valid_to"):
            if value is None:
                require(field in ("valid_to", "prereq_met_at"), "null_time", field)
            else:
                row[field] = format_utc(time(value))
        elif field != "expected_story_minutes":
            require(isinstance(value, str) and bool(value.strip()), "identifier", field)
    if table == "session_uploads":
        require(time(row["start_at"]) < time(row["end_at"]) <= time(row["available_at"]), "session_time", row["session_id"])
    if table == "story_start_uploads":
        require(time(row["event_time"]) <= time(row["available_at"]), "start_time", row["event_id"])
    if table == "players":
        require(time(row["registered_at"]) <= time(row["available_at"]), "player_time", row["user_id"])
    if table == "player_attributes":
        require(time(row["valid_from"]) <= time(row["available_at"]) and
                (row["valid_to"] is None or time(row["valid_from"]) < time(row["valid_to"])), "attribute_time", row["attribute_id"])
    return row
