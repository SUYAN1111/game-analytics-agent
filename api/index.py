import os
import sys
from pathlib import Path
vendor=Path(__file__).resolve().parents[1]/'_core_vendor'
if vendor.is_dir():sys.path.insert(0,str(vendor))
if os.environ.get('VERCEL'):
    from tempfile import gettempdir
    temporary=Path(gettempdir())
    os.environ['APP_STATE_DIR']=str(temporary/'player-agent')
    os.environ['APP_DEBUG']='0'
    os.environ.pop('PYTHONPATH',None)
    # Set the asset root before importing any application paths or models.
    from cloud_api.asset_bundle import install_archive
    os.environ['APP_ASSET_DIR']=str(install_archive(vendor.parent,temporary/'player-agent-assets'))
from cloud_api.app import create_app
app=create_app()
