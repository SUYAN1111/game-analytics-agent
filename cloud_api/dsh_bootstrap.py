"""-S excludes core site-packages; the pinned SDK gets its own Pydantic version."""
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
assert sys.flags.no_site, 'DSH bootstrap must use python -S'
sys.path.insert(0, str(root / '_dsh_vendor'))
import pydantic
assert pydantic.__version__ == '2.12.5', 'DSH dependency isolation failed'
runpy.run_module('task13_runtime.dsh_driver', run_name='__main__')
