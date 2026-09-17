"""Verify values AND rendered answer text against current-session public evidence.

Each body line is a whole fact reference or a fixed host note reference.
The host renders labels, scope, units and values together from checked evidence.
There is no independent model-authored prose in a reference-checked answer.
"""
import copy
import re
from decimal import Decimal, ROUND_HALF_UP
from agent_runtime.common import HostError, canonical, digest, require


# Presentation vocabulary, not an NLP classifier or an expected-answer table.
FIELD_LABELS = {
    "candidate_count": "候选组合数", "numerator": "分子（Q5）", "denominator": "分母（Q4+Q5）",
    **{f"Q{i}": f"Q{i}组合数" for i in range(6)},
    "rate": "实际观测M03比例", "observation_coverage": "观察覆盖比例",
    "rate_difference": "实际观测M03比例差", "percentage_point_difference": "实际观测M03百分点差",
    "mean_p": "冻结预测平均概率", "prediction_coverage": "预测覆盖比例",
    "expected_qualified_count": "应预测资格组合数", "predicted_count": "已预测组合数", "missing_count": "缺失预测组合数",
}
HOST_NOTES = {
    "limitations": "本结果仅描述固定模拟数据，不外推真实业务；引用核验不代表设计审核批准。",
    "causality": "观测差异不能确定原因，也不足以证明因果关系。",
    "unsupported": "当前工具不支持该请求的范围或能力，不能提供相应读数。",
}


def render_fact(checked, metric_id):
    """Called only after verify_claim; never take a label from free model text."""
    claim, scope = checked["claim"], checked["scope"]
    kind, field = claim["kind"], claim["meaning"]
    label = FIELD_LABELS[field]
    if kind.startswith("prediction_"):
        metric_type = "M03冻结预测重放（不是实际观测比例）"
        scope_text = (f"版本={scope['version_id']}；分组=整体资格队列；模型={scope['model_id']}；"
                      f"时间模式={scope['time_mode']}（冻结t0重放）")
    else:
        metric_type = "M03实际观测差值" if "difference" in kind else "M03实际观测统计"
        group = "整体" if scope["group_by"] == "none" else f"{scope['group_by']}={scope['group_value']}"
        version = (f"右版本={scope['right_version']} 减 左版本={scope['left_version']}（右减左）"
                   if "difference" in kind else f"版本={scope['version_id']}")
        scope_text = f"{version}；分组={group}；窗口={scope['window_hours']}小时"
        if "difference" in kind: label += "（右减左）"
    unit = {"count": "个用户×剧情组合", "percent": "%", "percentage_point": "个百分点"}[claim["display_unit"]]
    binding = {"metric_id": metric_id, "metric_type": metric_type, "kind": kind, "scope": copy.deepcopy(scope),
               "field": field, "field_label": label, "raw_unit": claim["raw_unit"], "raw_value": claim["value"],
               "display_unit": claim["display_unit"], "unit_label": unit, "precision": claim["precision"],
               "rendered_value": checked["rendered_value"], "evidence_id": claim["evidence_id"],
               "content_fingerprint": claim["content_fingerprint"], "pointer": claim["pointer"]}
    rendered = (f"{metric_type}｜{scope_text}｜{label} [{field}]：{checked['rendered_value']}"
                f"（单位：{unit}） {checked['citation']}")
    return {**checked, "binding": binding, "rendered_fact": rendered}


def pointer(value, path):
    require(type(path) is str and path.startswith("/"), "pointer", "JSON Pointer must be absolute")
    try:
        for piece in path[1:].split("/"):
            require(not re.search(r"~(?![01])", piece), "pointer", "invalid JSON Pointer escape")
            key = piece.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                require(re.fullmatch(r"0|[1-9]\d*", key), "pointer", "invalid array index")
                value = value[int(key)]
            else:
                value = value[key]
        return value
    except (KeyError, IndexError, TypeError) as exc:
        raise HostError("pointer", "evidence pointer does not exist") from exc


class EvidenceIndex:
    def __init__(self, definition, schemas):
        self.definition = definition
        self.registry_fingerprint = digest({"definition": definition, "schemas": schemas})
        self.session_id = None
        self.entries = {}

    def add(self, result):
        require(result["source_identities"] == self.definition["identities"], "identity", "tool source identity mismatch")
        if self.session_id is None:
            self.session_id = result["session_id"]
        require(result["session_id"] == self.session_id, "session", "cross-session evidence rejected")
        if result["error"] is not None:
            require(result["evidence_id"] is None, "evidence", "failed tool cannot supply successful evidence")
            return
        require(result["tool_name"] in ("inspect_context", "check_quality", "query_metric", "compare_results",
                "predict_registered", "read_model_card", "get_evidence"), "evidence", "unknown evidence producer")
        parents = []
        arguments = copy.deepcopy(result["validated_arguments"])
        for key in ("left_evidence_id", "right_evidence_id", "evidence_id"):
            if key in arguments:
                require(arguments[key] in self.entries, "evidence", "unknown or stale evidence parent")
                fp = self.entries[arguments[key]]["runtime"]["content_fingerprint"]
                arguments[key] = fp
                parents.append(fp)
        content = {"tool_name": result["tool_name"], "validated_arguments": arguments, "status": result["status"],
                   "data": result["data"], "warnings": result["warnings"], "source_identities": result["source_identities"],
                   "parent_content_fingerprints": parents, "registry_fingerprint": self.registry_fingerprint}
        require(digest(content) == result["runtime"]["content_fingerprint"], "fingerprint", "public evidence content fingerprint mismatch")
        require(result["evidence_id"] not in self.entries, "evidence", "duplicate evidence instance")
        self.entries[result["evidence_id"]] = copy.deepcopy(result)

    def resolve_selection(self, selection):
        """Resolve an explicit semantic selection; never repair a full claim.

        Only current-session, fingerprint-checked evidence admitted by add() is
        eligible. Row order is not a model input. Missing/ambiguous scope fails
        closed; value, fingerprint, units and pointer come from the host.
        The expanded claim still traverses the unchanged strict verifier.
        """
        require(type(selection) is dict and set(selection) == {"id", "evidence_id", "field", "scope"},
                "selection", "selection requires exactly id/evidence_id/field/scope; no numeric or pointer overrides")
        require(type(selection["id"]) is str and re.fullmatch(r"c[1-9]\d*", selection["id"]),
                "selection", "invalid selection ID")
        require(type(selection["evidence_id"]) is str and selection["evidence_id"] in self.entries,
                "evidence", "selection evidence not obtained in this MCP session")
        require(type(selection["field"]) is str and type(selection["scope"]) is dict,
                "selection", "selection field and scope have invalid types")
        evidence = self.entries[selection["evidence_id"]]
        require(evidence["error"] is None and evidence["status"] not in ("restricted_granularity", "empty"),
                "claim", "failed, withheld or empty evidence cannot produce a fact")
        tool, field = evidence["tool_name"], selection["field"]
        counts = {"candidate_count", "numerator", "denominator", "Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}
        if tool in ("query_metric", "check_quality"):
            kind = "count" if field in counts else {"rate": "metric_rate", "observation_coverage": "observation_coverage"}.get(field)
        elif tool == "compare_results":
            kind = "count_difference" if field in counts else {"rate_difference": "rate_difference",
                "percentage_point_difference": "percentage_point_difference"}.get(field)
        elif tool == "predict_registered":
            kind = "prediction_count" if field in {"expected_qualified_count", "predicted_count", "missing_count"} else {
                "mean_p": "prediction_probability", "prediction_coverage": "prediction_coverage"}.get(field)
        else:
            kind = None
        require(kind is not None, "selection", "field is not a permitted numeric fact of the selected tool")
        matches = []
        for index, row in enumerate(evidence["data"]["rows"]):
            if tool in ("query_metric", "check_quality"):
                scope = {"version_id": row["version_id"], "group_by": row["group_by"],
                         "group_value": row["group_value"], "window_hours": 72}
            elif tool == "compare_results":
                if row["left"] is None or row["right"] is None:
                    continue  # Never replace a missing comparison group with zero.
                scope = {"left_version": row["left"]["version_id"], "right_version": row["right"]["version_id"],
                         "group_by": row["left"]["group_by"], "group_value": row["left"]["group_value"], "window_hours": 72}
            else:
                scope = {"version_id": row["version_id"], "model_id": self.definition["model_id"],
                         "time_mode": "frozen_t0_replay"}
            if scope == selection["scope"]:
                matches.append((index, row, scope))
        require(len(matches) == 1, "selection_scope",
                "selection must identify exactly one evidence row by version/group/model scope")
        index, row, scope = matches[0]
        path = ("count_differences/" if kind == "count_difference" else "") + field
        value = pointer(evidence, f"/data/rows/{index}/" + path)
        integer = kind in ("count", "count_difference", "prediction_count")
        claim = {"id": selection["id"], "meaning": field, "kind": kind,
            "evidence_id": selection["evidence_id"], "content_fingerprint": evidence["runtime"]["content_fingerprint"],
            "pointer": f"/data/rows/{index}/" + path, "value": value,
            "raw_unit": "count" if integer else "percentage_point" if kind == "percentage_point_difference" else "ratio",
            "display_unit": "count" if integer else "percentage_point" if "difference" in kind else "percent",
            "precision": 0 if integer else 2, "scope": scope}
        checked = self.verify_claim(claim)
        return {**checked, "input_contract": "semantic_selection_v1", "selection": copy.deepcopy(selection)}

    def verify_claim(self, claim):
        fields = {"id", "meaning", "kind", "evidence_id", "content_fingerprint", "pointer", "value",
                  "raw_unit", "display_unit", "precision", "scope"}
        require(type(claim) is dict and set(claim) == fields, "claim", "claim fields differ from contract")
        require(re.fullmatch(r"c[1-9]\d*", claim["id"] or ""), "claim", "invalid claim ID")
        require(claim["evidence_id"] in self.entries, "evidence", "claim evidence not obtained in this MCP session")
        evidence = self.entries[claim["evidence_id"]]
        require(claim["content_fingerprint"] == evidence["runtime"]["content_fingerprint"], "fingerprint", "claim fingerprint mismatch")
        require(evidence["status"] not in ("restricted_granularity", "empty"), "claim", "withheld or empty evidence")
        path = claim["pointer"]
        match = re.fullmatch(r"/data/rows/(0|[1-9]\d*)/(count_differences/)?([A-Za-z0-9_]+)", path)
        require(match is not None, "pointer", "claim must reference a registered aggregate row value")
        row = pointer(evidence, "/data/rows/" + match[1])
        value = pointer(evidence, path)
        # JSON through JavaScript may render the ratio 1.0 as 1. Preserve its
        # numeric value and semantic unit; integer counts remain strictly ints below.
        require(type(value) in (int, float) and type(claim["value"]) in (int, float) and value == claim["value"],
                "value", "claim raw numeric value differs from evidence")
        tool, leaf = evidence["tool_name"], match[3]
        count_fields = {"candidate_count", "numerator", "denominator", "Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}
        if tool in ("query_metric", "check_quality"):
            kind = "count" if leaf in count_fields else "metric_rate" if leaf == "rate" else "observation_coverage" if leaf == "observation_coverage" else None
            scope = {"version_id": row["version_id"], "group_by": row["group_by"], "group_value": row["group_value"], "window_hours": 72}
        elif tool == "compare_results":
            require(row["left"] is not None and row["right"] is not None, "scope", "missing comparison group")
            kind = "count_difference" if match[2] and leaf in count_fields else "rate_difference" if leaf == "rate_difference" else "percentage_point_difference" if leaf == "percentage_point_difference" else None
            scope = {"left_version": row["left"]["version_id"], "right_version": row["right"]["version_id"],
                     "group_by": row["left"]["group_by"], "group_value": row["left"]["group_value"], "window_hours": 72}
        elif tool == "predict_registered":
            kind = "prediction_probability" if leaf == "mean_p" else "prediction_coverage" if leaf == "prediction_coverage" else "prediction_count" if leaf in ("expected_qualified_count", "predicted_count", "missing_count") else None
            scope = {"version_id": row["version_id"], "model_id": self.definition["model_id"], "time_mode": "frozen_t0_replay"}
        else:
            kind, scope = None, None
        require(kind is not None and claim["kind"] == kind and claim["scope"] == scope, "scope", "claim kind or version/group/model scope differs")
        require(claim["meaning"] == leaf, "meaning", "claim meaning must name the actual evidence field")
        integer = kind in ("count", "count_difference", "prediction_count")
        if integer:
            require(type(value) is int and type(claim["value"]) is int, "value", "count claims require native integers")
        raw_unit = "count" if integer else "percentage_point" if kind == "percentage_point_difference" else "ratio"
        require(claim["raw_unit"] == raw_unit, "unit", "wrong raw unit")
        permitted = ("count",) if integer else ("percentage_point",) if "difference" in kind else ("percent",)
        require(claim["display_unit"] in permitted, "unit", "display unit does not match semantic kind")
        require(type(claim["precision"]) is int and claim["precision"] == (0 if integer else 2), "precision", "counts use 0 and rates use 2 decimal places")
        amount = Decimal(str(value))
        if claim["display_unit"] in ("percent", "percentage_point") and raw_unit == "ratio":
            amount *= 100
        text = format(amount.quantize(Decimal(1).scaleb(-claim["precision"]), rounding=ROUND_HALF_UP), "f")
        suffix = "" if integer else "个百分点" if claim["display_unit"] == "percentage_point" else "%"
        return {"claim": claim, "rendered_value": text+suffix, "verification_status": "reference_checked_candidate",
                "citation": f"[{claim['evidence_id']} {path}]", "scope": scope}

    def verify_answer(self, text):
        try:
            answer = __import__("json").loads(text)
        except (ValueError, TypeError) as exc:
            raise HostError("answer_json", "final response must be ordinary JSON, without fences") from exc
        require(type(answer) is dict and set(answer) == {"answer_markdown", "claims"}, "answer", "final JSON fields invalid")
        prose, claims = answer["answer_markdown"], answer["claims"]
        require(type(prose) is str and type(claims) is list, "answer", "answer field types invalid")
        checked = [render_fact(self.resolve_selection(c) if type(c) is dict and "field" in c else self.verify_claim(c),
                               self.definition["metric_id"]) for c in claims]
        mapping = {c["claim"]["id"]: c for c in checked}
        require(len(mapping) == len(claims), "claim", "duplicate claim ID")
        # Whole-line grammar prevents headings, prefixes, metadata, Markdown and
        # otherwise nonnumeric prose from relabelling an independently valid fact.
        blocks = [line.strip() for line in prose.splitlines() if line.strip()]
        require(bool(blocks), "answer_body", "answer requires a whole fact or host note block")
        used, rendered = [], []
        for block in blocks:
            fact = re.fullmatch(r"\{\{claim:(c[1-9]\d*)\}\}", block)
            note = re.fullmatch(r"\{\{note:([a-z_]+)\}\}", block)
            if fact:
                require(fact[1] in mapping, "answer", "body references an unknown claim")
                used.append(fact[1]); rendered.append(mapping[fact[1]]["rendered_fact"])
            elif note and note[1] in HOST_NOTES:
                rendered.append(HOST_NOTES[note[1]])
            else:
                raise HostError("answer_body", "body must contain only whole claim or registered note blocks; independent labels, metadata and prose are forbidden")
        require(len(used) == len(mapping) and set(used) == set(mapping), "answer", "each verified fact must occur exactly once")
        if HOST_NOTES["limitations"] not in rendered: rendered.append(HOST_NOTES["limitations"])
        return {"answer_markdown": "\n\n".join(rendered), "claims": checked, "status": "reference_checked_candidate",
                "presentation_contract": "host_bound_facts_v1",
                "limitations": "Evidence-bound facts rendered by host; no free model prose is accepted. This is not causal or design approval."}
