"""Session-bound aggregate evidence. Individual artifacts never leave this store."""

from copy import deepcopy
from uuid import uuid4
from analysis_tools.contracts import digest, read, require, write


class EvidenceStore:
    def __init__(self, directory, registry, session_id):
        self.directory, self.registry, self.session_id = directory, registry, session_id
        self.entries = {}

    def create(self, tool, arguments, status, data, warnings, parents=()):
        # Parents are semantic fingerprints, not per-call opaque IDs.
        content = {"tool_name": tool, "validated_arguments": arguments, "status": status,
                   "data": data, "warnings": warnings, "source_identities": self.registry.identities,
                   "parent_content_fingerprints": list(parents), "registry_fingerprint": self.registry.fingerprint}
        fingerprint = digest(content)
        evidence_id = "ev" + uuid4().hex
        entry = {"evidence_id": evidence_id, "session_id": self.session_id, "role": self.registry.role,
                 "verification_status": "candidate", "content_fingerprint": fingerprint, "content": content}
        path = self.directory / (evidence_id + ".json")
        write(path, entry)
        self.entries[evidence_id] = (path, digest(entry))
        return evidence_id, fingerprint

    def get(self, evidence_id):
        require(evidence_id in self.entries, "unauthorized", "evidence not authorized in this session")
        path, expected = self.entries[evidence_id]
        entry = read(path)
        require(digest(entry) == expected and digest(entry["content"]) == entry["content_fingerprint"],
                "integrity_error", "evidence content changed")
        require(entry["session_id"] == self.session_id and entry["role"] == self.registry.role,
                "unauthorized", "evidence session or role mismatch")
        require(entry["content"]["registry_fingerprint"] == self.registry.fingerprint and
                entry["content"]["source_identities"] == self.registry.identities,
                "integrity_error", "evidence identity is stale")
        return deepcopy(entry)
