"""Count-first aggregation and explicitly keyed comparisons."""

from collections import Counter
from analysis_tools.contracts import canonical, digest, require, status


def count_row(records, version, dimension, value, source_table_id):
    counts = Counter(r["state"] for r in records)
    q = {"Q" + str(i): counts["Q" + str(i)] for i in range(6)}
    n, d = q["Q5"], q["Q4"] + q["Q5"]
    matured = d + q["Q3"]
    comparison_key = canonical(["overall" if dimension == "none" else "group", dimension, value])
    row = {"row_key": canonical([version, comparison_key]), "comparison_key": comparison_key,
           "row_type": "overall" if dimension == "none" else "group", "version_id": version,
           "group_by": dimension, "group_value": value, "candidate_count": len(records), **q,
           "numerator": n, "denominator": d, "rate": n/d if d else None,
           "display_rate": f"{100*n/d:.2f}%" if d else None,
           "observation_coverage": d/matured if matured else None, "source_table_id": source_table_id}
    row["quality_status"] = status([row])
    return row


def aggregate(records, versions, dimension, source_table_id, minimum=20):
    output = []
    for version in list(versions) + (["+".join(versions)] if len(versions) > 1 else []):
        selected = [r for r in records if r["version_id"] in version.split("+")]
        output.append(count_row(selected, version, "none", None, source_table_id))
        if dimension != "none":
            values = sorted({r[dimension] for r in selected}, key=canonical)
            output.extend(count_row([r for r in selected if r[dimension] == value], version,
                                    dimension, value, source_table_id) for value in values)
    groups = [r for r in output if r["row_type"] == "group"]
    if any(0 < r["Q3"]+r["Q4"]+r["Q5"] < minimum for r in groups):
        return "restricted_granularity", []
    require(len({r["row_key"] for r in output}) == len(output), "data_error", "duplicate aggregate row key")
    return status([r for r in output if r["row_type"] == "overall"]), output


def compare(left, right):
    for item in (left, right):
        require(item["tool_name"] == "query_metric" and item["status"] != "restricted_granularity",
                "invalid_arguments", "comparison requires unrestricted metric evidence")
        require(len(item["data"]["versions"]) == 1, "invalid_arguments", "comparison requires single versions")
    a, b = left["data"], right["data"]
    require(left["source_identities"] == right["source_identities"] and a["definition"] == b["definition"]
            and a["group_by"] == b["group_by"], "unauthorized", "incompatible comparison context")
    require(a["versions"] != b["versions"], "invalid_arguments", "comparison requires different versions")
    sides = []
    for item in (a, b):
        mapping = {r["comparison_key"]: r for r in item["rows"]}
        require(len(mapping) == len(item["rows"]), "data_error", "duplicate comparison key")
        sides.append(mapping)
    result = []
    for key in sorted(set(sides[0]) | set(sides[1])):
        l, r = sides[0].get(key), sides[1].get(key)
        delta = None if l is None or r is None or l["rate"] is None or r["rate"] is None else r["rate"]-l["rate"]
        # Counts remain meaningful with a zero rate denominator, but a missing
        # group is unknown, not a group containing zero candidates.
        count_differences = {field: None if l is None or r is None else r[field]-l[field]
                             for field in ("candidate_count", "numerator", "denominator",
                                           "Q0", "Q1", "Q2", "Q3", "Q4", "Q5")}
        result.append({"comparison_key": key, "left_row_key": l["row_key"] if l else None,
                       "right_row_key": r["row_key"] if r else None, "left": l, "right": r,
                       "count_differences": count_differences,
                       "comparison_status": "missing_left" if l is None else "missing_right" if r is None else
                            "not_computable" if delta is None else "comparable",
                       "rate_difference": delta, "percentage_point_difference": None if delta is None else delta*100,
                       "display_percentage_point_difference": None if delta is None else f"{delta*100:.2f} pp"})
    return {"direction": "right_minus_left", "definition": a["definition"], "group_by": a["group_by"],
            "left_snapshots": a["snapshots"], "right_snapshots": b["snapshots"], "rows": result}
