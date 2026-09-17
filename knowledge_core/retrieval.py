"""Concrete twelve-card schema and BM25. Never scans directories or executes text."""
import copy
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from agent_runtime.common import ROOT, digest, read, require, sha

TOKEN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[a-z0-9_]+")
CARD_FIELDS = {"card_id", "title", "knowledge_revision", "language", "case_id", "metric_id",
               "definition_fingerprint", "enabled", "keywords", "chunks"}
CHUNK_FIELDS = {"chunk_id", "section_title", "text", "source_refs"}
REF_FIELDS = {"source_id", "sha256", "locator"}


def normalize(text):
    return unicodedata.normalize("NFKC", text).lower()


def tokens(text):
    result = []
    for word in TOKEN.findall(normalize(text)):
        if '\u3400' <= word[0] <= '\u9fff' and not word[0].isascii():
            result.extend([word] if len(word) == 1 else [word[i:i+2] for i in range(len(word)-1)])
        else:
            result.append(word)
    return result


def exact(obj, fields, code):
    require(type(obj) is dict and set(obj) == fields, code, "unexpected fields: "+repr(fields))


def text(value, code):
    require(type(value) is str and bool(value.strip()), code, "nonempty text required")


def validate_cards(cards):
    require(type(cards) is list, "card_schema", "cards must be a list")
    ids, chunks, active = set(), set(), set()
    for card in cards:
        exact(card, CARD_FIELDS, "card_schema")
        for field in CARD_FIELDS-{"enabled", "keywords", "chunks"}: text(card[field], "card_schema")
        require(re.fullmatch(r"K\d{2}", card["card_id"]) and card["language"] == "zh-CN" and
                re.fullmatch(r"[0-9a-f]{64}", card["definition_fingerprint"]), "card_schema", "invalid scope/ID")
        key = card["card_id"], card["knowledge_revision"]
        require(key not in ids, "card_schema", "duplicate card revision")
        ids.add(key)
        require(type(card["enabled"]) is bool, "card_schema", "enabled must be bool")
        if card["enabled"]:
            scope = (card["card_id"], card["case_id"], card["metric_id"], card["definition_fingerprint"])
            require(scope not in active, "card_schema", "multiple enabled revisions for one topic")
            active.add(scope)
        require(type(card["keywords"]) is list and 1 <= len(card["keywords"]) <= 16 and
                all(type(w) is str for w in card["keywords"]), "card_schema", "finite keyword list required")
        require(len(set(card["keywords"])) == len(card["keywords"]), "card_schema", "duplicate keyword")
        for word in card["keywords"]:
            text(word, "card_schema"); require(len(word) <= 32, "card_schema", "keyword too long")
        require(type(card["chunks"]) is list and 2 <= len(card["chunks"]) <= 4, "card_schema", "two to four chunks per card")
        for chunk in card["chunks"]:
            exact(chunk, CHUNK_FIELDS, "card_schema")
            for field in ("chunk_id", "section_title", "text"): text(chunk[field], "card_schema")
            require(chunk["chunk_id"].startswith(card["card_id"]+".") and len(chunk["text"]) <= 500,
                    "card_schema", "invalid chunk identity or overlong text")
            chunk_key = (card["case_id"],card["metric_id"],card["definition_fingerprint"],card["knowledge_revision"],chunk["chunk_id"])
            require(chunk_key not in chunks, "card_schema", "duplicate chunk ID")
            chunks.add(chunk_key)
            require(type(chunk["source_refs"]) is list and bool(chunk["source_refs"]), "source", "source required")
            for ref in chunk["source_refs"]:
                exact(ref, REF_FIELDS, "source")
                for v in ref.values(): text(v, "source")
                require(re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) and
                        re.fullmatch(r"S\d{2}", ref["source_id"]) and
                        (ref["locator"].startswith("/") or re.fullmatch(r"L\d+-L\d+", ref["locator"])),
                        "source", "source must use logical ID/hash/exact locator")
    require(len(chunks) <= 48, "card_schema", "corpus exceeds 48 chunks")


class Index:
    def __init__(self, cards, configuration, scope):
        validate_cards(cards)
        exact(scope, {"case_id","metric_id","definition_fingerprint","knowledge_revision"}, "card_schema")
        for value in scope.values(): text(value,"card_schema")
        self.config, self.scope = copy.deepcopy(configuration), copy.deepcopy(scope)
        require(configuration["k1"] == 1.2 and configuration["b"] == .75 and configuration["top_k"] == 4,
                "retriever", "fixed BM25 parameters changed")
        self.cards = sorted(copy.deepcopy(cards), key=lambda c: (c["card_id"], c["knowledge_revision"]))
        for card in self.cards: card["chunks"].sort(key=lambda c:c["chunk_id"])
        self.corpus_fingerprint = digest(self.cards)
        self.retriever_fingerprint = digest(configuration)
        self.documents = []
        for card in self.cards:
            if not card["enabled"] or any(card[k] != v for k, v in scope.items()): continue
            for chunk in sorted(card["chunks"], key=lambda c:c["chunk_id"]):
                terms = tokens(" ".join((card["title"], chunk["section_title"], chunk["text"])))
                self.documents.append({"card_id":card["card_id"], "title":card["title"],
                    "knowledge_revision":card["knowledge_revision"], **copy.deepcopy(chunk),
                    "text_sha256":__import__('hashlib').sha256(chunk["text"].encode('utf-8')).hexdigest(),
                    "tf":dict(Counter(terms)), "length":len(terms)})
        self.df = Counter(t for doc in self.documents for t in doc["tf"])
        self.avg_len = sum(d["length"] for d in self.documents)/len(self.documents) if self.documents else 0
        self.cache_key = digest({"corpus":self.corpus_fingerprint,"retriever":self.retriever_fingerprint,"scope":scope})

    def search(self, arguments):
        exact(arguments, {"query"}, "invalid_arguments")
        query = arguments["query"]
        require(type(query) is str and 1 <= len(query) <= 256, "invalid_arguments", "query requires 1–256 Unicode characters")
        normalized = normalize(query)
        query_tokens = sorted(set(tokens(query)))
        # Whole public terms (Chinese substring / full English identifier), not whole test questions.
        matched = [w for w in self.config["vocabulary"] if
                   (normalize(w) in normalized if any('\u3400' <= c <= '\u9fff' for c in w)
                    else normalize(w) in query_tokens)]
        hits = []
        if normalized.strip() and matched and self.documents and self.avg_len:
            n = len(self.documents)
            for document in self.documents:
                score = 0.0
                for term in query_tokens:
                    frequency = document["tf"].get(term, 0)
                    if not frequency: continue
                    df = self.df[term]
                    idf = math.log(1+(n-df+.5)/(df+.5))
                    score += idf*frequency*2.2/(frequency+1.2*(.25+.75*document["length"]/self.avg_len))
                if score > 0:
                    hits.append({k:copy.deepcopy(v) for k,v in document.items() if k not in ("tf","length")} | {"score":score})
            hits.sort(key=lambda d:(-d["score"], d["card_id"], d["chunk_id"]))
        return {"status":"ok" if hits else "empty", "query":query, "normalized_query":normalized,
                "scope":self.scope, "corpus_fingerprint":self.corpus_fingerprint,
                "retriever_fingerprint":self.retriever_fingerprint, "hits":hits[:4]}

    def statistics(self):
        return {"N":len(self.documents), "avg_len":self.avg_len, "df":dict(sorted(self.df.items())),
                "documents":[{"chunk_id":d["chunk_id"],"length":d["length"],"tf":d["tf"]} for d in self.documents],
                "cache_key":self.cache_key}


class Corpus:
    """Explicit file allowlist. The pinned object fails closed after any source edit."""
    def __init__(self, home=None):
        self.home = Path(home or ROOT/"business_knowledge").resolve()
        self.manifest = read(self.home/"manifest_v1.json")
        exact(self.manifest,{"schema_version","chunk_version","scope","retrieval_sha256","cards"},"corpus")
        require(self.manifest["schema_version"]=="knowledge_cards_v1" and self.manifest["chunk_version"]=="whole_rule_v1",
                "corpus","unregistered structure/chunk version")
        self.files = {"manifest_v1.json":sha(self.home/"manifest_v1.json"),
                      "retrieval_v1.json":self.manifest["retrieval_sha256"]}
        entries = self.manifest["cards"]
        require(len(entries) == 12 and {e["card_id"] for e in entries} == {f"K{i:02}" for i in range(1,13)},
                "corpus", "production manifest must contain exactly K01–K12")
        cards = []
        for entry in entries:
            exact(entry, {"card_id","path","sha256"}, "corpus")
            require(entry["path"] == "cards/"+entry["card_id"]+".json", "corpus", "unlisted/non-card source denied")
            self.files[entry["path"]] = entry["sha256"]
        self.assert_current()
        for entry in entries:
            card = read(self.home/entry["path"])
            require(card["card_id"] == entry["card_id"] and card["enabled"] is True, "corpus", "production card identity mismatch")
            require(all(card[k] == v for k,v in self.manifest["scope"].items()), "corpus", "production scope mismatch")
            cards.append(card)
        config = read(self.home/"retrieval_v1.json")
        require(config["vocabulary"] == sorted({w for c in cards for w in c["keywords"]}) and
                config["vocabulary_sha256"] == digest(config["vocabulary"]), "corpus", "vocabulary not frozen from public card keywords")
        expected={"version":"bm25_zh_bigram_v1","normalization":"NFKC_lower","han_ranges":["3400-4DBF","4E00-9FFF"],
            "ascii_pattern":"[a-z0-9_]+","document_fields":["title","section_title","text"],"unique_query_tokens":True,
            "query_token_order":"Unicode_ascending","k1":1.2,"b":.75,"top_k":4,"positive_scores_only":True,
            "tie_break":["card_id","chunk_id"],"vocabulary":config["vocabulary"],"vocabulary_sha256":config["vocabulary_sha256"]}
        require(config==expected,"corpus","retriever configuration differs from implemented fixed algorithm")
        self.index = Index(cards, config, self.manifest["scope"])
        self.identity = {"corpus_fingerprint":self.index.corpus_fingerprint,
                         "retriever_fingerprint":self.index.retriever_fingerprint,"files":self.files,
                         "scope":self.manifest["scope"]}

    def assert_current(self):
        for relative, expected in self.files.items():
            p = self.home/relative
            require(not p.is_symlink() and not p.parent.is_symlink() and p.resolve().is_relative_to(self.home)
                    and p.is_file() and sha(p) == expected, "knowledge_integrity", "registered knowledge file missing or changed: "+relative)

    def search(self, args):
        self.assert_current()
        return self.index.search(args)
