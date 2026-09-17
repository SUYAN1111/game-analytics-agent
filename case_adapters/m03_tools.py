"""M03 bridge. Reuses accepted qualification/coverage/Q code; no label or X reads."""

import os
from datetime import timedelta
from pathlib import Path
from analysis_tools.contracts import append, digest, read, require, write
from analysis_tools.aggregation import aggregate
from analysis_core.coverage import assess_coverage, prepare_evidence
from features.contract import format_utc, time
from features.observed import ObservedIndex, select_metadata
from features.m03_build import candidates
from features.m03_history import qualify, story_state
from preparation.m03_observation import evaluate_m03


def compact_coverage(value):
    if value is None:
        return {"status": "not_applicable", "coverage_complete": False, "sources": []}
    keep = ("source_id", "status", "coverage_complete", "merged_complete_intervals", "uncovered_intervals",
            "known_gaps", "max_complete_checked_at", "watermark_reaches_window_end",
            "watermark_follows_confirmation", "reason_codes", "reasons")
    return {**{k: value[k] for k in ("status", "coverage_complete", "window_start", "window_end", "reason_codes")},
            "sources": [{**{k: source[k] for k in keep}, "latest_watermark": source["latest_watermark"]}
                        for source in value["sources"]]}


class M03Backend:
    def __init__(self, gate, definition, audit, progress):
        self.gate, self.definition, self.audit, self.progress = gate, definition, Path(audit), progress
        self.records, self.counts, self.source_profiles = [], {}, {}
        self.index = None
        self.ready, self.failed = False, False

    def build(self):
        if self.ready:
            self.gate.verify("mature_backend")
            return
        require(not self.failed, "data_error", "failed backend must be restarted; partial materialization cannot be reused")
        self.failed = True
        paths = [self.gate.path("observed:"+name, "mature_backend") for name in
                 ("players", "player_attributes", "story_calendar", "source_catalog", "qualification_checks",
                  "collection_checks", "watermark_checks", "session_uploads", "story_start_uploads")]
        require(len({p.parent for p in paths}) == 1, "integrity_error", "observed resource roots differ")
        contract = read(self.gate.path("feature_contract", "mature_backend"))
        self.index = ObservedIndex(paths[0].parent, self.audit.parent / "indexes/observed.sqlite", contract, progress=self.progress)
        try:
            all_candidates = candidates(self.index)
            keys = {(r["user_id"], r["story_id"]) for r in all_candidates}
            require(all((r["user_id"], r["story_id"]) in keys for r in self.index.tables["qualification_checks"]),
                    "data_error", "qualification outside complete candidate list")
            require(all((r["user_id"], r["story_id"]) in keys for r in self.index.tables["story_start_uploads"]),
                    "data_error", "start event outside complete candidate list")
            for version, as_of in self.definition["snapshots"].items():
                ev = prepare_evidence(self.index.tables["collection_checks"], self.index.tables["watermark_checks"], as_of)
                self.source_profiles[version] = ev
                write(self.audit / "coverage_sources" / (version+".json"), ev)
                stories = {r["story_id"] for r in all_candidates if r["version_id"] == version}
                uploads = [r for r in self.index.tables["story_start_uploads"] if r["story_id"] in stories]
                visible = [r for r in uploads if time(r["event_time"]) <= time(as_of) and time(r["available_at"]) <= time(as_of)]
                qualifications = [r for r in self.index.tables["qualification_checks"] if r["story_id"] in stories]
                visible_qualifications = [r for r in qualifications if time(r["checked_at"]) <= time(as_of) and time(r["available_at"]) <= time(as_of)]
                self.counts[version] = {"start_events": {"input_event_rows": len(uploads), "visible_event_rows": len(visible),
                        "deduplicated_event_count": len({r["event_id"] for r in visible})},
                    "qualification_checks": {"input_rows":len(qualifications),"visible_rows":len(visible_qualifications),
                        "visible_record_id_count":len({r["record_id"] for r in visible_qualifications}),
                        "excluded_rows":len(qualifications)-len(visible_qualifications)},
                    "collection_checks": ev["collection"]["counts"], "watermark_checks": ev["watermarks"]["counts"]}
            # Player-first iteration reuses the existing bounded session cache.
            for number, candidate in enumerate(sorted(all_candidates, key=lambda r: (r["user_id"], r["version_id"])), 1):
                uid, story, version = (candidate[k] for k in ("user_id", "story_id", "version_id"))
                as_of = self.definition["snapshots"][version]
                state = story_state(self.index, candidate, as_of)
                population, qualification = qualify(self.index, candidate, as_of)
                coverage = None
                if state["qualification_status"] == "qualified":
                    # Compact cached profile is the accepted coverage input; full versions are saved once above.
                    profile, _, _ = self.index.profile(state["source_id"], as_of)
                    coverage = assess_coverage(state["t0"], state["window_end"], [state["source_id"]], profile)
                population["coverage_complete"] = state["coverage_complete"]
                qualification.pop("coverage_complete", None)
                qualification.pop("coverage_source", None)
                qualification["interface_placeholder"] = {"coverage_complete": False,
                    "reason": "Task02 interface placeholder only; final coverage comes from collection and watermark evidence"}
                when = state["t0"] if state["qualification_status"] == "qualified" else as_of
                attr = select_metadata(self.index.by_user["player_attributes"][uid], when, "attribute")
                attrs = self.index.by_user["player_attributes"][uid]
                require(len({(a["region_id"], a["language"], a["client"]) for a in attrs}) == 1,
                        "data_error", "main-case attributes changed")
                registered = self.index.by_user["players"][uid][0]["registered_at"]
                new_player = "not_applicable" if state["state"] in ("Q0", "Q1") else int(time(state["t0"])-time(registered) < timedelta(days=7))
                record = {**candidate, **state, "language": attr["language"], "client": attr["client"],
                          "new_player": new_player, "attribute_as_of": when, "registered_at": registered,
                          "population": population, "qualification": qualification,
                          "coverage": compact_coverage(coverage), "coverage_source_ref": version,
                          "coverage_source": "visible collection intervals and delivery watermark evidence"}
                self.records.append(record)
                if os.environ.get("APP_DEBUG")=="1":append(self.audit / "candidates.jsonl", record)
                if number % 500 == 0:
                    self.progress(f"M03 registered calculation {number}/{len(all_candidates)} candidates")
            self.records.sort(key=lambda r: (r["version_id"], r["user_id"], r["story_id"]))
            self.gate.verify("mature_backend")
            self.ready, self.failed = True, False
        finally:
            self.index.close()
            self.index = None

    def query(self, versions, dimension):
        self.build()
        table_id = "aggregate_" + digest([self.definition["identities"], versions, dimension])[:24]
        state, result = aggregate(self.records, versions, dimension, table_id,
                                  self.definition["metric"]["minimum_mature_group_size"])
        return state, {"kind": "mature_metric", "versions": versions, "group_by": dimension,
                       "definition": self.definition["metric"], "snapshots": {v:self.definition["snapshots"][v] for v in versions},
                       "rows": result, "event_and_evidence_counts": {v:self.counts[v] for v in versions},
                       "query_origin": "registered_python", "function": "features.m03_history.story_state",
                       "audit_artifact": {"access": "controller_only", "kind": "candidate_and_coverage_audit"}}

    def close(self):
        if self.index is not None:
            self.index.close()


class FixtureBackend:
    """Only the check controller can construct this host; no public fixture switch."""
    def __init__(self, bundle, definition, audit):
        self.bundle, self.definition, self.audit = bundle, definition, Path(audit)
        self.records = []
        self.actual = None

    def build(self):
        if self.actual is not None:
            return
        self.actual = evaluate_m03(**self.bundle["input"])
        attrs = self.bundle["attributes"]
        pops = {(r["user_id"], r["story_id"]): r for r in self.actual["population"]}
        for state in self.actual["m03"]["combinations"]:
            uid = state["user_id"]
            attr = attrs[uid]
            population = pops[uid, state["story_id"]]
            self.records.append({**state, "version_id": self.bundle.get("version_id", "V1"),
                "qualification_status": population["qualification_status"], "population": population,
                "region_id": attr["region_id"], "language": attr["language"], "client": attr["client"],
                "new_player": "not_applicable" if state["state"] in ("Q0", "Q1") else
                    int(time(state["t0"])-time(attr["registered_at"]) < timedelta(days=7))})
        write(self.audit / "fixture_actual.json", self.actual)

    def query(self, versions, dimension):
        self.build()
        state, result = aggregate(self.records, versions, dimension, "fixture_observed",
                                  0 if self.bundle.get("allow_small_groups", True) else 20)
        return state, {"kind": "mature_metric", "versions": versions, "group_by": dimension,
            "definition": self.definition["metric"], "snapshots": {v:self.bundle["input"]["as_of"] for v in versions},
            "rows": result, "event_and_evidence_counts": {"fixture": {"start_events": {k:self.actual["m03"][k]
                for k in ("input_event_rows", "visible_event_rows", "deduplicated_event_count")},
                "qualification_checks": self.actual["qualification_record_counts"],
                "collection_checks": self.actual["coverage_evidence"]["collection"]["counts"],
                "watermark_checks": self.actual["coverage_evidence"]["watermarks"]["counts"]}},
            "query_origin": "registered_python", "function": "preparation.m03_observation.evaluate_m03",
            "audit_artifact": {"access": "controller_only", "kind": "fixture_audit"}}

    def close(self):
        pass
