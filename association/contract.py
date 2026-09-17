"""Concrete Task12 contract, UTC seconds and deterministic file primitives."""
import csv
import json
import re
from datetime import timedelta
from pathlib import Path
from agent_runtime.common import ROOT,HostError,canonical,digest,read,write,sha,require,now
from analysis_core.temporal import parse_utc

BUSINESS=ROOT/'business_configs/activity_rules_v1.json'
SCHEMA=ROOT/'schemas/activity_raw_v1.json'
RULE_SCHEMA=ROOT/'schemas/activity_rules_v1.json'
TABLES=('activity_catalog','activity_windows','activity_source_catalog','activity_uploads','collection_checks','watermark_checks')
UPSTREAM='m035c1fae9c52860eb04c4565ca'
from product_core.paths import ASSETS
OBSERVED=ASSETS/'data/generated'/UPSTREAM/'observed'
METADATA=('players','player_attributes','story_calendar')
ITEMS=tuple(f'A{i:02}' for i in range(1,7))
EVALUATIONS={'discovery_V1_V3':['V1','V2','V3'],'validation_V4':['V4'],'validation_V5':['V5'],'validation_V6':['V6']}

def config(value=None):
    c=read(BUSINESS) if value is None else value
    require(c['case_id']=='case_activity_week_v1' and c['metric_id']=='activity_association_v1' and
        c['contract']=='activity_week_basket_v1' and c['upstream_dataset_id']==UPSTREAM and
        c['activities']==dict(zip(ITEMS,('支线体验','地图探索','素材收集','战斗挑战','协作玩法','休闲小游戏'))) and c['sources']=={'R1':'actsrc01','R2':'actsrc02','R3':'actsrc03'} and
        c['window_seconds']==604800 and c['delivery_wait_seconds']==86400 and c['evaluations']==EVALUATIONS and
        c['thresholds']=={'support':'1/20','confidence':'2/5','lift':'11/10','joint_count':50} and
        c['max_itemset_size']==3 and c['max_antecedent_size']==2 and c['consequent_size']==1 and
        c['display_limit']==10 and c['public_min_count']==20 and c['basket_size_bins']==['0','1','2','3','4+'] and
        c['sort']==['lift_desc','confidence_desc','support_desc','antecedent_size_asc','antecedent_lex','consequent_lex'],
        'contract','fixed Task12 business contract differs')
    require(not any(k in canonical(c) for k in ('main_seed','theta_coefficient','g_beta','final_label')),
            'contract','private generation mechanism in business contract')
    return c

def utc(s):
    require(type(s) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',s),'time','UTC integer seconds required')
    return parse_utc(s,'activity UTC')

def iso(t):return t.strftime('%Y-%m-%dT%H:%M:%SZ')
def shift(s,seconds):return iso(utc(s)+timedelta(seconds=seconds))
def stable(prefix,*keys):return prefix+digest(list(keys))[:32]

def rows(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            value=json.loads(line);require(type(value) is dict,'row','JSONL object required');yield value

def write_rows(path,values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        for row in values:stream.write(canonical(row)+'\n')

def csv_rows(path,values,fields):
    with Path(path).open('x',encoding='utf-8-sig',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
        for row in values:w.writerow({k:canonical(row[k]) if isinstance(row.get(k),(dict,list)) else row.get(k) for k in fields})

def validate_row(table,row,definitions=None):
    definition=(read(SCHEMA)['tables'] if definitions is None else definitions)[table]
    require(type(row) is dict and set(row)==set(definition['fields']),'row','wrong fields in '+table)
    for name,field in definition['fields'].items():
        value=row[name]
        require(value is not None or field.get('nullable',False),'row','null '+table+'.'+name)
        if value is None:continue
        if field['type']=='utc_time':utc(value)
        else:require(type(value) is str and bool(value.strip()),'row','nonempty string '+table+'.'+name)
        if 'enum' in field:require(value in field['enum'],'row','invalid enum '+table+'.'+name)
    return row

def load_metadata(home=OBSERVED):
    return {table:list(rows(Path(home)/(table+'.jsonl'))) for table in METADATA}

def calendar(metadata):
    c=config();out=[];seen=set()
    for r in sorted(metadata['story_calendar'],key=lambda r:(r['version_id'],r['region_id'])):
        key=(r['version_id'],r['region_id']);require(key not in seen,'calendar','duplicate regional version');seen.add(key)
        require(r['region_id'] in c['sources'] and r['version_id'] in ('V1','V2','V3','V4','V5','V6'),'calendar','unknown region/version')
        start=r['region_open_at'];utc(start)
        out.append({'window_id':'week_'+r['version_id']+'_'+r['region_id'],'version_id':r['version_id'],
            'region_id':r['region_id'],'w_start':start,'w_end':shift(start,604800),'available_at':shift(start,-604800)})
    for w in out:w['as_of']=shift(max(x['w_end'] for x in out if x['version_id']==w['version_id']),86400)
    return out

def candidates(metadata,windows):
    from features.observed import select_metadata
    require(len({p['user_id'] for p in metadata['players']})==len(metadata['players']),'metadata','duplicate user')
    attrs={}
    for a in metadata['player_attributes']:attrs.setdefault(a['user_id'],[]).append(a)
    selected=[]
    for w in windows:
        for p in metadata['players']:
            if utc(p['registered_at'])>utc(w['w_start']) or utc(p['available_at'])>utc(w['w_start']):continue
            a=select_metadata(attrs.get(p['user_id'],[]),w['w_start'],'attribute')
            if a['region_id']==w['region_id']:selected.append({'user_id':p['user_id'],**w})
    require(len({(r['user_id'],r['version_id']) for r in selected})==len(selected),'metadata','multiple regions for same player/version')
    return sorted(selected,key=lambda r:(r['version_id'],r['window_id'],r['user_id']))
