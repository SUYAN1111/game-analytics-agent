"""Frozen rule assets; every access verifies independently pinned bytes."""
import copy
import shutil
from association.contract import *
from association.mining import evaluate
from association.public import public_view

REQUIRED={'rules.json','business.json','rule_contract.json','raw_contract.json','generation_manifest.json','metadata_references.json','windows.json'}|{f'{folder}/{name}.json' for folder in ('baskets','evaluations','public') for name in EVALUATIONS}

def verify_asset(home,expected=None):
    home=Path(home).resolve();manifest=home/'asset_manifest.json'
    require(manifest.is_file() and not manifest.is_symlink() and (expected is None or sha(manifest)==expected),'asset_integrity','untrusted activity manifest')
    m=read(manifest);require(REQUIRED<=set(m['files']),'asset_integrity','required activity asset omitted')
    for name,h in m['files'].items():
        p=home/name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and p.resolve().is_relative_to(home) and
                p.is_file() and not p.is_symlink() and sha(p)==h,'asset_integrity','changed activity asset '+name)
    i=m['identity'];r=read(home/'rules.json');c=read(home/'business.json');g=read(home/'generation_manifest.json')
    bindings={'rules_sha256':'rules.json','configuration_sha256':'business.json','contract_sha256':'rule_contract.json',
        'raw_contract_sha256':'raw_contract.json','generation_manifest_sha256':'generation_manifest.json',
        'metadata_sha256':'metadata_references.json','windows_sha256':'windows.json'}
    require(all(i.get(k)==m['files'][p]==sha(home/p) for k,p in bindings.items()),'asset_integrity','declared activity SHA differs from actual file')
    require(i.get('baskets')=={e:sha(home/'baskets'/f'{e}.json') for e in EVALUATIONS},'asset_integrity','basket identity differs')
    require(c==config() and sha(home/'rule_contract.json')==sha(RULE_SCHEMA) and sha(home/'raw_contract.json')==sha(SCHEMA),
            'asset_integrity','installed contract differs from fixed contract')
    require(i['case_id']==c['case_id'] and i['basket_contract']==c['contract'] and i['definition_fingerprint']==sha(RULE_SCHEMA) and
        i['rule_set_id']==r['rule_set_id']=='rules12'+digest(r['identity'])[:24] and i['activity_dataset_id']==g['activity_dataset_id']==
        'activity12'+digest(g['identity'])[:24] and m['content_id']=='association12'+digest(i)[:24], 'asset_integrity','activity identity differs')
    require(r['identity']['rules']==r['rules'] and r['display_rule_ids']==[x['rule_id'] for x in r['rules'][:10]],'asset_integrity','frozen list differs')
    for name,h in read(home/'metadata_references.json').items():require(name in METADATA and sha(OBSERVED/(name+'.jsonl'))==h,'asset_integrity','upstream metadata differs')
    return m

def verify_trusted(home,trust,live=False):
    from product_core.release import verify_anchor
    from product_core.paths import ASSETS
    manifest=verify_asset(home,verify_anchor(home,trust,'association'))
    generation=read(Path(home)/'generation_manifest.json')
    observed=ASSETS/'data/generated'/manifest['identity']['activity_dataset_id']/'observed'
    require(observed.is_dir() and {p.name for p in observed.iterdir()}==set(generation['identity']['observed']),'asset_integrity','observations missing/extra')
    for name,h in generation['identity']['observed'].items():
        require(sha(observed/name)==h,'asset_integrity','observation changed '+name)
    return manifest

class FrozenStore:
    def __init__(self,home,trust):
        self.home=Path(home);self.trust=copy.deepcopy(trust);self.manifest=verify_trusted(home,trust)
        self.rules=read(self.home/'rules.json');self.cache={};self.basket_load_count=0;self.evaluation_count=0;self.mine_count=0
    def get(self,name):
        require(name in EVALUATIONS,'invalid_arguments','unknown fixed evaluation')
        require(verify_trusted(self.home,self.trust)==self.manifest,'asset_integrity','asset identity changed after load')
        if name in self.cache:return copy.deepcopy(self.cache[name]),True
        baskets=read(self.home/'baskets'/f'{name}.json');self.basket_load_count+=1
        actual=evaluate(baskets,self.rules,name);self.evaluation_count+=1
        actual['windows']=[{k:w[k] for k in ('window_id','version_id','region_id','w_start','w_end','as_of')}
            for w in read(self.home/'windows.json') if w['version_id'] in EVALUATIONS[name]]
        require(actual==read(self.home/'evaluations'/f'{name}.json'),'asset_integrity','actual frozen-basket counts differ from sealed result')
        public=public_view(actual);require(public==read(self.home/'public'/f'{name}.json'),'asset_integrity','public disclosure differs')
        self.cache[name]=public;return copy.deepcopy(public),False


