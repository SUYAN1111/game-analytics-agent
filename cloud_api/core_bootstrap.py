"""Explicit core imports for clean Linux child processes; no PYTHONPATH or site hook."""
import json
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('task13_runtime.bridge', 'task13_runtime.launch_mcp', 'case_adapters.m03_prediction')


def core_command(module, *arguments, executable=None):
    if module not in MODULES:
        raise ValueError('unregistered core child module')
    prefix = [] if os.name == 'nt' else ['-S', '-m', 'cloud_api.core_bootstrap']
    return [executable or sys.executable, *prefix, *(['-m'] if os.name == 'nt' else []), module, *arguments]


def main():
    if not sys.flags.no_site:
        raise RuntimeError('core bootstrap must use python -S')
    vendor = ROOT / '_core_vendor'
    if not vendor.is_dir():
        raise RuntimeError('isolated core dependencies missing')
    sys.path.insert(0, str(vendor))
    import pydantic
    if pydantic.__version__ != '2.13.4':
        raise RuntimeError('core dependency isolation failed')
    if sys.argv[1:] == ['--check']:
        import importlib
        packages = {}
        for name in ('pydantic', 'mcp', 'numpy', 'scipy', 'sklearn'):
            module = importlib.import_module(name)
            if not Path(module.__file__).resolve().is_relative_to(vendor.resolve()):
                raise RuntimeError('core dependency imported from outside its vendor tree: ' + name)
            packages[name] = str(getattr(module, '__version__', 'installed'))
        print(json.dumps({'no_site': True, 'packages': packages, 'credential_present': 'DEEPSEEK_API_KEY' in os.environ}))
        return
    if len(sys.argv) < 2 or sys.argv[1] not in MODULES:
        raise ValueError('unregistered core child module')
    sys.argv = sys.argv[1:]
    runpy.run_module(sys.argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
