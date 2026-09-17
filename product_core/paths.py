"""Explicit independent roots; never fall back to the experiment repository."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS=Path(os.environ.get('APP_ASSET_DIR',ROOT/'assets')).resolve()
STATE=Path(os.environ.get('APP_STATE_DIR',ROOT/'state')).resolve()
if ASSETS==ROOT or STATE==ROOT or STATE==ASSETS or STATE.is_relative_to(ASSETS) or ASSETS.is_relative_to(STATE):
    raise ValueError('source, asset and state roots must be separate')
def within_state(path):
    p=Path(path).resolve()
    if not p.is_relative_to(STATE):raise ValueError('output must be under APP_STATE_DIR')
    return p
