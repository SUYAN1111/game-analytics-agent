"""Ship sealed assets as one archive so platform directory filters cannot drop data.

Only standard-library imports: the entrypoint must install assets and set
APP_ASSET_DIR before any module imports product_core.paths.
"""
import hashlib
import errno
import json
import os
import re
import stat
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from agent_runtime.common import HostError
from product_core._release_anchor import RELEASE_SHA256

ARCHIVE_NAME='runtime-assets.zip'


def fail(message):
    raise HostError('asset_integrity','cloud_asset_bundle: '+message)


def sealed_manifest(root):
    raw=(Path(root)/'product_release.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=RELEASE_SHA256:
        fail('release manifest differs from installed source anchor')
    manifest=json.loads(raw)
    if not re.fullmatch(r'asset[0-9a-f]{16,64}',manifest['asset_set_id']):
        fail('invalid asset identity')
    for name in manifest['asset_files']:
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or path.as_posix()!=name or '\\' in name or ':' in name:
            fail('unsafe registered asset path')
    return manifest


def verify_tree(directory, manifest):
    directory=Path(directory)
    for name,entry in manifest['asset_files'].items():
        path=directory/name
        for part in [path,*path.parents]:
            if part==directory.parent:break
            if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
                fail('linked asset '+name)
        if not path.is_file() or path.stat().st_size!=entry['size']:
            fail('missing/changed '+name)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=entry['sha256']:
                fail('missing/changed '+name)


def build_archive(root, assets):
    """Build artifact only; no new public asset upload or manifest resealing."""
    root,assets=Path(root),Path(assets)
    manifest=sealed_manifest(root)
    verify_tree(assets,manifest)
    output=root/ARCHIVE_NAME
    with tempfile.NamedTemporaryFile(prefix='runtime-assets-',suffix='.zip',dir=root,delete=False) as temporary:
        staged=Path(temporary.name)
    try:
        with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,entry in sorted(manifest['asset_files'].items()):
                data=(assets/name).read_bytes()
                if len(data)!=entry['size'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
                    fail('changed during packaging '+name)
                info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,data)
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    return output


@contextmanager
def installation_lock(cache_root):
    """OS-owned lock: simultaneous cold starts must not unpack duplicate trees.

    The kernel releases the lock if a worker dies; the tiny lock file stays.
    """
    with (cache_root/'.install.lock').open('a+b') as stream:
        if not stream.seek(0, 2):
            stream.write(b'\0');stream.flush()
        started=time.monotonic()
        while True:
            try:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES,errno.EAGAIN):raise
                if time.monotonic()-started>60:fail('asset installation lock timed out')
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def install_archive(root, cache_root):
    """Validate, unpack, and atomically publish one immutable asset-set directory.

    Serialize cold starts so staging never doubles the temporary disk footprint.
    An existing but damaged cache is rejected, never repaired silently or accepted
    on the strength of a marker file.
    """
    root,cache_root=Path(root),Path(cache_root)
    manifest=sealed_manifest(root)
    cache_root.mkdir(parents=True,exist_ok=True)
    with installation_lock(cache_root):
        return _install_archive(root,cache_root,manifest)


def _install_archive(root, cache_root, manifest):
    target=cache_root/manifest['asset_set_id']
    if target.exists() or target.is_symlink():
        verify_tree(target,manifest)
        return target.resolve()
    archive_path=root/ARCHIVE_NAME
    if not archive_path.is_file() or archive_path.stat().st_size>300*1024*1024:
        fail('missing/oversized runtime archive; rebuild the deployment')
    cache_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='unpack-',dir=cache_root) as temporary:
        stage=Path(temporary)/'assets';stage.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            infos=archive.infolist()
            names=[info.filename for info in infos]
            if len(names)!=len(set(names)) or set(names)!=set(manifest['asset_files']):
                fail('archive inventory differs from sealed assets')
            for info in infos:
                name=info.filename;entry=manifest['asset_files'][name]
                if (info.file_size!=entry['size'] or info.is_dir() or info.flag_bits&1 or
                    stat.S_ISLNK(info.external_attr>>16) or
                    info.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)):
                    fail('invalid archive entry '+name)
                path=stage/name
                if not path.resolve().is_relative_to(stage.resolve()):fail('unsafe archive path')
                path.parent.mkdir(parents=True,exist_ok=True)
                digest=hashlib.sha256();size=0
                with archive.open(info) as source,path.open('xb') as dest:
                    while chunk:=source.read(1024*1024):
                        size+=len(chunk)
                        if size>entry['size']:fail('oversized archive entry '+name)
                        digest.update(chunk);dest.write(chunk)
                if size!=entry['size'] or digest.hexdigest()!=entry['sha256']:
                    fail('changed archive entry '+name)
        verify_tree(stage,manifest)
        try:stage.rename(target)
        except OSError:
            if not target.exists():raise
            verify_tree(target,manifest)
    return target.resolve()
