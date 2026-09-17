"""M03 资格、观察证据与原计算器的薄适配层。"""

from copy import deepcopy
from datetime import timedelta

from analysis_core.coverage import assess_coverage, prepare_evidence, validate_sources
from analysis_core.temporal import InputError, format_utc, parse_utc, require_id, window_end
from metrics.m03 import calculate_m03
from preparation.m03_qualification import prepare_population


TARGET_FIELDS = frozenset(("user_id", "story_id", "region_open_at", "required_source_ids"))
COVERAGE_SOURCE = "本次可见采集区间检查及交付水位证据；未验证真实上游声明"
PLACEHOLDER = "Task02 资格接口占位 false，仅用于资格推导，不是最终覆盖结论或已验证证据"


def evaluate_m03(targets, qualification_checks, collection_checks, watermark_checks, start_events, as_of):
    parse_utc(as_of, "as_of")
    if not isinstance(targets, list):
        raise InputError("targets: 必须是列表")
    bindings, qualification_targets = {}, []
    for index, row in enumerate(targets):
        context = f"targets[{index}]"
        if isinstance(row, dict) and "coverage_complete" in row:
            raise InputError(f"{context}: 外部不得提供 coverage_complete")
        if not isinstance(row, dict) or set(row) != TARGET_FIELDS:
            raise InputError(f"{context}: 字段必须为 {sorted(TARGET_FIELDS)}")
        key = (require_id(row, "user_id", context), require_id(row, "story_id", context))
        if key in bindings:
            raise InputError(f"{context}: 重复候选组合 {key!r}")
        parse_utc(row["region_open_at"], f"{context}.region_open_at")
        bindings[key] = validate_sources(row["required_source_ids"], f"{context}.required_source_ids")
        qualification_targets.append({"user_id": key[0], "story_id": key[1],
                                      "region_open_at": row["region_open_at"], "coverage_complete": False})
    prepared = prepare_population(qualification_targets, qualification_checks, as_of)
    evidence = prepare_evidence(collection_checks, watermark_checks, as_of)
    population = deepcopy(prepared["population"])
    audit_by_key = {(row["user_id"], row["story_id"]): row for row in prepared["audit"]}
    qualification_audit, observation_audit = [], []
    for row in population:
        key = (row["user_id"], row["story_id"])
        qualification = deepcopy(audit_by_key[key])
        qualification.pop("coverage_complete")
        qualification.pop("coverage_source")
        qualification["interface_placeholder"] = {"coverage_complete": False, "reason": PLACEHOLDER}
        qualification_audit.append(qualification)
        if row["qualification_status"] == "qualified":
            start = parse_utc(qualification["t0"], "qualification.t0")
            coverage = assess_coverage(format_utc(start), format_utc(window_end(start, timedelta(hours=72))),
                                       bindings[key], evidence)
        else:
            coverage = {"status": "not_applicable", "coverage_complete": False,
                        "window_start": None, "window_end": None, "required_source_ids": bindings[key],
                        "sources": [], "reason_codes": ["qualification_not_confirmed"],
                        "reasons": ["资格未确认为 qualified，不创建有效观察窗口"]}
        row["coverage_complete"] = coverage["coverage_complete"]
        observation_audit.append({"user_id": key[0], "story_id": key[1],
                                  "qualification_status": row["qualification_status"],
                                  "coverage_source": COVERAGE_SOURCE, "coverage": coverage})
    result = calculate_m03(population, start_events, as_of)
    return {"population": population, "qualification_audit": qualification_audit,
            "observation_audit": observation_audit, "coverage_evidence": evidence,
            "qualification_counts": prepared["qualification_counts"],
            "qualification_record_counts": prepared["qualification_record_counts"],
            "qualification_conflict_record_ids": prepared["conflict_record_ids"],
            "qualification_conflict_combinations": prepared["conflict_combinations"], "m03": result}
