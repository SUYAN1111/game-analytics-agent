"""The sole tool dispatch implementation used by direct and MCP transports."""

import time
import traceback
from pathlib import Path
from uuid import uuid4
from analysis_tools.contracts import ToolError, ERRORS, append, digest, now, require, validate
from analysis_tools.evidence import EvidenceStore
from analysis_tools.aggregation import compare


class Service:
    def __init__(self, registry, gate, backend, predictor, cards, directory, session_id=None):
        self.registry, self.gate, self.backend, self.predictor, self.cards = registry, gate, backend, predictor, cards
        self.directory = Path(directory)
        self.session_id = session_id or "session" + uuid4().hex
        self.evidence = EvidenceStore(self.directory / "public_evidence", registry, self.session_id)

    def catalog(self):
        return [{"name": k, **v} for k, v in self.registry.schemas["tools"].items()]

    def dispatch(self, tool_name, arguments, *, transport="direct"):
        began, started, request_id = time.perf_counter(), now(), "req" + uuid4().hex
        validated, data, error, evidence_id, warnings, state = None, None, None, None, [], "internal_error"
        fingerprint = None
        try:
            require(tool_name in self.registry.schemas["tools"], "not_found", "tool is not registered")
            validated = self.registry.bind(tool_name, validate(self.registry.schemas["tools"][tool_name]["input_schema"], arguments))
            self.gate.verify("host_context")
            parents = []
            d = self.registry.definition
            if tool_name == "inspect_context":
                data = {"case_id": d["case_id"], "metric_id": d["metric_id"], "model_id": d["model_id"],
                        "metric_definition": d["metric"], "public_context": d["public_context"],
                        "snapshot_set_id": d["snapshot_set_id"],
                        "snapshots": d["snapshots"], "cohorts": d["cohorts"], "prediction_cohorts": d["prediction_cohorts"],
                        "group_by": ["none", "region_id", "language", "client", "new_player"],
                        "role": self.registry.role, "tools": [item["name"] for item in self.catalog()],
                        "limitations": ["Fixed simulated observed data; no upstream collection proof", "72h only",
                            "Frozen t0 replay is not an actual historical deployment", "No arbitrary paths, SQL or per-person queries"]}
                state = "ok"
            elif tool_name in ("query_metric", "check_quality"):
                state, data = self.backend.query(d["cohorts"][validated["cohort_id"]], validated.get("group_by", "none"))
                if tool_name == "check_quality":
                    data = {**data, "kind": "quality", "quality_is_prerequisite": False,
                            "coverage_semantics": "(Q4+Q5)/(Q3+Q4+Q5); zero denominator=null"}
                if state == "partial":
                    warnings.append("Q0/Q2/Q3 remain; the computable subset is not the full candidate population")
                if state == "restricted_granularity":
                    warnings.append("Entire grouped view withheld: a mature group contains 1–19 candidates")
            elif tool_name == "predict_registered":
                require(self.predictor is not None, "unauthorized", "prediction not registered for this host")
                data = self.predictor.predict(d["prediction_cohorts"][validated["cohort_id"]], request_id)
                state = "ok"
                warnings.append("Frozen t0 replay; individual predictions are controller-only")
            elif tool_name == "read_model_card":
                require(self.registry.role in self.cards, "unauthorized", "model card role denied")
                self.gate.verify("card_reader")
                data = self.cards[self.registry.role]
                state = "ok"
            elif tool_name == "compare_results":
                self._fresh_evidence()
                left = self.evidence.get(validated["left_evidence_id"])
                right = self.evidence.get(validated["right_evidence_id"])
                data = compare(left["content"], right["content"])
                parents = [left["content_fingerprint"], right["content_fingerprint"]]
                data["parent_content_fingerprints"] = parents
                state = "partial" if any(x["content"]["status"] == "partial" for x in (left, right)) else "ok"
                # Parent IDs are instance lineage, stored in the call log, not semantic content.
            elif tool_name == "get_evidence":
                self._fresh_evidence()
                entry = self.evidence.get(validated["evidence_id"])
                data = {"verification_status": entry["verification_status"], "content_fingerprint": entry["content_fingerprint"],
                        "content": entry["content"]}
                parents = [entry["content_fingerprint"]]
                state = entry["content"]["status"]
            semantic_arguments = dict(validated)
            for field in ("left_evidence_id", "right_evidence_id", "evidence_id"):
                if field in semantic_arguments:
                    semantic_arguments[field] = parents[("left_evidence_id", "right_evidence_id").index(field)] if field != "evidence_id" else parents[0]
            evidence_id, fingerprint = self.evidence.create(tool_name, semantic_arguments, state, data, warnings, parents)
        except ToolError as exc:
            state = exc.code
            error = {"type": type(exc).__name__, "code": exc.code, "message": exc.reason}
            append(self.directory / "audit/errors.jsonl", {"request_id": request_id, "type": type(exc).__name__,
                   "message": str(exc), "traceback": traceback.format_exc()})
        except Exception as exc:
            # Detailed raw input/paths stay local; public errors never echo raw records or tracebacks.
            state = "data_error" if isinstance(exc, ValueError) else "internal_error"
            error = {"type": "ToolError", "code": state, "message": "registered computation failed; consult controller audit"}
            append(self.directory / "audit/errors.jsonl", {"request_id": request_id, "type": type(exc).__name__,
                   "message": str(exc), "traceback": traceback.format_exc()})
        result = {"request_id": request_id, "session_id": self.session_id, "tool_name": tool_name, "status": state,
                  "validated_arguments": validated, "data": data, "evidence_id": evidence_id,
                  "source_identities": self.registry.identities, "warnings": warnings, "error": error,
                  "runtime": {"transport": transport, "started_at": started, "executed_at": now(),
                              "elapsed_seconds": time.perf_counter()-began, "cache_hit": False,
                              "content_fingerprint": fingerprint}}
        append(self.directory / (transport+"_calls.jsonl"), {"arguments": arguments, "response": result})
        return result

    def _fresh_evidence(self):
        for purpose in ("mature_backend", "predictor", "card_reader"):
            self.gate.verify(purpose)

    def close(self):
        self.backend.close()
