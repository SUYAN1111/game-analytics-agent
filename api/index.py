import os
import sys
from pathlib import Path
vendor=Path(__file__).resolve().parents[1]/'_core_vendor'
if vendor.is_dir():sys.path.insert(0,str(vendor))
if os.environ.get('VERCEL'):
    os.environ['APP_STATE_DIR']='/tmp/player-agent'
    os.environ['APP_DEBUG']='0'
    os.environ.pop('PYTHONPATH',None)
from cloud_api.app import create_app
app=create_app()
