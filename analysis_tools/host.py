"""Trusted launch configuration; never populated from a tool request."""

import argparse
import sys
import threading
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from analysis_tools.contracts import ROOT, append, digest, now, read, require, sha
from analysis_tools.registry import Gate, Registry, load_registered
from analysis_tools.service import Service
from case_adapters.m03_tools import M03Backend, FixtureBackend
from case_adapters.m03_prediction import FrozenPrediction


class Heartbeat:
    def __init__(self, directory, interval=30):
        self.directory, self.interval = Path(directory), interval
        self.stopped = threading.Event()
        self.thread = None

    def progress(self, message):
        append(self.directory / "progress.jsonl", {"actual_utc": now(), "message": message})
        print(message, file=sys.stderr, flush=True)

    def __enter__(self):
        def beat():
            while not self.stopped.wait(self.interval):
                self.progress("Task08 host still working; no check conclusion yet")
        self.thread = threading.Thread(target=beat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=2)


def make_service(host, directory, progress):
    directory = Path(directory)
    definition = deepcopy(host["definition"])
    if "fixture" in host:
        definition["identities"] = {**definition["identities"], "data_scope":"public_hand_fixture",
                                     "fixture_input_sha256":digest(host["fixture"])}
        definition["snapshots"][host["fixture"].get("version_id","V1")] = host["fixture"]["input"]["as_of"]
    registry = Registry(definition, host["schemas"], host["role"])
    gate = Gate(__import__("product_core.paths",fromlist=["ASSETS"]).ASSETS, host["resources"], directory / "access_log.jsonl")
    if "fixture" in host:
        require(host.get("check_controller_only") is True, "unauthorized", "fixture host denied")
        backend = FixtureBackend(host["fixture"], definition, directory / "audit")
    else:
        backend = M03Backend(gate, definition, directory / "audit", progress)
    predictor = FrozenPrediction(gate, definition, host["prediction_queue"], directory / "audit") if "prediction_queue" in host else None
    return Service(registry, gate, backend, predictor, host.get("cards", {}), directory)


def launch_arguments(*args,**kwargs):
    raise ValueError('Use python -m product_core; historical check-host launch is not distributed')
