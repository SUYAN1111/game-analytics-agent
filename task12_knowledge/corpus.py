import copy
import hashlib
from collections import Counter
from agent_runtime.common import ROOT,read,sha,digest,require
from knowledge_core.retrieval import Index,tokens,validate_cards

class CombinedIndex(Index):
    def __init__(self,cards,configuration,scopes):
        validate_cards(cards);self.config=copy.deepcopy(configuration)
        require(configuration['k1']==1.2 and configuration['b']==.75 and configuration['top_k']==4,'retriever','fixed parameters')
        self.scope={'allowed_scopes':copy.deepcopy(scopes)}
        fields=('case_id','metric_id','definition_fingerprint','knowledge_revision')
        require(len(scopes)==3 and all(set(s)==set(fields) for s in scopes),'scope','three complete scopes required')
        self.cards=sorted([copy.deepcopy(c) for c in cards if c['enabled'] and any(all(c[k]==s[k] for k in fields) for s in scopes)],key=lambda c:c['card_id'])
        self.documents=[]
        for c in self.cards:
            for chunk in c['chunks']:
                words=tokens(' '.join((c['title'],chunk['section_title'],chunk['text'])))
                self.documents.append({'card_id':c['card_id'],'title':c['title'],'knowledge_revision':c['knowledge_revision'],
                    'scope':{k:c[k] for k in fields},**copy.deepcopy(chunk),'text_sha256':hashlib.sha256(chunk['text'].encode()).hexdigest(),
                    'tf':dict(Counter(words)),'length':len(words)})
        self.df=Counter(k for d in self.documents for k in d['tf'])
        self.avg_len=sum(d['length'] for d in self.documents)/len(self.documents) if self.documents else 0
        self.corpus_fingerprint=digest(self.cards);self.retriever_fingerprint=digest(configuration)
        self.cache_key=digest({'corpus':self.corpus_fingerprint,'retriever':self.retriever_fingerprint,'scope':self.scope})

class Corpus:
    def __init__(self,home=None):
        require(home is None,'corpus','only fixed Task12 allowlist accepted')
        __import__('product_core.release',fromlist=['verify']).verify(False)
        self.home=ROOT;manifest=read(ROOT/'task12_knowledge/manifest.json');self.manifest=manifest
        self.files={e['path']:e['sha256'] for e in manifest['cards']}
        self.files.update({s['path']:s['sha256'] for s in manifest['source'].values()})
        self.files['task12_knowledge/manifest.json']=sha(ROOT/'task12_knowledge/manifest.json')
        self.assert_current();cards=[]
        for e in manifest['cards']:
            c=read(ROOT/e['path']);scope={k:c[k] for k in ('case_id','metric_id','definition_fingerprint','knowledge_revision')}
            require(c['card_id']==e['card_id'] and scope==manifest['scopes'][e['scope_index']],'corpus','per-card scope mismatch')
            for chunk in c['chunks']:
                for ref in chunk['source_refs']:
                    require(ref['source_id'] in manifest['source'] and ref['sha256']==manifest['source'][ref['source_id']]['sha256'],'knowledge_integrity','unbound public citation source')
            cards.append(c)
        vocabulary=sorted({w for c in cards for w in c['keywords'] if len(w)>1})
        conf={'version':'task12_three_scope_bm25_v1','k1':1.2,'b':.75,'top_k':4,'vocabulary':vocabulary,
              'vocabulary_fingerprint':digest(vocabulary),'tokenizer':'NFKC_lower_chinese_bigrams_ascii_identifiers',
              'filter_before_statistics':True}
        self.index=CombinedIndex(cards,conf,manifest['scopes'])
        self.identity={'corpus_fingerprint':self.index.corpus_fingerprint,'retriever_fingerprint':self.index.retriever_fingerprint,
                       'scope':self.index.scope,'files':self.files}
    def assert_current(self):
        for p,h in self.files.items():
            path=ROOT/p
            require(path.resolve().is_relative_to(ROOT.resolve()) and not path.is_symlink() and sha(path)==h,'knowledge_integrity','card/manifest changed '+p)
    def search(self,args):self.assert_current();return self.index.search(args)
