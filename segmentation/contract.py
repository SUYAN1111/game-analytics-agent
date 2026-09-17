"""Concrete, immutable Task11 contract and JSON-only artifact primitives."""
import csv
import json
import math
from pathlib import Path
from agent_runtime.common import ROOT, HostError, digest, read, require, sha, write, now
from analysis_core.temporal import parse_utc as _parse_utc, format_utc

def parse_utc(value, field='Task11 UTC time'):
    return _parse_utc(value, field)

CONFIG = ROOT/'business_configs/m03_segments_v1.json'
FEATURES = ('completed_active_dates_14d','completed_sessions_14d','median_session_minutes_14d','session_45min_share_14d')
STATES = ('insufficient_history','coverage_incomplete','observed_no_completed_session','eligible')
TABLES = ('players','player_attributes','source_catalog','session_uploads','collection_checks','watermark_checks','story_calendar')
EXPECTED_ENV = {'numpy':'2.4.2','scipy':'1.17.1','scikit-learn':'1.8.0','matplotlib':'3.10.8'}

def config():
    value = read(CONFIG)
    require(value['features'] == list(FEATURES) and value['history_days']==14 and value['k']==[2,3,4]
            and value['seeds']==list(range(20260916,20260921)) and value['representative_seed']==20260916
            and value['public_min_count']==20 and value['selection_tolerance']==.01
            and value['min_cluster_absolute']==20 and value['min_cluster_fraction']==.01
            and value['kmeans']=={'init':'k-means++','n_init':10,'algorithm':'lloyd','max_iter':300,'tol':1e-4,'copy_x':True}
            and value['dataset_id']=='m035c1fae9c52860eb04c4565ca'
            and value['snapshots']=={'fit_V3main':'2025-03-17T14:00:00Z','replay_V5main':'2025-05-12T14:00:00Z','replay_V6main':'2025-06-09T14:00:00Z'},
            'contract','fixed Task11 contract changed')
    return value

def rows(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            value=json.loads(line)
            require(type(value) is dict,'row','JSONL object required')
            yield value

def write_rows(path, values):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        for value in values:
            stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n')

def csv_rows(path, values, fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for value in values:
            writer.writerow({k:json.dumps(value.get(k),ensure_ascii=False,allow_nan=False)
                             if isinstance(value.get(k),(dict,list)) else value.get(k) for k in fields})

def matrix(values):
    import numpy as np
    require(all(set(v)==set(FEATURES) and all(type(v[k]) in (int,float) and math.isfinite(v[k]) for k in FEATURES)
                for v in values),'features','exact finite numeric feature columns required')
    return np.asarray([[v[k] for k in FEATURES] for v in values],dtype=np.float64).reshape((-1,4))
