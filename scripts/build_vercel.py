"""Reproducible Linux build. Never reseal or weaken the installed release manifest."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def assets():
    from product_core.release import manifest,check_file
    m=manifest();home=ROOT/'assets'
    if all((home/n).is_file() for n in m['asset_files']):
        for n,e in m['asset_files'].items():check_file(home,n,e)
        return
    url=os.environ.get('ASSET_BUNDLE_URL','')
    if not url.startswith('https://'):raise SystemExit('Set ASSET_BUNDLE_URL to the HTTPS release asset URL; do not put a token in the URL.')
    # The downloaded zip is untrusted. Installed path, size and hashes are authoritative.
    with tempfile.TemporaryFile() as file:
        with urllib.request.urlopen(url,timeout=60) as response:
            size=0
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>300*1024*1024:raise ValueError('asset bundle exceeds 300 MiB')
                file.write(chunk)
        file.seek(0)
        with zipfile.ZipFile(file) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)) or set(names)!=set(m['asset_files']):raise ValueError('asset archive inventory mismatch')
            for name,entry in m['asset_files'].items():
                item=archive.getinfo(name)
                if item.file_size!=entry['size']:raise ValueError('asset size mismatch')
                target=(home/name).resolve()
                if not target.is_relative_to(home.resolve()):raise ValueError('unsafe asset path')
                data=archive.read(item)
                if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('asset hash mismatch')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)

def main():
    environment=f'{sys.platform} / Python {sys.version.split()[0]} ({sys.executable})'
    print('Cloud build environment: '+environment,flush=True)
    if sys.platform!='linux' or sys.version_info[:2]!=(3,14):
        raise SystemExit('Cloud build requires Linux / Python 3.14; got '+environment+
            '. Use the uv build command from vercel.json; the system python may have a different version.')
    os.chdir(ROOT)
    core=[line for line in (ROOT/'requirements-core.lock').read_text().splitlines() if line and not line.startswith('pywin32==')]
    core+=['psycopg[binary]==3.3.3']
    for target,requirements in [('_core_vendor',core),('_dsh_vendor',(ROOT/'requirements-dsh.lock').read_text().splitlines())]:
        subprocess.run([sys.executable,'-m','pip','install','--only-binary=:all:','--target',target,*requirements],check=True)
    assets()
    subprocess.run(['npm','run','build','--prefix','web'],check=True)
    from product_core.release import verify
    from web_api.build import verify_build
    verify();verify_build()
    print('Linux dependencies, assets, source and frontend build verified; cloud runtime still needs acceptance testing.')
if __name__=='__main__':main()
