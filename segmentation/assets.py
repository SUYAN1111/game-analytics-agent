"""Immutable build artifacts and safe public report exports. User-run only."""
import importlib.metadata
import json
import shutil
import sys
import zipfile
from pathlib import Path
from segmentation.contract import ROOT, FEATURES, CONFIG, config, read, write, write_rows, csv_rows, digest, sha, require, now
from segmentation.profiles import assign, public_view

def source_identity():
    home=ROOT/'segmentation'
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(home.glob('*.py'))}



def verify_asset(home, expected_manifest_sha256=None):
    """Internal consistency plus an optional EXTERNAL sealed-manifest anchor.

    Builders may inspect an unpublished asset without an anchor. Registered
    readers must supply the digest obtained from the sealed offline run.
    """
    home=Path(home).resolve();manifest=home/'asset_manifest.json'
    require(manifest.is_file() and not manifest.is_symlink(),'asset_integrity','missing/linked asset manifest')
    if expected_manifest_sha256 is not None:
        require(sha(manifest)==expected_manifest_sha256,'asset_integrity','installed manifest differs from trusted sealed manifest')
    record=read(manifest);cfg=config()
    required={'model.json','configuration.json','feature_contract.json',
              *(f'{folder}/{name}.json' for folder in ('snapshots','results') for name in cfg['snapshots'])}
    require(type(record.get('files')) is dict and required<=set(record['files']),
            'asset_integrity','manifest omits mandatory model/configuration/contract/snapshot/result files')
    for name,value in record['files'].items():
        p=home/name
        require(p.resolve().is_relative_to(home) and not p.is_symlink() and p.is_file() and sha(p)==value,
                'asset_integrity','changed artifact '+name)
    ident=record['identity']
    require(ident.get('model_sha256')==sha(home/'model.json'),'asset_integrity','identity model SHA differs from actual model')
    require(type(ident.get('features')) is dict and set(ident['features'])==set(cfg['snapshots']),
            'asset_integrity','identity must bind exactly three snapshot features')
    for name,expected in ident['features'].items():
        require(sha(home/'snapshots'/f'{name}.json')==expected,'asset_integrity','identity feature SHA differs: '+name)
    require(ident.get('dataset_id')==cfg['dataset_id'],'asset_integrity','asset dataset differs')
    require(ident.get('configuration_sha256')==sha(CONFIG) and
            ident.get('schema_sha256')==sha(ROOT/'schemas/m03_segments_v1.json'),
            'asset_integrity','registered configuration/contract source SHA differs')
    # These copies are canonical JSON, whereas identity hashes the original bytes.
    require(read(home/'configuration.json')==cfg and
            read(home/'feature_contract.json')==read(ROOT/'schemas/m03_segments_v1.json'),
            'asset_integrity','frozen configuration/contract copy differs from registered source')
    require(record['content_id']=='segments11'+digest(record['identity'])[:24],'asset_integrity','asset identity')
    return record

def verify_trusted_asset(home,trust,live=False):
    from product_core.release import verify_anchor
    return verify_asset(home,verify_anchor(home,trust,'segmentation'))

def evidence_identity(home, manifest):
    """Only call after asset verification; never infer expected identity from a response."""
    cfg=read(Path(home)/'configuration.json')
    return {'case_id':cfg['case_id'],'dataset_id':manifest['identity']['dataset_id'],
            'segmentation_model_id':read(Path(home)/'model.json')['segmentation_model_id'],
            'feature_contract':cfg['contract'],'snapshots':cfg['snapshots'],
            'model_sha256':manifest['identity']['model_sha256'],
            'features':manifest['identity']['features']}



class FrozenStore:
    """No raw data reads, fitting, labels, caches that bypass integrity, or pickle."""
    def __init__(self, home, trust=None):
        self.home=Path(home)
        require(trust is not None,'asset_integrity','product release trust required')
        self.trust=trust
        self.manifest=verify_trusted_asset(home,self.trust);self.model=read(self.home/'model.json')
        phases=read(self.home/'phases.json') if 'phases.json' in self.manifest['files'] else []
        self.frozen_at=next((p['actual_at'] for p in phases if p['phase']=='model_frozen'),None)
        self.cache={};self.load_count=0;self.assignment_count=0;self.fit_count=0
    def get(self, snapshot):
        require(snapshot in config()['snapshots'],'invalid_arguments','unknown snapshot')
        current=verify_trusted_asset(self.home,self.trust)
        require(current==self.manifest,'asset_integrity','asset manifest changed')
        require(sha(CONFIG)==current['identity']['configuration_sha256'],'asset_integrity','feature contract changed')
        require(sha(ROOT/'schemas/m03_segments_v1.json')==current['identity']['schema_sha256'],'asset_integrity','schema changed')
        key=(self.model['segmentation_model_id'],snapshot,self.manifest['identity']['features'][snapshot],sha(CONFIG))
        hit=key in self.cache
        if not hit:
            source=read(self.home/'snapshots'/f'{snapshot}.json');self.load_count+=1
            require(source['snapshot_id']==snapshot and source['S']==config()['snapshots'][snapshot]
                    and digest(source['rows'])==source['feature_fingerprint'],'asset_integrity','snapshot content identity')
            actual=assign(source,self.model);self.assignment_count+=1
            require(actual==read(self.home/'results'/f'{snapshot}.json'),'frozen_assignment','actual frozen assignment differs from build')
            self.cache[key]=public_view(actual)
        return self.cache[key],hit




