"""M03 最小计算器；不读取文件、预期答案或系统当前时间。"""

from datetime import timedelta

from analysis_core.temporal import (
    InputError, format_utc, in_window, is_mature, parse_utc,
    require_id, validate_duration, visible_unique_events, window_end,
)


DEFAULT_WINDOW = timedelta(hours=72)
Q_STATES = ("Q0", "Q1", "Q2", "Q3", "Q4", "Q5")


def calculate_m03(population, start_events, as_of, *, duration=DEFAULT_WINDOW):
    """返回可 JSON 序列化的逐组合结果和聚合值；输入错误抛出 InputError。

    本轮将整理好的 qualification_status/coverage_complete 作为输入事实，
    不从原始流水、采集心跳或水位证明这些标记。缺少必要时间用 None 表示。
    """
    snapshot = parse_utc(as_of, "as_of")
    # 即使清单为空也验证窗口参数。
    validate_duration(duration)
    if not isinstance(population, list):
        raise InputError("population: 必须为列表")
    members = {}
    for index, row in enumerate(population):
        context = f"population[{index}]"
        if not isinstance(row, dict):
            raise InputError(f"{context}: 必须为对象")
        key = (require_id(row, "user_id", context), require_id(row, "story_id", context))
        if key in members:
            raise InputError(f"{context}: 重复研究组合 {key!r}")
        qualification = row.get("qualification_status")
        if qualification not in ("qualified", "not_qualified", "unknown"):
            raise InputError(f"{context}.qualification_status: 非法资格状态 {qualification!r}")
        coverage = row.get("coverage_complete")
        if type(coverage) is not bool:
            raise InputError(f"{context}.coverage_complete: 必须为布尔值")
        times = {}
        for field in ("region_open_at", "prereq_met_at"):
            value = row.get(field)
            times[field] = None if value is None else parse_utc(value, f"{context}.{field}")
        if qualification == "qualified" and any(
            value is not None and value > snapshot for value in times.values()
        ):
            raise InputError(f"{context} {key!r}: 资格信息矛盾，必要资格时间晚于 as_of")
        t0 = None
        if qualification == "qualified" and all(value is not None for value in times.values()):
            t0 = max(times.values())
        members[key] = (qualification, coverage, t0)

    events, visible_rows = visible_unique_events(start_events, members, snapshot)
    grouped = {key: [] for key in members}
    for event in events:
        grouped[(event["user_id"], event["story_id"])].append(event)

    combinations = []
    counts = dict.fromkeys(Q_STATES, 0)
    for (user_id, story_id), (qualification, coverage, t0) in sorted(members.items()):
        end = None if t0 is None else window_end(t0, duration)
        member_events = grouped[(user_id, story_id)]
        within = [] if t0 is None else [
            event for event in member_events if in_window(event["event_time"], t0, end)
        ]
        early = [] if t0 is None else [
            event for event in member_events if event["event_time"] < t0
        ]
        if qualification == "unknown":
            state, reasons = "Q0", ["资格 unknown"]
        elif qualification == "qualified" and t0 is None:
            state, reasons = "Q0", ["qualified 但缺少必要资格时间"]
        elif qualification == "not_qualified":
            state, reasons = "Q1", ["明确 not_qualified"]
        elif not is_mature(snapshot, end):
            state, reasons = "Q2", ["观察窗口尚未成熟"]
        elif not coverage or early:
            state, reasons = "Q3", []
            if not coverage:
                reasons.append("coverage_complete=false，尚未证实窗口数据完整")
            if early:
                reasons.append("目标开始事件早于 t0，需要核查")
        elif within:
            state, reasons = "Q4", ["成熟、完整且无异常，窗内存在有效开始"]
        else:
            state, reasons = "Q5", ["成熟、完整且无异常，窗内没有有效开始"]
        counts[state] += 1
        combinations.append({
            "user_id": user_id, "story_id": story_id,
            "t0": format_utc(t0), "window_end": format_utc(end),
            "state": state, "reasons": reasons,
            "visible_start_count": len(member_events),
            "window_visible_start_count": len(within),
            "early_event_ids": [event["event_id"] for event in early],
        })

    numerator = counts["Q5"]
    denominator = counts["Q4"] + numerator
    rate = numerator / denominator if denominator else None
    return {
        "metric": "M03", "as_of": format_utc(snapshot),
        "window_hours": duration.total_seconds() / 3600,
        "input_population_count": len(population), "input_event_rows": len(start_events),
        "visible_event_rows": visible_rows, "deduplicated_event_count": len(events),
        "combinations": combinations, "state_counts": counts,
        "numerator": numerator, "denominator": denominator, "rate": rate,
        "status": "不可计算" if rate is None else "可计算",
        "display_rate": None if rate is None else f"{rate:.2%}",
    }
