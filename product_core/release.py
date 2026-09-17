"""Externally pinned release. Hash actual bytes on every check; no stale cache."""
import hashlib,json
from pathlib import Path
from product_core.paths import ROOT,ASSETS

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text('utf-8'))
def fail(msg):
    from agent_runtime.common import HostError
    raise HostError('asset_integrity','product_integrity: '+msg)
def manifest():
    from product_core._release_anchor import RELEASE_SHA256
    p=ROOT/'product_release.json'
    if sha(p)!=RELEASE_SHA256:fail('release manifest differs from installed source anchor')
    return read(p)
def check_file(root,name,entry):
    p=root/name
    if Path(name).is_absolute() or '..' in Path(name).parts or not p.resolve().is_relative_to(root.resolve()):fail('unsafe path '+name)
    for part in [p,*p.parents]:
        if part==root.parent:break
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):fail('linked path '+name)
    if not p.is_file() or p.stat().st_size!=entry['size'] or sha(p)!=entry['sha256']:fail('missing/changed '+name)
def verify(include_assets=True):
    m=manifest()
    for n,e in m['source_files'].items():check_file(ROOT,n,e)
    if include_assets:
        for n,e in m['asset_files'].items():check_file(ASSETS,n,e)
    return m
def host():
    m=verify();h=read(ASSETS/'runtime/host.json')
    if h['role']!='analysis_demo':fail('role changed')
    return h
def asset_trust(kind):
    m=manifest();entry=m['asset_files'][kind+'/asset_manifest.json']
    return {'kind':'product_release','manifest_sha256':entry['sha256'],'release_id':m['release_id'],'asset_kind':kind}
def verify_anchor(home,trust,kind):
    m=verify(False)
    if Path(home).resolve()!=(ASSETS/kind).resolve() or trust!=asset_trust(kind):fail('asset outside trusted installed release')
    check_file(ASSETS,kind+'/asset_manifest.json',m['asset_files'][kind+'/asset_manifest.json'])
    return trust['manifest_sha256']
