"""Tenth tool; host-bound identities, scopes, directions, labels and units."""
import copy
import re
from uuid import uuid4
from association.contract import *
from association.assets import FrozenStore,verify_trusted
from association.public import tool_view

OVERALL=('candidate_basket_count','eligible_basket_count','nonempty_basket_count','empty_basket_count','coverage_incomplete_count',
         'eligible_unique_player_count','frozen_rule_count','displayed_rule_count')
FIELDS=('antecedent_count','consequent_count','joint_count','support','confidence','lift')
NOTES={'no_rules':'rules_none','no_eligible_baskets':'rules_no_eligible','restricted_granularity':'rules_restricted'}
LABELS={'candidate_basket_count':'候选篮子数','eligible_basket_count':'有效篮子数N','nonempty_basket_count':'非空有效篮子数',
    'empty_basket_count':'完整空篮子数','coverage_incomplete_count':'覆盖不足篮子数','eligible_unique_player_count':'有效篮子涉及不同玩家数',
    'frozen_rule_count':'冻结合格规则数','displayed_rule_count':'固定展示规则数','antecedent_count':'前件篮子数nA',
    'consequent_count':'后件篮子数nB','joint_count':'联合篮子数nAB','support':'支持度','confidence':'置信度','lift':'提升度'}

def semantic(r):return {k:copy.deepcopy(r[k]) for k in ('evidence_type','tool_name','status','validated_arguments','data','error','warnings')}

def tool(identifier):
    return {'name':'query_association_rules','description':'查询新增独立模拟活动的冻结Apriori规则，在固定评价篮子上实际复算；含空篮子。只返回公开聚合。所有数字必须放rule_selections，r编号和{{rule:r1}}块；禁止放claims或cluster_selections。',
        'input_schema':{'type':'object','properties':{'rule_set_id':{'type':'string','enum':[identifier]},
            'evaluation_id':{'type':'string','enum':list(EVALUATIONS)}},'required':['rule_set_id','evaluation_id'],'additionalProperties':False},
        'output_schema':{'type':'object','required':['evidence_type','tool_name','request_id','session_id','turn_id','evidence_id','status','data','error','content_fingerprint','execution'],'additionalProperties':True}}

class RuleService:
    def __init__(self,home,session,trust):self.store=FrozenStore(home,trust);self.session=session
    def catalog(self):return tool(self.store.rules['rule_set_id'])
    def dispatch(self,args,turn):
        r={'evidence_type':'activity_rules_v1','tool_name':'query_association_rules','request_id':'rreq'+uuid4().hex,
           'session_id':self.session,'turn_id':turn,'evidence_id':None,'validated_arguments':copy.deepcopy(args),'data':None,'error':None,'warnings':[]};hit=False
        try:
            require(type(args) is dict and set(args)=={'rule_set_id','evaluation_id'} and all(type(v) is str for v in args.values()),'invalid_arguments','exactly two string arguments')
            require(args['rule_set_id']==self.store.rules['rule_set_id'],'invalid_arguments','unknown frozen rules')
            full,hit=self.store.get(args['evaluation_id']);value=tool_view(full);i=self.store.manifest['identity']
            r['data']={**value,**{k:i[k] for k in ('case_id','activity_dataset_id','basket_contract','definition_fingerprint','rules_sha256')},
                'basket_sha256':i['baskets'][args['evaluation_id']],'versions':EVALUATIONS[args['evaluation_id']],
                'activity_names':config()['activities'],'selection_contract':{'array':'rule_selections','prefix':'r','block':'rule',
                    'overall_fields':list(OVERALL),'rule_fields':list(FIELDS),'scope':['rule_set_id','evaluation_id','rule_id']}}
            r['status']=value['status'];r['evidence_id']='rules12_'+uuid4().hex
        except (HostError,OSError) as exc:
            r['status']='error';r['error']={'type':type(exc).__name__,'code':getattr(exc,'code','asset_integrity'),'message':str(exc)}
        r['content_fingerprint']=digest(semantic(r));r['execution']={'at':now(),'cache_hit':hit,'basket_load_count':self.store.basket_load_count,
            'evaluation_count':self.store.evaluation_count,'mine_count':self.store.mine_count};return r

class RuleEvidence:
    def __init__(self,home,trust):
        self.home=Path(home);self.trust=copy.deepcopy(trust);self.manifest=verify_trusted(home,trust)
        self.identity=copy.deepcopy(self.manifest['identity']);self.entries={};self.requests=set()
    def validate(self):require(verify_trusted(self.home,self.trust)==self.manifest,'asset_integrity','activity asset changed')
    def add(self,r,session,turn,arguments):
        self.validate();require(r.get('evidence_type')=='activity_rules_v1' and r.get('tool_name')=='query_association_rules','rule_identity','wrong evidence family')
        require(r['session_id']==session and r['turn_id']==turn,'rule_session','not current session/turn')
        require(r['request_id'] not in self.requests and digest(semantic(r))==r['content_fingerprint'],'rule_fingerprint','duplicate/altered result')
        require(r['validated_arguments']==arguments,'rule_identity','actual MCP arguments differ')
        if r['error']:
            require(r['error']['code']!='asset_integrity','asset_integrity','activity asset failure');self.requests.add(r['request_id']);return
        i=self.identity;require(set(arguments)=={'rule_set_id','evaluation_id'} and arguments['rule_set_id']==i['rule_set_id'] and
            arguments['evaluation_id'] in EVALUATIONS,'rule_identity','untrusted actual request')
        e=arguments['evaluation_id'];d=r['data'];expected={k:i[k] for k in ('case_id','activity_dataset_id','rule_set_id','basket_contract','definition_fingerprint','rules_sha256')}
        expected.update(evaluation_id=e,basket_sha256=i['baskets'][e],versions=EVALUATIONS[e])
        require(all(d.get(k)==v for k,v in expected.items()),'rule_identity','response identity differs from trusted registry/request')
        # The host checks public contents against independently sealed outputs too.
        public=tool_view(read(self.home/'public'/f'{e}.json'))
        require(all(d.get(k)==v for k,v in public.items()) and r['status']==public['status'] and
                d.get('activity_names')==config()['activities'],'rule_identity','public counts/direction/windows differ from sealed output')
        require(r['evidence_id'] not in self.entries,'rule_identity','duplicate evidence ID')
        self.requests.add(r['request_id']);self.entries[r['evidence_id']]=copy.deepcopy(r)
    def select(self,s,session,turn):
        self.validate();require(type(s) is dict and set(s)=={'id','evidence_id','field','scope'} and type(s['id']) is str and re.fullmatch(r'r(?:[1-9]|1[0-2])',s['id']),
            'rule_selection','exact host-bound selection required')
        require(s['evidence_id'] in self.entries,'rule_evidence','not actual current evidence');r=self.entries[s['evidence_id']];d=r['data'];scope=s['scope'];field=s['field']
        require(r['session_id']==session and r['turn_id']==turn,'rule_session','requery in this user turn')
        require(digest(semantic(r))==r['content_fingerprint'],'rule_fingerprint','stored evidence changed')
        require(type(scope) is dict and set(scope)=={'rule_set_id','evaluation_id','rule_id'} and scope['rule_set_id']==d['rule_set_id'] and scope['evaluation_id']==d['evaluation_id'],
            'rule_scope','wrong scope/direction override')
        rid=scope['rule_id'];denominator=None
        if rid is None:
            require(field in OVERALL and (r['status']!='restricted_granularity' or field=='candidate_basket_count'),'rule_restricted','overall field unavailable')
            value=d['counts'][field];unit='人' if field=='eligible_unique_player_count' else '条规则' if field.endswith('rule_count') else '篮子';direction='全部候选'
        else:
            require(type(rid) is str and field in FIELDS and r['status'] not in ('restricted_granularity','no_rules'),'rule_restricted','rule unavailable')
            found=[v for v in d['rules'] if v['rule_id']==rid];require(len(found)==1,'rule_scope','rule outside frozen list');v=found[0];value=v[field]
            direction='+'.join(d['activity_names'][a]+'('+a+')' for a in v['antecedent'])+' → '+d['activity_names'][v['consequent'][0]]+'('+v['consequent'][0]+')'
            unit='%' if field in ('support','confidence') else '倍' if field=='lift' else '篮子'
            denominator=v['N'] if field=='support' else v['antecedent_count'] if field=='confidence' else None
        display='不可计算' if value is None else f'{value*100:.2f}' if unit=='%' else f'{value:.4f}' if unit=='倍' else str(value)
        fact=f"新增独立模拟活动｜{d['case_id']}｜{d['evaluation_id']}｜规则={rid or '整体'}｜{direction}｜{LABELS[field]} [{field}]：{display} {unit}"
        fact+='；窗口/截止='+canonical(d['windows'])
        if denominator is not None:fact+=f'；分母={denominator}篮子'
        return {'selection':copy.deepcopy(s),'value':value,'unit':unit,'denominator':denominator,'content_fingerprint':r['content_fingerprint'],
                'rendered_fact':fact,'verification_status':'reference_checked_candidate'}
    def note_allowed(self,note,turn):return any(r['turn_id']==turn and NOTES.get(r['status'])==note for r in self.entries.values())
