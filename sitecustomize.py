"""Linux child interpreters use the release's core dependency tree, never DSH's."""
import os
import sys
from pathlib import Path
vendor=Path(__file__).resolve().parent/'_core_vendor'
if os.name!='nt' and vendor.is_dir():sys.path.insert(0,str(vendor))
