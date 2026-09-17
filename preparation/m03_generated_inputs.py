"""Observed-only input adapter. No generator configuration or private ledger access."""

import json
from pathlib import Path

from analysis_core.temporal import InputError
from preparation.m03_observation import evaluate_m03


FIELDS = {
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


def check_fields(name, row):
    if not isinstance(row, dict) or set(row) != set(FIELDS[name].split()):
        raise InputError(f"observed_field_whitelist: {name}: {sorted(row)}")


class ObservedInputs:
    """Call after full global row/join validation; Task05 runner enforces that order."""
    def __init__(self, observed, business):
        self.path, self.business = Path(observed).resolve(), business
        if any(part.casefold() == "private_eval" for part in self.path.parts):
            raise InputError("adapter_read_boundary: 不读取 private_eval")
        if {p.name for p in self.path.iterdir()} != {n + ".jsonl" for n in FIELDS}:
            raise InputError("adapter_read_boundary: 必须是九表 observed 目录")
        self.data = {n: [] for n in FIELDS if n != "session_uploads"}
        for name in FIELDS:
            with (self.path / (name + ".jsonl")).open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    check_fields(name, row)
                    if name in self.data:
                        self.data[name].append(row)
        self.attrs = {r["user_id"]: r for r in self.data["player_attributes"]}
        self.qualifications, self.starts = {}, {}
        for name, target in (("qualification_checks", self.qualifications), ("story_start_uploads", self.starts)):
            for row in self.data[name]:
                target.setdefault((row["user_id"], row["story_id"]), []).append(row)

    def batches(self, version, as_of, batch_size=100):
        for calendar in self.data["story_calendar"]:
            if calendar["version_id"] != version:
                continue
            region, story = calendar["region_id"], calendar["story_id"]
            required = self.business["m03_source_bindings"][region]
            selected = [p for p in self.data["players"] if self.attrs[p["user_id"]]["region_id"] == region
                        and p["registered_at"] <= calendar["region_open_at"]]
            collection = [r for r in self.data["collection_checks"] if r["source_id"] in required]
            watermarks = [r for r in self.data["watermark_checks"] if r["source_id"] in required]
            # Keep all versions, including excluded future records; Task03 selects by snapshot.
            for offset in range(0, len(selected), batch_size):
                targets, qualifications, starts = [], [], []
                for player in selected[offset:offset + batch_size]:
                    key = (player["user_id"], story)
                    targets.append({"user_id": key[0], "story_id": story, "region_open_at": calendar["region_open_at"],
                                    "required_source_ids": required})
                    qualifications.extend(self.qualifications.get(key, []))
                    starts.extend({k: r[k] for k in ("event_id", "user_id", "story_id", "event_time", "available_at")}
                                  for r in self.starts.get(key, []))
                inputs = {"targets": targets, "qualification_checks": qualifications, "collection_checks": collection,
                          "watermark_checks": watermarks, "start_events": starts, "as_of": as_of}
                yield region, inputs, evaluate_m03(**inputs)
