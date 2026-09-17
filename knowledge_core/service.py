"""Distinct, turn-bound knowledge evidence; no Task08 EvidenceStore mutation."""
import copy
from uuid import uuid4
from agent_runtime.common import HostError, digest, now, require

TOOL = {"name":"search_knowledge", "description":"本地检索已登记业务定义；返回最多四个完整原文块及逻辑来源，不计算业务读数。",
    "input_schema":{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":256}},
                    "required":["query"],"additionalProperties":False},
    "output_schema":{"type":"object", "required":["evidence_type","tool_name","status","request_id","session_id",
        "turn_id","evidence_id","query","normalized_query","scope","corpus_fingerprint","retriever_fingerprint",
        "hits","error","content_fingerprint","execution"],
        "properties":{"status":{"enum":["ok","empty","invalid_arguments","integrity_error","internal_error"]},
                      "hits":{"type":"array","maxItems":4}},"additionalProperties":True}}


def semantic(result):
    return {k:copy.deepcopy(result[k]) for k in ("evidence_type","tool_name","status","query","normalized_query",
        "scope","corpus_fingerprint","retriever_fingerprint","hits","error")}


class KnowledgeService:
    def __init__(self, corpus, session_id):
        self.corpus, self.session_id = corpus, session_id

    def dispatch(self, arguments, turn_id):
        require(type(turn_id) is str and bool(turn_id), "turn", "trusted current turn required")
        base = {"evidence_type":"business_knowledge_v1", "tool_name":"search_knowledge",
            "request_id":"kreq"+uuid4().hex, "session_id":self.session_id, "turn_id":turn_id,
            "evidence_id":None, "query":None, "normalized_query":None, "hits":[], "error":None,
            "scope":self.corpus.index.scope, "corpus_fingerprint":self.corpus.index.corpus_fingerprint,
            "retriever_fingerprint":self.corpus.index.retriever_fingerprint}
        try:
            base.update(self.corpus.search(arguments))
            base["evidence_id"] = "knowledge10_"+uuid4().hex
        except HostError as exc:
            base.update(status="integrity_error" if exc.code == "knowledge_integrity" else "invalid_arguments",
                        error={"type":type(exc).__name__,"code":exc.code,"message":str(exc)})
        except OSError:
            base.update(status="integrity_error",error={"type":"OSError","code":"knowledge_integrity",
                        "message":"registered knowledge files unavailable; stop this turn"})
        base["content_fingerprint"] = digest(semantic(base))
        base["execution"] = {"at":now()}
        return base


class KnowledgeEvidence:
    def __init__(self, corpus):
        self.corpus, self.entries, self.results = corpus, {}, []
        self.session_id = None
        self.request_ids = set()

    def add(self, result, session_id, turn_id):
        self.corpus.assert_current()
        require(result.get("evidence_type") == "business_knowledge_v1" and result.get("tool_name") == "search_knowledge",
                "knowledge_identity", "wrong knowledge producer")
        require(result["session_id"] == session_id and result["turn_id"] == turn_id,
                "knowledge_session", "knowledge response not from this session and turn")
        identifier = result.get("request_id")
        require(type(identifier) is str and identifier.startswith("kreq") and identifier not in self.request_ids,
                "knowledge_identity", "invalid or repeated knowledge request instance")
        if self.session_id is None: self.session_id = session_id
        require(self.session_id == session_id, "knowledge_session", "knowledge crossed MCP session")
        index = self.corpus.index
        require(result["scope"] == index.scope and result["corpus_fingerprint"] == index.corpus_fingerprint and
                result["retriever_fingerprint"] == index.retriever_fingerprint,
                "knowledge_identity", "knowledge identity changed")
        require(digest(semantic(result)) == result["content_fingerprint"], "knowledge_fingerprint", "knowledge content changed")
        if result["error"] is not None:
            require(result["status"] != "integrity_error", "knowledge_integrity", "knowledge identity fault stops the turn")
            require(result["evidence_id"] is None and result["hits"] == [], "knowledge_identity", "error cannot supply knowledge")
        else:
            expected = self.corpus.search({"query":result["query"]})
            require(all(result[k] == v for k,v in expected.items()), "knowledge_fingerprint", "returned hits differ from pinned corpus retrieval")
            identifier = result["evidence_id"]
            require(type(identifier) is str and identifier.startswith("knowledge10_") and identifier not in self.entries,
                    "knowledge_identity", "invalid or duplicate knowledge evidence ID")
            self.entries[identifier] = copy.deepcopy(result)
        self.request_ids.add(result["request_id"])
        self.results.append(copy.deepcopy(result))

    def select(self, selection, session_id, turn_id):
        from knowledge_core.retrieval import exact
        import re
        self.corpus.assert_current()
        exact(selection, {"id","evidence_id","chunk_id"}, "knowledge_selection")
        require(type(selection["id"]) is str and re.fullmatch(r"k[1-9]\d*", selection["id"]),
                "knowledge_selection", "invalid knowledge selection ID")
        require(type(selection["evidence_id"]) is str and selection["evidence_id"] in self.entries,
                "knowledge_evidence", "knowledge evidence was not actually retrieved")
        evidence = self.entries[selection["evidence_id"]]
        require(evidence["turn_id"] == turn_id and evidence["session_id"] == session_id,
                "knowledge_session", "knowledge must be retrieved again in this user turn")
        require(digest(semantic(evidence)) == evidence["content_fingerprint"], "knowledge_fingerprint", "stored evidence changed")
        expected = self.corpus.search({"query":evidence["query"]})
        require(evidence["hits"] == expected["hits"], "knowledge_fingerprint", "stored knowledge blocks changed")
        found = [h for h in evidence["hits"] if h["chunk_id"] == selection["chunk_id"]]
        require(len(found) == 1, "knowledge_chunk", "chunk was not returned by this search")
        return {"selection":copy.deepcopy(selection),"chunk":copy.deepcopy(found[0]),
                "content_fingerprint":evidence["content_fingerprint"],"session_id":session_id,"turn_id":turn_id}

    def note_allowed(self, note, turn_id):
        values = [r for r in self.results if r["turn_id"] == turn_id]
        if note == "knowledge_not_found":
            return any(r["status"] == "empty" and r["error"] is None for r in values) and not any(r["status"] == "ok" for r in values)
        return bool(values) and all(r["error"] is not None for r in values)
