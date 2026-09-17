"""UTC 时间、半开窗口及快照事件处理；仅使用标准库。"""

import re
from datetime import datetime, timedelta, timezone


class InputError(ValueError):
    """输入不符合约定，调用方不得据此输出成功指标。"""


_UTC_ISO = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)"
)


def parse_utc(value, field):
    """接受带 Z 或 +00:00 的 ISO 8601，拒绝无时区或非 UTC 时间。"""
    if not isinstance(value, str) or not _UTC_ISO.fullmatch(value):
        raise InputError(f"{field}: 必须是带 UTC 时区的 ISO 8601 时间，收到 {value!r}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError(f"{field}: 非法时间 {value!r}: {exc}") from exc


def format_utc(value):
    return None if value is None else value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_duration(duration):
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise InputError("窗口长度必须为正 timedelta")


def window_end(start, duration):
    """窗口长度由调用方提供，不包含默认业务时长。"""
    validate_duration(duration)
    try:
        return start + duration
    except OverflowError as exc:
        raise InputError("窗口终点超出可表示的时间范围") from exc


def in_window(event_time, start, end):
    return start <= event_time < end


def is_mature(as_of, end):
    return as_of >= end


def require_id(row, field, context):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{context}.{field}: 必须为非空字符串")
    return value


def visible_unique_events(start_events, population_keys, as_of):
    """校验所有输入行，先按双时间筛选，再检查可见事件的同 ID 重传。

    不可见行仍须时间合法且可关联研究对象；其 ID 冲突不参与当前快照。
    同 ID 业务内容指 user_id、story_id 和解析后的 event_time。
    """
    if not isinstance(start_events, list):
        raise InputError("start_events: 必须为列表")
    visible = []
    for index, row in enumerate(start_events):
        context = f"start_events[{index}]"
        if not isinstance(row, dict):
            raise InputError(f"{context}: 必须为对象")
        event_id = require_id(row, "event_id", context)
        user_id = require_id(row, "user_id", context)
        story_id = require_id(row, "story_id", context)
        if (user_id, story_id) not in population_keys:
            raise InputError(f"{context}: 事件无法关联研究对象 {(user_id, story_id)!r}")
        event_time = parse_utc(row.get("event_time"), f"{context}.event_time")
        available_at = parse_utc(row.get("available_at"), f"{context}.available_at")
        if event_time <= as_of and available_at <= as_of:
            visible.append({"event_id": event_id, "user_id": user_id,
                            "story_id": story_id, "event_time": event_time,
                            "available_at": available_at})

    unique = {}
    for event in visible:
        event_id = event["event_id"]
        previous = unique.get(event_id)
        if previous is not None:
            fields = ("user_id", "story_id", "event_time")
            if any(previous[field] != event[field] for field in fields):
                raise InputError(f"event_id={event_id!r}: 同 ID 业务内容冲突（user_id/story_id/event_time）")
            # 保留最早可用的重传，使返回内容不依赖输入顺序。
            if event["available_at"] < previous["available_at"]:
                unique[event_id] = event
        else:
            unique[event_id] = event
    return sorted(unique.values(), key=lambda event: event["event_id"]), len(visible)
