"""Externally pinned release. Hash actual bytes on every check; no stale cache."""
import hashlib,json
from pathlib import Path
from product_core.paths import ROOT,ASSETS

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text('utf-8'))
def json_sha(data):
    """Pin JSON values and array order; reject ambiguous/non-JSON representations."""
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def invalid_constant(value):raise ValueError('non-finite JSON number')
    value=json.loads(data.decode('utf-8-sig'),object_pairs_hook=unique,parse_constant=invalid_constant)
    canonical=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
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
    if not p.is_file():fail('missing/changed '+name)
    if p.stat().st_size==entry['size'] and sha(p)==entry['sha256']:return
    # Deployment tooling may reserialize its configuration. Only this
    # explicitly sealed JSON file may vary in whitespace/object-key order.
    # No fields are removed, overwritten or ignored; application/assets stay byte-pinned.
    if name=='vercel.json' and 'json_sha256' in entry:
        if p.stat().st_size>1024*1024:fail('oversized JSON '+name)
        try:actual=json_sha(p.read_bytes())
        except (ValueError,UnicodeError,RecursionError):fail('invalid JSON '+name)
        if actual==entry['json_sha256']:return
        fail('JSON content changed '+name+' (not just formatting); check the deployed commit and project overrides')
    fail('missing/changed '+name)
def build_only_source(name):
    # Vercel's Python builder omits these build inputs from the function bundle.
    # They remain pinned and mandatory during the source/build check. Runtime
    # serves the compiled web/dist assets, not the web/public source directory.
    return name in ('.gitignore','web/package-lock.json') or name.startswith('web/public/')

def verify(include_assets=True, *, include_build_sources=False):
    m=manifest()
    for n,e in m['source_files'].items():
        if include_build_sources or not build_only_source(n):check_file(ROOT,n,e)
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
