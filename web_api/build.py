"""Verify local production build bytes against the release-pinned inventory."""
from product_core.paths import ROOT
from product_core.release import verify, read, check_file


def verify_build():
    verify(False,include_build_sources=True)
    directory=ROOT/'web/dist'
    manifest=read(ROOT/'web/build-manifest.json')
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual!=set(manifest): raise ValueError('Web build is missing or changed; run npm.cmd --prefix web ci and npm.cmd --prefix web run build')
    for name,entry in manifest.items(): check_file(directory,name,entry)
