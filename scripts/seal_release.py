"""Explicit local release operation; never called automatically by server startup."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def entry(path): return {'size': path.stat().st_size, 'sha256': sha(path)}
def save(path, value): path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n', encoding='utf-8')

def main():
    path = ROOT / 'product_release.json'
    manifest = json.loads(path.read_text('utf-8'))
    if 'parent_release' not in manifest:
        manifest['parent_release'] = {'release_id': manifest['release_id'], 'manifest_sha256': sha(path), 'task': 'Task14'}
    dist = ROOT / 'web/dist'
    if not (dist/'index.html').exists(): raise SystemExit('Build web first: npm.cmd --prefix web run build')
    save(ROOT/'web/build-manifest.json', {p.relative_to(dist).as_posix(): entry(p) for p in sorted(dist.rglob('*')) if p.is_file()})
    names = set(manifest['source_files'])
    names.add('task13_runtime/progress.py')
    names.add('task13_runtime/request_scope.py')
    names.discard('sitecustomize.py')
    names.update(('requirements.txt','.python-version','vercel.json','.vercelignore','agent_runtime/posix_processes.py'))
    for directory in ('web', 'web_api', 'scripts', 'docs', 'cloud_api', 'api'):
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and not any(part in ('node_modules','dist','__pycache__','.vite') for part in p.relative_to(ROOT).parts):
                names.add(p.relative_to(ROOT).as_posix())
    names.discard('product_core/_release_anchor.py')
    names.discard('product_release.json')
    manifest['source_files'] = {name: entry(ROOT/name) for name in sorted(names)}
    manifest['build_contract'] = 'npm ci + npm run build; web/build-manifest.json pins dist bytes; dist and dependencies excluded from source inventory'
    identity = json.dumps({'source_files': manifest['source_files'], 'asset_set_id': manifest['asset_set_id'], 'parent': manifest['parent_release']}, sort_keys=True).encode()
    manifest['release_id'] = 'product15'+hashlib.sha256(identity).hexdigest()[:24]
    save(path, manifest)
    (ROOT/'product_core/_release_anchor.py').write_text("RELEASE_SHA256 = '"+sha(path)+"'\n", encoding='utf-8')
    print(manifest['release_id'], manifest['asset_set_id'])

if __name__ == '__main__': main()
