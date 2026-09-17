"""通用半开区间覆盖及交付证据核查；不推导上游声明的真实性。"""

from collections import defaultdict
from copy import deepcopy

from analysis_core.temporal import InputError, format_utc, parse_utc, require_id


COLLECTION_FIELDS = frozenset(("record_id", "source_id", "interval_id", "start_at", "end_at",
                               "state", "checked_at", "available_at"))
WATERMARK_FIELDS = frozenset(("record_id", "source_id", "watermark_at", "checked_at", "available_at"))


def validate_sources(value, context="required_source_ids"):
    if not isinstance(value, list) or not value:
        raise InputError(f"{context}: 必须是非空来源列表")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise InputError(f"{context}: 来源 ID 必须是非空字符串")
    if len(set(value)) != len(value):
        raise InputError(f"{context}: 来源 ID 不得重复")
    return list(value)


def _read_table(rows, table, snapshot, collection):
    fields = COLLECTION_FIELDS if collection else WATERMARK_FIELDS
    if not isinstance(rows, list):
        raise InputError(f"{table}: 必须是列表")
    visible, excluded = [], []
    for index, raw in enumerate(rows):
        context = f"{table}[{index}]"
        if not isinstance(raw, dict) or set(raw) != fields:
            raise InputError(f"{context}: 字段必须为 {sorted(fields)}")
        row = {field: require_id(raw, field, context) for field in
               (("record_id", "source_id", "interval_id") if collection else ("record_id", "source_id"))}
        time_fields = ("start_at", "end_at", "checked_at", "available_at") if collection else (
            "watermark_at", "checked_at", "available_at")
        times = {field: parse_utc(raw[field], f"{context}.{field}") for field in time_fields}
        row.update({field: format_utc(value) for field, value in times.items()})
        if collection:
            if raw["state"] not in ("complete", "gap"):
                raise InputError(f"{context}.state: 必须是 complete 或 gap")
            row["state"] = raw["state"]
            valid = times["start_at"] < times["end_at"] <= times["checked_at"] <= times["available_at"]
        else:
            valid = times["watermark_at"] <= times["checked_at"] <= times["available_at"]
        if not valid:
            raise InputError(f"{context}: 非法时间关系")
        evidence = {"input_row": index + 1, "record": deepcopy(raw), "normalized": row}
        if times["checked_at"] <= snapshot and times["available_at"] <= snapshot:
            visible.append(evidence)
        else:
            excluded.append(evidence)

    unique = {}
    for evidence in visible:
        row = evidence["normalized"]
        previous = unique.get(row["record_id"])
        if previous is not None:
            if {k: v for k, v in previous.items() if k != "available_at"} != {
                    k: v for k, v in row.items() if k != "available_at"}:
                raise InputError(f"{table}: record_id={row['record_id']!r} 同记录 ID 可见业务内容冲突")
            if _time(row["available_at"]) < _time(previous["available_at"]):
                unique[row["record_id"]] = row
        else:
            unique[row["record_id"]] = row
    return {"counts": {"input_rows": len(rows), "visible_rows": len(visible),
                       "deduplicated_records": len(unique), "excluded_rows": len(excluded)},
            "visible_uploads": visible, "excluded_uploads": excluded,
            "records": sorted(unique.values(), key=lambda row: row["record_id"])}


def _time(value):
    return parse_utc(value, "coverage evidence time")


def prepare_evidence(collection_checks, watermark_checks, as_of):
    """先验证全部记录，再筛选、去重和选择版本。合法未用来源也保留。"""
    snapshot = parse_utc(as_of, "as_of")
    collection = _read_table(collection_checks, "collection_checks", snapshot, True)
    watermarks = _read_table(watermark_checks, "watermark_checks", snapshot, False)
    all_sources = {row["source_id"] for row in collection_checks + watermark_checks}
    sources = {}
    for source_id in sorted(all_sources):
        intervals = defaultdict(list)
        for row in collection["records"]:
            if row["source_id"] == source_id:
                intervals[row["interval_id"]].append(row)
        current, conflicts, superseded = [], [], []
        for interval_id, history in sorted(intervals.items()):
            latest_time = max(_time(row["checked_at"]) for row in history)
            latest = [row for row in history if _time(row["checked_at"]) == latest_time]
            superseded.extend(row for row in history if _time(row["checked_at"]) < latest_time)
            boundaries = {(row["start_at"], row["end_at"]) for row in history}
            states = {row["state"] for row in latest}
            if len(boundaries) != 1:
                conflicts.append({"code": "interval_boundaries_conflict", "interval_id": interval_id,
                                  "record_ids": sorted(row["record_id"] for row in history),
                                  "reason": "同一区间可见历史边界改变", "records": history})
            if len(states) != 1:
                conflicts.append({"code": "interval_state_conflict", "interval_id": interval_id,
                                  "record_ids": sorted(row["record_id"] for row in latest),
                                  "reason": "最新同刻采集状态冲突", "records": latest})
            valid = len(boundaries) == 1 and len(states) == 1
            current.append({"interval_id": interval_id, "start_at": latest[0]["start_at"] if valid else None,
                            "end_at": latest[0]["end_at"] if valid else None,
                            "state": latest[0]["state"] if valid else "conflict",
                            "checked_at": format_utc(latest_time),
                            "record_ids": sorted(row["record_id"] for row in latest), "records": latest})
        wm_history = [row for row in watermarks["records"] if row["source_id"] == source_id]
        latest_wm, old_wm = None, []
        if wm_history:
            latest_time = max(_time(row["checked_at"]) for row in wm_history)
            latest = [row for row in wm_history if _time(row["checked_at"]) == latest_time]
            old_wm = [row for row in wm_history if _time(row["checked_at"]) < latest_time]
            conflicting = len({row["watermark_at"] for row in latest}) != 1
            if conflicting:
                conflicts.append({"code": "watermark_conflict", "reason": "最新同刻交付水位冲突",
                                  "record_ids": sorted(row["record_id"] for row in latest), "records": latest})
            latest_wm = {"watermark_at": None if conflicting else latest[0]["watermark_at"],
                         "checked_at": format_utc(latest_time),
                         "record_ids": sorted(row["record_id"] for row in latest), "records": latest}
        sources[source_id] = {
            "source_id": source_id, "current_intervals": current, "latest_watermark": latest_wm,
            "conflicts": conflicts, "superseded_collection_records": superseded,
            "superseded_watermark_records": old_wm,
            "excluded_collection_uploads": [row for row in collection["excluded_uploads"]
                                             if row["normalized"]["source_id"] == source_id],
            "excluded_watermark_uploads": [row for row in watermarks["excluded_uploads"]
                                            if row["normalized"]["source_id"] == source_id]}
    return {"as_of": format_utc(snapshot), "collection": collection, "watermarks": watermarks, "sources": sources}


def _ranges(ranges):
    return [{"start_at": format_utc(start), "end_at": format_utc(end)} for start, end in ranges]


def assess_coverage(window_start, window_end, required_source_ids, evidence):
    """接收显式窗口，不包含指标名或固定窗口长度。完整区间与已知 gap 独立核查。"""
    start, end = _time(window_start), _time(window_end)
    if start >= end:
        raise InputError("coverage window: start 必须早于 end")
    source_ids = validate_sources(required_source_ids)
    audits = []
    for source_id in source_ids:
        source = deepcopy(evidence["sources"].get(source_id, {
            "source_id": source_id, "current_intervals": [], "latest_watermark": None, "conflicts": [],
            "superseded_collection_records": [], "superseded_watermark_records": [],
            "excluded_collection_uploads": [], "excluded_watermark_uploads": []}))
        complete, known_gaps, confirmations = [], [], []
        for interval in source["current_intervals"]:
            if interval["state"] == "conflict":
                continue
            left, right = max(start, _time(interval["start_at"])), min(end, _time(interval["end_at"]))
            if left >= right:
                continue
            if interval["state"] == "gap":
                known_gaps.append({"interval_id": interval["interval_id"],
                                   **_ranges([(left, right)])[0], "record_ids": interval["record_ids"],
                                   "checked_at": interval["checked_at"]})
            else:
                complete.append((left, right))
                confirmations.append(_time(interval["checked_at"]))
        merged = []
        for left, right in sorted(complete):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        holes, cursor = [], start
        for left, right in merged:
            if cursor < left:
                holes.append((cursor, left))
            cursor = max(cursor, right)
        if cursor < end:
            holes.append((cursor, end))
        reasons, codes = [], []

        def reason(code, message):
            codes.append(code)
            reasons.append(message)

        if source["conflicts"]:
            reason("source_conflict", "必需来源存在业务冲突")
        if known_gaps:
            reason("known_gap", "当前版本存在与窗口相交的已知采集缺口")
        if holes:
            reason("uncovered", "完整区间并集未覆盖整个窗口")
        watermark = source["latest_watermark"]
        last_confirmation = max(confirmations) if confirmations else None
        reaches_end = None if watermark is None or watermark["watermark_at"] is None else _time(watermark["watermark_at"]) >= end
        follows_confirmation = (None if watermark is None or last_confirmation is None else
                                _time(watermark["checked_at"]) >= last_confirmation)
        if watermark is None:
            reason("missing_watermark", "没有可见交付水位")
        elif watermark["watermark_at"] is None:
            reason("conflicting_watermark", "最新交付水位存在冲突")
        elif not reaches_end:
            reason("watermark_short", "最新交付水位未到达窗口右端")
        if follows_confirmation is False:
            reason("watermark_before_confirmation", "水位早于当前完整性确认")
        source.update(status="conflict" if source["conflicts"] else ("incomplete" if codes else "complete"),
                      coverage_complete=not codes, merged_complete_intervals=_ranges(merged),
                      uncovered_intervals=_ranges(holes), known_gaps=known_gaps,
                      max_complete_checked_at=format_utc(last_confirmation),
                      watermark_reaches_window_end=reaches_end,
                      watermark_follows_confirmation=follows_confirmation,
                      reason_codes=codes, reasons=reasons or ["采集区间与交付证据支持本窗口完整"])
        audits.append(source)
    complete = all(row["coverage_complete"] for row in audits)
    return {"status": "complete" if complete else "incomplete", "coverage_complete": complete,
            "window_start": format_utc(start), "window_end": format_utc(end),
            "required_source_ids": source_ids, "sources": audits,
            "reason_codes": sorted({code for row in audits for code in row["reason_codes"]}),
            "reasons": ["全部必需来源满足完整性要求"] if complete else ["部分必需来源未满足完整性要求"]}
