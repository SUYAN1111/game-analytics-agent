"""One observed-only SQLite session index; source profiles keyed by visible versions."""

import json
import sqlite3
import time as clock
from bisect import bisect_right
from collections import defaultdict, OrderedDict
from pathlib import Path

from analysis_core.coverage import prepare_evidence
from features.contract import (TABLE_FIELDS, canonical, digest, read_rows, require, time,
                               validate_row, format_utc)


def select_metadata(rows, snapshot, kind):
    t = time(snapshot)
    visible = [r for r in rows if time(r["available_at"]) <= t]
    if kind == "attribute":
        visible = [r for r in visible if time(r["valid_from"]) <= t and
                   (r["valid_to"] is None or t < time(r["valid_to"]))]
    require(len(visible) == 1, "metadata_visibility", f"{kind}: 需要唯一可见有效记录，实际{len(visible)}")
    return visible[0]


def visible_uploads(rows, snapshot, id_field):
    """Pure point selection: unavailable variants never participate in deduplication."""
    t, chosen = time(snapshot), {}
    for raw in rows:
        raw = {k: format_utc(time(v)) if v is not None and (k.endswith("_at") or k == "event_time") else v for k, v in raw.items()}
        if time(raw["available_at"]) > t:
            continue
        key = raw[id_field]
        business = {k: v for k, v in raw.items() if k not in ("upload_id", "available_at")}
        if key in chosen:
            previous = chosen[key]
            require(business == {k: v for k, v in previous.items() if k not in ("upload_id", "available_at")},
                    "visible_content_conflict", f"{id_field}={key}")
            if (time(raw["available_at"]), raw["upload_id"]) < (time(previous["available_at"]), previous["upload_id"]):
                chosen[key] = raw
        else:
            chosen[key] = raw
    return [chosen[key] for key in sorted(chosen)]


class ObservedIndex:
    def __init__(self, observed, database, contract, *, fixture=None, progress=print):
        self.contract, self.progress = contract, progress
        self.tables = {n: [] for n in TABLE_FIELDS if n != "session_uploads"}
        self.user_cache, self.profile_cache = OrderedDict(), OrderedDict()
        self.profile_catalog = {}
        self.database = Path(database)
        require(not self.database.exists(), "index_exists", str(database))
        self.database.parent.mkdir(parents=True, exist_ok=True)
        if fixture is not None:
            require(observed is None and set(fixture) == set(TABLE_FIELDS), "observed_boundary", "仅接受九表小样例")
        else:
            path = Path(observed).resolve()
            require("private_eval" not in [p.lower() for p in path.parts], "observed_boundary", "禁止私有输入")
            require({p.name for p in path.iterdir()} == {n + ".jsonl" for n in TABLE_FIELDS}, "observed_boundary", "仅接受九张观测表")
        self.db = sqlite3.connect(database)
        try:
            self.db.execute("CREATE TABLE sessions(upload TEXT PRIMARY KEY, uid TEXT, lid TEXT, row TEXT)")
            for table in TABLE_FIELDS:
                started = clock.perf_counter()
                count = 0
                incoming = fixture[table] if fixture is not None else read_rows(path / (table + ".jsonl"))
                for raw in incoming:
                    row = validate_row(table, raw)
                    if table == "session_uploads":
                        self.db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (row["upload_id"], row["user_id"], row["session_id"], canonical(row)))
                    else:
                        self.tables[table].append(row)
                    count += 1
                    if count % 100000 == 0:
                        progress(f"观测索引 {table}: {count}行，{clock.perf_counter()-started:.1f}秒")
                progress(f"观测索引 {table}: 完成{count}行，{clock.perf_counter()-started:.1f}秒")
            self.db.execute("CREATE INDEX sessions_user ON sessions(uid,lid,upload)")
            self.db.execute("CREATE INDEX sessions_logical ON sessions(lid)")
            self.db.commit()
            self.db.execute("PRAGMA query_only=ON")
            self.by_user = {}
            for table in ("players", "player_attributes", "qualification_checks", "story_start_uploads"):
                grouped = defaultdict(list)
                for row in self.tables[table]:
                    grouped[row["user_id"]].append(row)
                self.by_user[table] = grouped
            self.source_rows, self.source_times = {}, {}
            self.cross_source_records = []
            for table in ("collection_checks", "watermark_checks"):
                ownership = defaultdict(list)
                for row in self.tables[table]:
                    ownership[row["record_id"]].append(row)
                self.cross_source_records.extend(values for values in ownership.values() if len({r["source_id"] for r in values}) > 1)
            self.starts_by_id = defaultdict(list)
            for row in self.tables["story_start_uploads"]:
                self.starts_by_id[row["event_id"]].append(row)
            for source in {r["source_id"] for n in ("collection_checks", "watermark_checks") for r in self.tables[n]}:
                for table in ("collection_checks", "watermark_checks"):
                    rows = sorted((r for r in self.tables[table] if r["source_id"] == source),
                                  key=lambda r: (time(r["available_at"]), r["record_id"], canonical(r)))
                    self.source_rows[source, table] = rows
                    self.source_times[source, table] = [time(r["available_at"]) for r in rows]
                # Validate even invisible row structure/time once; business conflicts remain snapshot-specific.
                prepare_evidence(self.source_rows[source, "collection_checks"], self.source_rows[source, "watermark_checks"], "1900-01-01T00:00:00Z")
            self._validate_links()
        except BaseException:
            self.db.close()
            raise

    def _validate_links(self):
        players = self.by_user["players"]
        require(all(len(v) == 1 for v in players.values()), "duplicate_player", "players")
        for uid, values in self.by_user["player_attributes"].items():
            require(uid in players, "attribute_player", uid)
            for row in values:
                require(row["region_id"] in ("R1", "R2", "R3") and row["language"] in ("L1", "L2") and row["client"] in ("PC", "Mobile"), "attribute_value", uid)
                require(row["valid_to"] is None or time(row["valid_from"]) < time(row["valid_to"]), "attribute_interval", uid)
        ids = {}
        for row in self.tables["qualification_checks"]:
            key = row["user_id"], row["story_id"]
            require(ids.setdefault(row["record_id"], key) == key, "qualification_owner", row["record_id"])
        for (uid,) in self.db.execute("SELECT DISTINCT uid FROM sessions"):
            require(uid in players, "session_player", uid)

    def sessions(self, uid):
        if uid not in self.user_cache:
            self.user_cache[uid] = [json.loads(row) for (row,) in self.db.execute(
                "SELECT row FROM sessions WHERE lid IN (SELECT lid FROM sessions WHERE uid=?) ORDER BY lid,upload", (uid,))]
            if len(self.user_cache) > 16:
                self.user_cache.popitem(last=False)
        self.user_cache.move_to_end(uid)
        return self.user_cache[uid]

    def starts(self, uid, story, snapshot):
        ids = {r["event_id"] for r in self.by_user["story_start_uploads"].get(uid, []) if r["story_id"] == story}
        selected = visible_uploads([r for key in sorted(ids) for r in self.starts_by_id[key]], snapshot, "event_id")
        return [r for r in selected if r["user_id"] == uid and r["story_id"] == story]

    def metadata(self, uid, story, snapshot):
        player = select_metadata(self.by_user["players"].get(uid, []), snapshot, "player")
        attr = select_metadata(self.by_user["player_attributes"].get(uid, []), snapshot, "attribute")
        visible_attrs = [r for r in self.by_user["player_attributes"][uid] if time(r["available_at"]) <= time(snapshot)]
        require(all(r["region_id"] == attr["region_id"] for r in visible_attrs), "unsupported_region_change", uid)
        calendar = select_metadata([r for r in self.tables["story_calendar"] if r["story_id"] == story and r["region_id"] == attr["region_id"]], snapshot, "calendar")
        require(calendar["expected_story_minutes"] == 45, "calendar_duration", story)
        bindings = {}
        for kind in ("session", "story_start"):
            row = select_metadata([r for r in self.tables["source_catalog"] if r["region_id"] == attr["region_id"] and r["event_kind"] == kind], snapshot, "source")
            require(row["source_id"] == self.contract["source_bindings"][attr["region_id"]][kind], "source_binding", row["source_id"])
            bindings[kind] = row
        return player, attr, calendar, bindings

    def profile(self, source, snapshot):
        for values in self.cross_source_records:
            visible_sources = {r["source_id"] for r in values if time(r["available_at"]) <= time(snapshot)}
            require(len(visible_sources) <= 1, "coverage_record_owner_conflict", values[0]["record_id"])
        cuts = tuple(bisect_right(self.source_times.get((source, table), []), time(snapshot)) for table in ("collection_checks", "watermark_checks"))
        key = source, cuts
        if key not in self.profile_cache:
            selected = [self.source_rows.get((source, table), [])[:cut] for table, cut in zip(("collection_checks", "watermark_checks"), cuts)]
            profile = prepare_evidence(*selected, snapshot)
            # assess_coverage only needs the source profile. Raw tables are preserved once in evidence/.
            for state in profile["sources"].values():
                for name in ("superseded_collection_records", "superseded_watermark_records", "excluded_collection_uploads", "excluded_watermark_uploads"):
                    state[name] = []
                for interval in state["current_intervals"]:
                    interval["records"] = []
                if state["latest_watermark"]:
                    state["latest_watermark"]["records"] = []
            history = selected[1]
            by_check = defaultdict(set)
            for row in history:
                by_check[time(row["checked_at"])].add(time(row["watermark_at"]))
            ordered = sorted(by_check)
            rollback = any(len(by_check[a]) == len(by_check[b]) == 1 and next(iter(by_check[b])) < next(iter(by_check[a])) for a, b in zip(ordered, ordered[1:]))
            compact = {"sources": profile["sources"]}
            evidence_id = digest({"source": source, "visible_collection": selected[0], "visible_watermarks": selected[1]})
            self.profile_catalog[evidence_id] = {"source_id": source, "visible_collection_ids": sorted({r["record_id"] for r in selected[0]}),
                "visible_watermark_ids": sorted({r["record_id"] for r in selected[1]}), "profile": compact, "rollback": rollback}
            self.profile_cache[key] = compact, evidence_id, rollback
            # One compact profile per actual source visibility boundary, not per sample t0.
            # Retain these finite input-derived versions to avoid repeating old deep parsing.
        self.profile_cache.move_to_end(key)
        return self.profile_cache[key]

    def close(self):
        self.db.close()
