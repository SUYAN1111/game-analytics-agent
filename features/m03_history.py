"""Watermark-anchored histories. All formal M03 states come from accepted tools."""

from datetime import timedelta

from analysis_core.coverage import assess_coverage
from preparation.m03_qualification import prepare_population
from metrics.m03 import calculate_m03
from features.contract import OBSERVATION_START, VERSIONS, format_utc, require, time, validate_x
from features.observed import visible_uploads


def personal_window(registered_at, h, days, observation_start=OBSERVATION_START):
    end = time(h)
    start = max(time(registered_at), time(observation_start), end - timedelta(days=days))
    return format_utc(start), max(0.0, (end - start).total_seconds() / 86400)


def select_sessions(rows, registered_at, source, t0, a, h, user_id=None):
    """Pure selector; does not itself certify delivery or positive-length coverage."""
    selected = []
    for row in visible_uploads(rows, t0, "session_id"):
        if user_id is not None and row["user_id"] != user_id:
            continue
        require(row["source_id"] == source, "session_source", row["session_id"])
        start, end, available = map(time, (row["start_at"], row["end_at"], row["available_at"]))
        require(time(registered_at) <= start < end <= available, "session_time", row["session_id"])
        if time(a) < time(h) and time(a) <= end < time(h) and end < time(t0):
            selected.append(row)
    return sorted(selected, key=lambda row: (time(row["end_at"]), row["session_id"]))


def session_statistics(rows, registered_at, source, t0, h, user_id=None):
    x, audit, selected_by_window = {}, {}, {}
    for days in (7, 28):
        left, observed = personal_window(registered_at, h, days)
        selected = select_sessions(rows, registered_at, source, t0, left, h, user_id)
        n = len(selected)
        x[f"completed_sessions_{days}d"] = n
        x[f"completed_active_dates_{days}d"] = len({time(r["end_at"]).date() for r in selected})
        x[f"observed_days_{days}d"] = observed
        audit[f"a{days}"] = left
        audit[f"history_state_{days}d"] = ("NO_PERSONAL_OBSERVATION" if observed == 0 else
            "OBSERVED_WITH_COMPLETED_SESSION" if n else "OBSERVED_NO_COMPLETED_SESSION")
        audit[f"session_ids_{days}d"] = [r["session_id"] for r in selected]
        selected_by_window[days] = selected
    sessions = selected_by_window[28]
    durations = [(time(r["end_at"]) - time(r["start_at"])).total_seconds() for r in sessions]
    n = len(durations)
    x.update(hours_since_last_completed_session_28d=(time(t0) - max(time(r["end_at"]) for r in sessions)).total_seconds() / 3600 if n else None,
             mean_session_minutes_28d=sum(durations) / (60 * n) if n else None,
             session_45min_share_28d=sum(d >= 2700 for d in durations) / n if n else None)
    return x, audit


def qualify(index, candidate, as_of):
    key = candidate["user_id"], candidate["story_id"]
    records = [r for r in index.by_user["qualification_checks"].get(key[0], []) if r["story_id"] == key[1]]
    target = {"user_id": key[0], "story_id": key[1], "region_open_at": candidate["region_open_at"], "coverage_complete": False}
    prepared = prepare_population([target], records, as_of)
    return prepared["population"][0], prepared["audit"][0]


def story_state(index, candidate, as_of):
    """Reuse Task02 + Task03 coverage primitives + Task01; no alternative Q algorithm."""
    population, qual = qualify(index, candidate, as_of)
    uid, story = candidate["user_id"], candidate["story_id"]
    player, attr, calendar, bindings = index.metadata(uid, story, as_of)
    source = bindings["story_start"]["source_id"]
    profile, evidence_id, _ = index.profile(source, as_of)
    coverage = None
    if population["qualification_status"] == "qualified":
        coverage = assess_coverage(qual["t0"], format_utc(time(qual["t0"]) + timedelta(hours=72)), [source], profile)
        population["coverage_complete"] = coverage["coverage_complete"]
    starts = index.starts(uid, story, as_of)
    for row in starts:
        require(row["source_id"] == source, "start_source", row["event_id"])
        linked = [s for s in index.sessions(uid) if s["session_id"] == row["session_id"] and s["user_id"] == uid]
        require(any(time(s["start_at"]) <= time(row["event_time"]) < time(s["end_at"]) for s in linked), "start_session_link", row["event_id"])
    projected = [{k: r[k] for k in ("event_id", "user_id", "story_id", "event_time", "available_at")} for r in starts]
    result = calculate_m03([population], projected, as_of)["combinations"][0]
    result.update(qualification_status=population["qualification_status"], supporting_record_ids=qual["supporting_record_ids"],
                  qualification_reasons=qual["reasons"], source_id=source, evidence_id=evidence_id,
                  coverage_complete=population["coverage_complete"],
                  coverage_reasons=coverage["reason_codes"] if coverage else ["qualification_not_confirmed"],
                  visible_event_ids=[r["event_id"] for r in starts], as_of=as_of)
    return result


def history_features(index, candidate, t0, prior_candidates):
    uid, story = candidate["user_id"], candidate["story_id"]
    player, attr, calendar, bindings = index.metadata(uid, story, t0)
    source = bindings["session"]["source_id"]
    profile, evidence_id, rollback = index.profile(source, t0)
    state = profile["sources"].get(source, {})
    watermark = state.get("latest_watermark")
    require(watermark is not None and watermark["watermark_at"] is not None and not state.get("conflicts"), "history_watermark", "缺少有效水位或存在冲突")
    require(not rollback, "history_watermark_rollback", "可见水位存在回退，不采用旧有利版本")
    h = format_utc(min(time(t0), time(watermark["watermark_at"])))
    sessions = index.sessions(uid)
    # The provided watermark cannot contradict uploads in the authorized observed table.
    by_id = {}
    for row in sessions:
        if row["user_id"] == uid and row["source_id"] == source and time(row["end_at"]) < time(h):
            by_id.setdefault(row["session_id"], []).append(row)
    for sid, values in by_id.items():
        require(any(time(r["available_at"]) <= time(watermark["checked_at"]) for r in values), "delivery_contradiction", sid)
    x, audit = session_statistics(sessions, player["registered_at"], source, t0, h, uid)
    for days in (7, 28):
        if x[f"observed_days_{days}d"] > 0:
            coverage = assess_coverage(audit[f"a{days}"], h, [source], profile)
            require(coverage["coverage_complete"], "history_coverage", ",".join(coverage["reason_codes"]))
            audit[f"coverage_{days}d"] = {"evidence_id": evidence_id, "coverage_complete": True,
                "max_complete_checked_at": coverage["sources"][0]["max_complete_checked_at"],
                "merged_complete_intervals": coverage["sources"][0]["merged_complete_intervals"]}
        else:
            audit[f"coverage_{days}d"] = {"not_applicable": "a>=h，个人观察区间为空，未调用正长度覆盖核查"}
    prior = []
    for old in prior_candidates:
        if old["user_id"] == uid and VERSIONS.index(old["version_id"]) < VERSIONS.index(candidate["version_id"]):
            prior.append(story_state(index, old, t0))
    complete = [r for r in prior if r["state"] in ("Q4", "Q5")]
    started = sum(r["state"] == "Q4" for r in complete)
    age = (time(t0) - time(player["registered_at"])).total_seconds()
    x.update(prior_complete_story_count=len(complete), prior_started_72h_count=started,
        prior_started_72h_rate=started / len(complete) if complete else None,
        account_age_days=age / 86400, new_player=int(age < 168 * 3600),
        hours_since_region_open=(time(t0) - time(calendar["region_open_at"])).total_seconds() / 3600,
        expected_story_minutes=calendar["expected_story_minutes"], region_id=attr["region_id"], language=attr["language"], client=attr["client"])
    audit.update(t0=t0, history_watermark=h, history_lag_hours=(time(t0)-time(h)).total_seconds()/3600,
        watermark_record_ids=watermark["record_ids"], watermark_checked_at=watermark["checked_at"],
        source_id=source, evidence_id=evidence_id, registered_at=player["registered_at"],
        attribute_id=attr["attribute_id"], prior_stories=prior,
        exclusion_query="按玩家读取；available_at>t0、end_at>=h或end_at<a28不进入S28；原始行位于固定九表")
    return validate_x(x), audit
