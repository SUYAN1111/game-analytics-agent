"""Frozen inference: only registered no-label resources; never fit or score."""

from contextlib import contextmanager
from analysis_tools.contracts import ROOT, append, now, prediction_summary, read, require, rows, sha, write


@contextmanager
def fit_guard(attempts):
    from modeling.m03_baselines import FrozenCandidate, LogisticRegression, DecisionTreeClassifier
    from modeling.m03_preprocessing import Preprocessor, StandardScaler, OneHotEncoder
    classes = (FrozenCandidate, LogisticRegression, DecisionTreeClassifier, Preprocessor, StandardScaler, OneHotEncoder)
    originals = {cls: cls.fit for cls in classes}
    def rejected(instance, *args, **kwargs):
        attempts.append({"class": type(instance).__name__, "actual_utc": now()})
        from analysis_tools.contracts import ToolError
        raise ToolError("unauthorized", "fit forbidden in frozen prediction")
    try:
        for cls in classes:
            cls.fit = rejected
        yield
    finally:
        for cls, method in originals.items():
            cls.fit = method


class FrozenPrediction:
    def __init__(self, gate, definition, queue, audit):
        self.gate, self.definition, self.queue, self.audit = gate, definition, queue, audit
        self.last_predictions = []
        self.last_state = None

    def predict(self, versions, request_id):
        import subprocess
        import sys
        from mcp.client.stdio import get_default_environment
        # Only this child executes the model. It receives no observed tables, y, old
        # predictions, mature query rows, report roots or unused resource permissions.
        request = {"definition": self.definition,
                   "resources": {k:v for k,v in self.gate.resources.items() if "predictor" in v["purposes"]},
                   "queue": self.queue, "versions": versions, "request_id": request_id,
                   "audit": str(self.audit), "access_log": str(self.gate.log)}
        path = self.audit / (request_id+"_worker_request.json")
        write(path, request)
        with (self.audit / (request_id+"_worker_stderr.log")).open("x", encoding="utf-8") as err:
            try:
                result = subprocess.run([sys.executable, "-m", "case_adapters.m03_prediction", "--request", str(path),
                    "--request-sha", sha(path)], cwd=ROOT, shell=False, stdout=subprocess.PIPE, stderr=err,
                    encoding="utf-8", timeout=150, env=__import__("agent_runtime.common",fromlist=["clean_environment"]).clean_environment())
            except subprocess.TimeoutExpired as exc:
                from analysis_tools.contracts import ToolError
                raise ToolError("timeout","owned prediction worker exceeded deadline and was terminated") from exc
        append(self.audit/"prediction_worker_returns.jsonl",{"request_id":request_id,"returncode":result.returncode,"actual_utc":now()})
        if result.returncode != 0:
            raw = read(self.audit / (request_id+"_worker_error.json"))
            from analysis_tools.contracts import ToolError
            raise ToolError(raw["code"], "registered frozen prediction rejected; details remain in controller audit")
        self.last_predictions = list(rows(self.audit / (request_id+"_predictions.jsonl")))
        self.last_state = read(self.audit / (request_id+"_prediction_state.json"))
        return read(self.audit / (request_id+"_summary.json"))

    def _predict_local(self, versions, request_id):
        from modeling.m03_data import align
        from modeling.m03_predict import Predictor
        from features.contract import digest
        self.gate.verify("predictor")
        freeze = read(self.gate.path("freeze", "predictor"))
        require(freeze["selected_candidate_id"] == self.definition["identities"]["selected_candidate_id"],
                "integrity_error", "selected candidate changed")
        data = align(list(rows(self.gate.path("test_X", "predictor"))), None,
                     list(rows(self.gate.path("test_row_map", "predictor"))), "test")
        expected_keys = {(q["user_id"], q["story_id"], q["version_id"], q["t0"]) for q in self.queue}
        actual_keys = {(m["user_id"], m["story_id"], m["version_id"], m["t0"]) for m in data["row_map"]}
        require(len(expected_keys) == len(self.queue) and expected_keys == actual_keys,
                "integrity_error", "frozen X does not cover the registered qualification queue")
        directory = self.gate.path("asset:"+freeze["selected_candidate_id"], "predictor").parent
        attempts = []
        with fit_guard(attempts):
            predictor = Predictor(directory, freeze["asset_hashes"])
            before = {key: model.state_sha256 for key, model in predictor.models.items()}
            require(before == freeze["candidate_state_sha256"], "integrity_error", "frozen parameter state changed")
            indices = [i for i, m in enumerate(data["row_map"]) if m["version_id"] in versions]
            x = [data["X"][i] for i in indices]
            mapping = [data["row_map"][i] for i in indices]
            p = predictor.predict(x, freeze["selected_candidate_id"])
            require(len(p) == len(mapping), "integrity_error", "missing model predictions")
            after = {}
            for key, model in predictor.models.items():
                model.check()
                after[key] = digest(model.parameters())
            require(before == after and not attempts, "integrity_error", "model mutated or fit attempted")
        executed = now()
        output = [{**m, "prediction_as_of": m["t0"], "executed_at": executed,
                   "producer": "registered_model_call", "time_mode": "frozen_t0_replay",
                   "p_not_started_72h": float(value)} for m, value in zip(mapping, p)]
        for record in output:
            append(self.audit / (request_id+"_predictions.jsonl"), record)
        self.last_predictions = output
        self.last_state = {"before": before, "after": after, "fit_attempts": attempts,
                           "full_X_rows": len(data["X"]), "selected_indices": indices}
        write(self.audit / (request_id+"_prediction_state.json"), self.last_state)
        expected = {v: sum(q["version_id"] == v for q in self.queue) for v in versions}
        self.gate.verify("predictor")
        return {"kind": "frozen_prediction", "time_mode": "frozen_t0_replay",
                "producer": "registered_model_call", "positive_class": "not_started_within_72h",
                "model_id": self.definition["model_id"], "versions": versions,
                "rows": prediction_summary(output, expected, versions),
                "individual_predictions": {"access": "controller_only", "kind": "frozen_prediction_audit"}}


def main():
    import argparse
    import os
    import traceback
    from pathlib import Path
    from analysis_tools.registry import Gate
    parser=argparse.ArgumentParser()
    parser.add_argument("--request",required=True)
    parser.add_argument("--request-sha",required=True)
    args=parser.parse_args()
    path=Path(args.request).resolve(strict=True)
    require(path.is_relative_to(__import__("product_core.paths",fromlist=["STATE"]).STATE) and sha(path)==args.request_sha,
            "unauthorized","prediction launch request not trusted")
    from task13_runtime.boundary import install
    install(path.parent)
    request=read(path)
    audit=Path(request["audit"])
    append(audit/"prediction_worker_lifecycle.jsonl",{"pid":os.getpid(),"parent_pid":os.getppid(),"event":"started","actual_utc":now()})
    try:
        require(set(request)=={"definition","resources","queue","versions","request_id","audit","access_log"},
                "unauthorized","prediction launch fields")
        gate=Gate(__import__("product_core.paths",fromlist=["ASSETS"]).ASSETS,request["resources"],request["access_log"])
        worker=FrozenPrediction(gate,request["definition"],request["queue"],audit)
        result=worker._predict_local(request["versions"],request["request_id"])
        write(audit/(request["request_id"]+"_summary.json"),result)
        return 0
    except Exception as exc:
        write(audit/(request["request_id"]+"_worker_error.json"),{"type":type(exc).__name__,
              "code":getattr(exc,"code","data_error"),"message":str(exc),"traceback":traceback.format_exc()})
        return 1
    finally:
        append(audit/"prediction_worker_lifecycle.jsonl",{"pid":os.getpid(),"parent_pid":os.getppid(),"event":"exited","actual_utc":now()})


if __name__=="__main__":
    raise SystemExit(main())
