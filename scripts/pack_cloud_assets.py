"""Package only registered simulated assets. No source, .env, state or credentials."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from product_core.release import verify
from product_core.paths import ASSETS

def main():
    manifest=verify()
    out=ROOT/'state/cloud-assets';out.mkdir(parents=True,exist_ok=True)
    path=out/(manifest['asset_set_id']+'.zip')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in sorted(manifest['asset_files']):
            item=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(item,(ASSETS/name).read_bytes())
    info={'filename':path.name,'bytes':path.stat().st_size,'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),
          'asset_set_id':manifest['asset_set_id'],'files':len(manifest['asset_files'])}
    (out/'bundle-info.json').write_text(json.dumps(info,indent=2),'utf8')
    print(json.dumps(info));print(path)
if __name__=='__main__':main()
