"""Host-only registry and resource-purpose boundary (not an OS sandbox)."""

from pathlib import Path
from analysis_tools.contracts import ROOT, ToolError, append, digest, now, read, require, sha


class Gate:
    def __init__(self, root, resources, log):
        self.root = Path(root).resolve(strict=True)
        self.resources, self.log = resources, Path(log)

    def path(self, resource_id, purpose):
        require(resource_id in self.resources, "unauthorized", "resource not registered")
        entry = self.resources[resource_id]
        require(purpose in entry["purposes"], "unauthorized", "resource purpose denied")
        relative = Path(entry["path"])
        require(not relative.is_absolute() and ".." not in relative.parts,
                "unauthorized", "resource location denied")
        try:
            path = (self.root / relative).resolve(strict=True)
        except OSError as exc:
            raise ToolError("integrity_error", "registered resource missing or unavailable") from exc
        require(path.is_relative_to(self.root), "unauthorized", "resource escapes registered root")
        # Reject every symlink/junction component, including a same-root redirection.
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            require(not cursor.is_symlink() and not (hasattr(cursor, "is_junction") and cursor.is_junction()),
                    "unauthorized", "resource redirection denied")
        require(sha(path) == entry["sha256"], "integrity_error", "registered resource content changed")
        append(self.log, {"role": purpose, "purpose": purpose, "resource_id": resource_id,
                          "path": str(path), "sha256": entry["sha256"], "actual_utc": now()})
        return path

    def verify(self, purpose):
        for key, entry in self.resources.items():
            if purpose in entry["purposes"]:
                self.path(key, purpose)


class Registry:
    def __init__(self, definition, schemas, role):
        require(role in ("analysis_demo", "evaluation"), "unauthorized", "unknown host role")
        self.definition, self.schemas, self.role = definition, schemas, role
        self.identities = definition["identities"]
        self.fingerprint = digest({"definition": definition, "schemas": schemas})

    def bind(self, tool, args):
        d = self.definition
        if "case_id" in args:
            require(args["case_id"] == d["case_id"], "unauthorized", "case binding mismatch")
        if "metric_id" in args:
            require(args["metric_id"] == d["metric_id"], "unauthorized", "metric binding mismatch")
        if "snapshot_set_id" in args:
            require(args["snapshot_set_id"] == d["snapshot_set_id"], "unauthorized", "snapshot binding mismatch")
        if "model_id" in args:
            require(args["model_id"] == d["model_id"], "unauthorized", "model binding mismatch")
        if "cohort_id" in args:
            allowed = d["prediction_cohorts"] if tool == "predict_registered" else d["cohorts"]
            require(args["cohort_id"] in allowed, "unauthorized", "cohort binding mismatch")
        return args


def load_registered(toolset_id):
    from product_core.release import host
    from agent_runtime.common import CONFIG,read
    require(toolset_id==read(CONFIG)['toolset_id'],'identity','unknown registered toolset')
    return host()
