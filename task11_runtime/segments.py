"""Strict ninth tool and separate current-turn segmentation evidence."""
import copy
import re
from uuid import uuid4
from agent_runtime.common import HostError,digest,now,require
from segmentation.contract import FEATURES,config
from segmentation.assets import FrozenStore

OVERALL=('candidate_count','eligible_count','assigned_count','unassigned_eligible_count','insufficient_history_count',
         'coverage_incomplete_count','observed_no_completed_session_count','assignment_coverage')
GROUP=('player_count','share_of_assigned',*(f+'.'+s for f in FEATURES for s in ('mean','median')))
LABELS={'candidate_count':'候选玩家数','eligible_count':'可分群玩家数','assigned_count':'已分配玩家数',
    'unassigned_eligible_count':'可分群但未分配玩家数','insufficient_history_count':'完整历史不足玩家数',
    'coverage_incomplete_count':'覆盖证据不足玩家数','observed_no_completed_session_count':'完整观察零完成会话玩家数',
    'assignment_coverage':'分配覆盖率','player_count':'群玩家数','share_of_assigned':'占已分配玩家比例',
    'completed_active_dates_14d':'完成会话UTC日期数','completed_sessions_14d':'完成会话数',
    'median_session_minutes_14d':'个人会话分钟中位数','session_45min_share_14d':'个人至少45分钟会话占比'}
STATUS_NOTES={'model_unavailable':'segmentation_unavailable','restricted_granularity':'segmentation_restricted'}
# Public topic navigation, not retrieved evidence, test IDs, or observed answers.
KNOWLEDGE_GUIDANCE={
    'status':'retrieval_guidance_only_not_citable',
    'profiles':{'query':'群画像 原量纲 中位数 开发中心 分母',
        'applies_to':'群画像均值或中位数；须引用当前成员统计与开发中心区别的资料'},
    'zero_sessions':{'query':'分群四列特征 历史不足 覆盖不足 零会话',
        'applies_to':'零会话与未分群处理；不能替代画像口径'},
    'frozen_assignment':{'query':'冻结分群分配 标准化尺度 中心距离 固定群ID',
        'applies_to':'同一冻结模型的后续分配'},
    'comparison_limits':{'query':'跨快照 横截面 个人迁移 因果 付费标签',
        'applies_to':'快照比较与解释、个人身份、付费命名或重新训练的范围限制'},
    'coverage_denominator':{'query':'群画像 分母 分配覆盖率 全部候选',
        'applies_to':'分群覆盖分母；M03分母需另检索原M03资料'}}

def tool(model_id):
    return {'name':'assign_segments','description':'读取冻结历史会话分群，对指定快照实际分配并返回公开聚合；不拟合、不返回个人。返回证据只能放最终JSON的cluster_selections，使用s编号和{{cluster:s1}}，不得放入M03的claims；即使字段同名candidate_count也不例外。',
        'input_schema':{'type':'object','properties':{'segmentation_model_id':{'type':'string','enum':[model_id]},
                          'snapshot_id':{'type':'string','enum':list(config()['snapshots'])}},
                        'required':['segmentation_model_id','snapshot_id'],'additionalProperties':False},
        'output_schema':{'type':'object','required':['evidence_type','tool_name','request_id','session_id','turn_id','evidence_id',
            'status','error','warnings','data','content_fingerprint','execution'],'additionalProperties':True}}

def semantic(result):
    return {k:copy.deepcopy(result[k]) for k in ('evidence_type','tool_name','status','validated_arguments','data','error','warnings')}

class SegmentService:
    def __init__(self,asset,session_id,trust=None):self.store=FrozenStore(asset,trust);self.session_id=session_id
    def catalog(self):return tool(self.store.model['segmentation_model_id'])
    def dispatch(self,args,turn_id):
        r={'evidence_type':'segmentation_v1','tool_name':'assign_segments','request_id':'sreq'+uuid4().hex,
           'session_id':self.session_id,'turn_id':turn_id,'evidence_id':None,'validated_arguments':copy.deepcopy(args),
           'data':None,'error':None,'warnings':[]};hit=False
        try:
            require(type(args) is dict and set(args)=={'segmentation_model_id','snapshot_id'} and
                all(type(v) is str for v in args.values()),'invalid_arguments','exactly two string arguments required')
            require(args['segmentation_model_id']==self.store.model['segmentation_model_id'],'invalid_arguments','unknown frozen model')
            value,hit=self.store.get(args['snapshot_id'])
            r['data']={**copy.deepcopy(value),'case_id':config()['case_id'],'dataset_id':config()['dataset_id'],
                'feature_contract':config()['contract'],'input_sha256':self.store.manifest['identity']['features'][args['snapshot_id']],
                'knowledge_guidance':copy.deepcopy(KNOWLEDGE_GUIDANCE),
                'selection_contract':{'answer_array':'cluster_selections','id_prefix':'s','body_block':'cluster',
                    'scope_fields':['segmentation_model_id','snapshot_id','segment_id'],
                    'knowledge_metric_id':'historical_session_segments_v1','forbidden_answer_array':'claims'},
                'model_sha256':self.store.manifest['identity']['model_sha256'],
                'freeze':{'development_snapshot_id':'fit_V3main','development_S':config()['snapshots']['fit_V3main'],
                          'configuration_sha256':self.store.manifest['identity']['configuration_sha256'],
                          'algorithm':'KMeans; fixed representative seed; no later fit'}}
            r['status']=value['status'];r['evidence_id']='segments11_'+uuid4().hex
        except (HostError,OSError) as exc:
            r['status']='error';r['error']={'type':type(exc).__name__,'code':getattr(exc,'code','asset_integrity'),
                'message':'registered frozen asset unavailable' if isinstance(exc,OSError) else str(exc)}
        r['content_fingerprint']=digest(semantic(r));r['execution']={'at':now(),'cache_hit':hit,
            'feature_load_count':self.store.load_count,'assignment_count':self.store.assignment_count,'fit_count':self.store.fit_count,
            'actual_model_frozen_at':self.store.frozen_at}
        return r

class ClusterEvidence:
    def __init__(self,trusted_identity,validate_asset=None):
        require(type(trusted_identity) is dict and set(trusted_identity)=={'case_id','dataset_id','segmentation_model_id',
                'feature_contract','snapshots','model_sha256','features'},'cluster_identity','host trusted asset identity required')
        self.identity=copy.deepcopy(trusted_identity);self.model_id=self.identity['segmentation_model_id']
        self.validate_asset=validate_asset;self.entries={};self.requests=set()
    def add(self,r,session,turn,arguments):
        if self.validate_asset is not None:self.validate_asset()
        require(r.get('evidence_type')=='segmentation_v1' and r.get('tool_name')=='assign_segments','cluster_identity','wrong producer')
        require(r['session_id']==session and r['turn_id']==turn,'cluster_session','wrong current session/turn')
        require(r['request_id'] not in self.requests and digest(semantic(r))==r['content_fingerprint'],'cluster_fingerprint','duplicate request or changed content')
        require(r.get('validated_arguments')==arguments,'cluster_identity','response differs from actual MCP arguments')
        if r['error']:
            require(r['error']['code']!='asset_integrity','asset_integrity','asset changed; stop answer')
            self.requests.add(r['request_id']);return
        expected=self.identity
        require(type(arguments) is dict and set(arguments)=={'segmentation_model_id','snapshot_id'} and
                arguments['segmentation_model_id']==self.model_id and arguments['snapshot_id'] in expected['snapshots'],
                'cluster_identity','untrusted model/snapshot call')
        snapshot=arguments['snapshot_id'];data=r['data']
        fields={k:expected[k] for k in ('case_id','dataset_id','segmentation_model_id','feature_contract','model_sha256')}
        fields.update(snapshot_id=snapshot,S=expected['snapshots'][snapshot],input_sha256=expected['features'][snapshot])
        require(type(data) is dict and all(data.get(k)==v for k,v in fields.items()),
                'cluster_identity','response identity differs from host trusted asset/call: '+
                repr([k for k,v in fields.items() if not isinstance(data,dict) or data.get(k)!=v]))
        require(r['evidence_id'] not in self.entries,'cluster_identity','duplicate evidence')
        self.requests.add(r['request_id'])
        self.entries[r['evidence_id']]=copy.deepcopy(r)
    def select(self,s,session,turn):
        if self.validate_asset is not None:self.validate_asset()
        require(type(s) is dict and set(s)=={'id','evidence_id','field','scope'} and type(s['id']) is str
                and re.fullmatch(r's(?:[1-9]|1[0-2])',s['id']),'cluster_selection','invalid cluster selection')
        require(type(s['evidence_id']) is str and s['evidence_id'] in self.entries,'cluster_evidence','not a returned cluster evidence')
        r=self.entries[s['evidence_id']];d=r['data'];scope=s['scope'];field=s['field']
        require(r['session_id']==session and r['turn_id']==turn,'cluster_session','must requery this turn')
        require(digest(semantic(r))==r['content_fingerprint'],'cluster_fingerprint','stored content changed')
        require(type(scope) is dict and set(scope)=={'segmentation_model_id','snapshot_id','segment_id'} and
                scope['segmentation_model_id']==d['segmentation_model_id'] and scope['snapshot_id']==d['snapshot_id'],
                'cluster_scope','wrong scope or override')
        require(type(field) is str,'cluster_selection','field must be string')
        presentation=config()['claims']
        require(presentation['overall_fields']==list(OVERALL) and presentation['group_fields']==list(GROUP),
                'contract','claim field configuration differs from fixed binding')
        group=scope['segment_id']
        if group is None:
            require(field in OVERALL,'cluster_field','overall field not allowed')
            require(r['status']!='restricted_granularity' or field=='candidate_count','cluster_restricted','partition hidden')
            value=d['counts'][field];denom=d['counts']['candidate_count'] if field=='assignment_coverage' else None
        else:
            require(type(group) is str and r['status']=='ok' and field in GROUP,'cluster_restricted','group unavailable/restricted')
            matches=[g for g in d['groups'] if g['segment_id']==group];require(len(matches)==1,'cluster_scope','unknown group')
            g=matches[0];value=g[field] if '.' not in field else g['features'][field.split('.')[0]][field.split('.')[1]]
            denom=d['counts']['assigned_count'] if field=='share_of_assigned' else g['player_count'] if '.' in field else None
        base=field.split('.')[0];ratio=field in ('assignment_coverage','share_of_assigned') or base=='session_45min_share_14d'
        unit=presentation['feature_units'][base] if base in FEATURES else presentation['ratio_unit'] if ratio else presentation['count_unit']
        label=LABELS[base]+('的群均值' if field.endswith('.mean') else '的群中位数' if field.endswith('.median') else '')
        integer='.' not in field and not ratio;precision=presentation['count_precision'] if integer else presentation['statistic_precision']
        display='不可计算' if value is None else (str(value) if integer else f'{value:.{precision}f}')
        rendered=f"历史会话描述性分群｜模型={scope['segmentation_model_id']}｜快照={scope['snapshot_id']}（S={d['S']}）｜群={group or '全部候选'}｜{label} [{field}]：{display} {unit}"
        if denom is not None:rendered+=f'；分母/汇总样本数={denom}人'
        return {'selection':copy.deepcopy(s),'value':value,'unit':unit,'denominator':denom,'precision':precision,
                'content_fingerprint':r['content_fingerprint'],'rendered_fact':rendered,'verification_status':'reference_checked_candidate'}
    def note_allowed(self,note,turn):
        return any(r['turn_id']==turn and STATUS_NOTES.get(r['status'])==note for r in self.entries.values())
