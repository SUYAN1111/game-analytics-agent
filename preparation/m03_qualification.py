"""M03 资格适配：不撤销资格的固定来源契约，不推导覆盖证明。"""

from copy import deepcopy

from analysis_core.temporal import InputError, format_utc, parse_utc, require_id
from metrics.m03 import calculate_m03


COVERAGE_SOURCE = "固定样例显式输入，本轮未验证覆盖证据"
TARGET_FIELDS = {"user_id", "story_id", "region_open_at", "coverage_complete"}
CHECK_FIELDS = {"record_id", "user_id", "story_id", "checked_at", "state",
                "prereq_met_at", "available_at"}


def _validate_fields(row, fields, context):
    if not isinstance(row, dict) or set(row) != fields:
        raise InputError(f"{context}: 非法字段，必须且只能包含 {sorted(fields)!r}")


def _serialize_record(row):
    return {field: format_utc(value) if field in ("checked_at", "prereq_met_at", "available_at") else value
            for field, value in row.items()}


def prepare_population(targets, qualification_checks, as_of):
    """返回 population、逐组合审计及资格记录计数；不计算 Q 状态或比例。

    所有行先校验。跨组合复用 record_id 属于结构错误，即使行尚不可见也报错。
    同组合内的内容冲突仅在当前可见行中判断；不同内容保留各自最早可见重传。
    """
    snapshot = parse_utc(as_of, "as_of")
    if not isinstance(targets, list) or not isinstance(qualification_checks, list):
        raise InputError("targets 和 qualification_checks 必须为列表")
    members, sources, visible_by_key = {}, {}, {}
    for index, target in enumerate(targets):
        context = f"targets[{index}]"
        _validate_fields(target, TARGET_FIELDS, context)
        key = (require_id(target, "user_id", context), require_id(target, "story_id", context))
        if key in members:
            raise InputError(f"{context}: 重复候选组合 {key!r}")
        if type(target["coverage_complete"]) is not bool:
            raise InputError(f"{context}.coverage_complete: 必须为布尔值")
        opened = parse_utc(target["region_open_at"], f"{context}.region_open_at")
        members[key] = (target, opened)
        sources[key], visible_by_key[key] = [], []

    id_owners = {}
    visible_rows, visible_ids = 0, set()
    for index, raw in enumerate(qualification_checks):
        context = f"qualification_checks[{index}]"
        _validate_fields(raw, CHECK_FIELDS, context)
        record_id = require_id(raw, "record_id", context)
        key = (require_id(raw, "user_id", context), require_id(raw, "story_id", context))
        if key not in members:
            raise InputError(f"{context}: 资格记录越界组合 {key!r}")
        if record_id in id_owners and id_owners[record_id] != key:
            raise InputError(f"{context}: record_id={record_id!r} 跨不同组合使用")
        id_owners[record_id] = key
        state = raw["state"]
        if state not in ("met", "not_met"):
            raise InputError(f"{context}.state: 只能为 met 或 not_met")
        checked = parse_utc(raw["checked_at"], f"{context}.checked_at")
        available = parse_utc(raw["available_at"], f"{context}.available_at")
        prereq = None
        if state == "met":
            prereq = parse_utc(raw["prereq_met_at"], f"{context}.prereq_met_at")
            if prereq > checked:
                raise InputError(f"{context}: 非法时间关系 prereq_met_at > checked_at")
        elif raw["prereq_met_at"] is not None:
            raise InputError(f"{context}: not_met 的 prereq_met_at 必须为空")
        if checked > available:
            raise InputError(f"{context}: 非法时间关系 checked_at > available_at")
        visible = checked <= snapshot and available <= snapshot
        sources[key].append({"input_row": index + 1, "record": deepcopy(raw), "visible": visible})
        if visible:
            visible_rows += 1
            visible_ids.add(record_id)
            visible_by_key[key].append({"record_id": record_id, "user_id": key[0], "story_id": key[1],
                                        "checked_at": checked, "state": state,
                                        "prereq_met_at": prereq, "available_at": available})

    population, audit = [], []
    qualification_counts = dict.fromkeys(("qualified", "unknown", "not_qualified"), 0)
    all_conflict_ids, conflict_combinations = set(), []
    for key, (target, opened) in sorted(members.items()):
        variants = {}
        for row in visible_by_key[key]:
            signature = (row["record_id"], row["checked_at"], row["state"], row["prereq_met_at"])
            if signature not in variants or row["available_at"] < variants[signature]["available_at"]:
                variants[signature] = row
        evidence = sorted(variants.values(), key=lambda row: (
            row["record_id"], row["checked_at"], row["state"],
            format_utc(row["prereq_met_at"]) or "", row["available_at"]))
        conflicts = []
        for record_id in sorted({row["record_id"] for row in evidence}):
            if sum(row["record_id"] == record_id for row in evidence) > 1:
                conflicts.append({"code": "same_id_content", "record_ids": [record_id],
                                  "reason": "同 record_id 可见记录的业务内容不同"})
        positives = [row for row in evidence if row["state"] == "met"]
        negatives = [row for row in evidence if row["state"] == "not_met"]
        positive_times = {row["prereq_met_at"] for row in positives}
        if len(positive_times) > 1:
            conflicts.append({"code": "different_first_met", "record_ids": sorted({row["record_id"] for row in positives}),
                              "reason": "可见 met 给出不同的首次满足时间"})
        contradicted = set()
        for positive in positives:
            for negative in negatives:
                if negative["checked_at"] >= positive["prereq_met_at"]:
                    contradicted.update((positive["record_id"], negative["record_id"]))
        if contradicted:
            conflicts.append({"code": "negative_after_met", "record_ids": sorted(contradicted),
                              "reason": "存在 checked_at >= 首次满足时间的 not_met"})
        conflict_ids = sorted({record_id for conflict in conflicts for record_id in conflict["record_ids"]})
        if conflicts:
            all_conflict_ids.update(conflict_ids)
            conflict_combinations.append({"user_id": key[0], "story_id": key[1]})

        # 有任何当前证据冲突时，不把某一正面证据当作已确认的首次满足。
        prereq = next(iter(positive_times)) if positives and not conflicts else None
        first_available = min(row["available_at"] for row in positives) if prereq is not None else None
        t0 = max(opened, prereq) if prereq is not None else None
        if opened > snapshot:
            status, reason_code, reason = "not_qualified", "not_open", "已知区域剧情尚未开放"
        elif conflicts:
            status, reason_code, reason = "unknown", "evidence_conflict", "已开放，但可见资格证据冲突"
        elif prereq is not None:
            status, reason_code, reason = "qualified", "consistent_met", "已开放，来源一致确认首次全部满足前置及权限"
        elif any(row["checked_at"] == snapshot for row in negatives):
            status, reason_code, reason = "not_qualified", "current_not_met", "查询时点的可见 not_met 确认尚未全部满足"
        else:
            status, reason_code, reason = "unknown", "insufficient_evidence", "无当前正面证据；无记录或仅历史 not_met 不能外推当前资格"
        qualification_counts[status] += 1
        calculator_row = {
            "user_id": key[0], "story_id": key[1], "qualification_status": status,
            "region_open_at": target["region_open_at"],
            "prereq_met_at": format_utc(prereq) if status == "qualified" else None,
            "coverage_complete": target["coverage_complete"],
        }
        population.append(calculator_row)
        audit.append({
            "user_id": key[0], "story_id": key[1], "region_open_at": target["region_open_at"],
            "qualification_status": status, "prereq_met_at": format_utc(prereq), "t0": format_utc(t0),
            "first_visible_met_available_at": format_utc(first_available),
            "supporting_record_ids": sorted({row["record_id"] for row in evidence} - set(conflict_ids)),
            "conflict_record_ids": conflict_ids, "conflicts": conflicts,
            "reason_code": reason_code, "reasons": [reason] + [item["reason"] for item in conflicts],
            "visible_records": [_serialize_record(row) for row in evidence],
            "source_records": sources[key],
            "coverage_complete": target["coverage_complete"], "coverage_source": COVERAGE_SOURCE,
            "adaptation_reason": "保留真实开放时间；非 qualified 的计算器 prereq_met_at 置空，来源值保留于审计",
        })
    return {
        "population": population, "audit": audit, "qualification_counts": qualification_counts,
        "qualification_record_counts": {"input_rows": len(qualification_checks), "visible_rows": visible_rows,
                                        "visible_record_id_count": len(visible_ids),
                                        "excluded_rows": len(qualification_checks) - visible_rows},
        "conflict_record_ids": sorted(all_conflict_ids), "conflict_combinations": conflict_combinations,
    }


def evaluate_m03(targets, qualification_checks, start_events, as_of):
    """唯一业务计算仍由 Task01 执行；任何输入错误向调用方传播。"""
    prepared = prepare_population(targets, qualification_checks, as_of)
    m03 = calculate_m03(prepared["population"], start_events, as_of)
    return {**prepared, "m03": m03}
