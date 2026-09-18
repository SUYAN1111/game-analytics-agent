"""Explicit one-time schema/budget initialization; never resets an existing ledger."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--budget',type=float,default=1)
    args=parser.parse_args()
    if not 0<args.budget<=5:raise SystemExit('Initial budget must be in (0,5] CNY')
    import psycopg
    with psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=10) as db:
        db.execute((ROOT/'cloud_api/schema.sql').read_text('utf8'))
        state={'limit_cny':args.budget,'max_attempts':336,'attempts':[],'tools':[],'closed_sessions':[],'stopped':False}
        db.execute('INSERT INTO agent_cloud.budgets VALUES(1,%s) ON CONFLICT(id) DO NOTHING',(json.dumps(state),))
    print('Schema ready. Existing history, budget and stop state retained.')
if __name__=='__main__':main()
