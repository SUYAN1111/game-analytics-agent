"""Server-owned capability catalogue and bounded, zero-provider-cost routing.

This parser is deliberately conservative. Unmatched language goes to the live
harness, or a clarification in offline mode; it never pretends to be an LLM.
"""
import copy
import re
import unicodedata
from functools import lru_cache
from agent_runtime.common import read
from product_core.paths import ASSETS
from web_api.scenarios import QUESTIONS, FRIENDLY_QUESTIONS, FAULTS, resolve_question


@lru_cache(maxsize=1)
def catalog():
    host = read(ASSETS/'runtime/host.json')['definition']
    segments = read(ASSETS/'segmentation/model.json')
    rules = read(ASSETS/'association/rules.json')
    business = read(ASSETS/'association/business.json')
    return {'metric_id':host['metric_id'], 'model_id':host['model_id'], 'case_id':host['case_id'],
            'versions':[v for v in host['snapshots']],
            'prediction_versions':sorted({v for vs in host['prediction_cohorts'].values() for v in vs}),
            'snapshots':list(segments['configuration']['snapshots']),
            'segmentation_model_id':segments['segmentation_model_id'],
            'rule_set_id':rules['rule_set_id'], 'rules':rules['rules'],
            'activities':business['activities'], 'evaluations':business['evaluations']}


def public_capabilities():
    c = catalog()
    return {'understanding':'bounded_local_rules_with_live_fallback',
            'metric_versions':c['versions'], 'prediction_versions':c['prediction_versions'],
            'segment_snapshots':c['snapshots'], 'rule_evaluations':list(c['evaluations']),
            'limits':['只分析已登记的数据与工具范围', '自选文件目前仅用于预览和字段配置',
                      '不提供天气、闲聊、任意代码或联网查询', '不推断因果，不训练新模型，不提供玩家明细'],
            'local_routes_do_not_request_model':True}


REASONS = {
    'greeting': '请直接告诉我你想了解的玩家或玩法问题。',
    'outside': '这里支持玩家行为分析，暂不提供天气、写作或其他通用问答。',
    'capability': '你想了解剧情开始情况、参与预测、玩家分组、玩法关联，还是某个指标的含义？',
    'scope': '你想查看哪次更新？请指定范围，避免把不同时间的数据混在一起。',
    'pair': '你想比较哪两种玩法？请写出名称；当前只查询已有的玩法关联规则。',
    'no_data': '当前登记的数据或工具不支持这个范围。可以修改问题，或查看支持的分析方向。',
    'upload': '这个文件目前只完成了预览或字段配置，还没有接入分析。请先使用当前示例数据。',
    'causality': '可以核对现有数据中的差异或关联，但不能据此判断玩家意愿，也不能证明原因。',
    'unsupported': '这部分要求超出了现有数据或工具的能力，下面仅展示已完成并核对过的部分。',
    'offline_language': '当前未连接语言模型，还不能可靠理解这句话。请补充要分析的对象和范围，也可以参考分析方向；你的原问题会保留。',
}


def control(kind, reason, *, choices=None, pending=None):
    return {'kind':kind, 'reason':reason, 'message':REASONS[reason], 'choices':choices or [],
            'pending':pending, 'model_requested':False}


def execute(plan, *, limitations=None):
    return {'kind':'execute', 'plan':plan, 'limitations':limitations or [],
            'message':describe(plan), 'model_requested':False}


def describe(p):
    if p['kind']=='fault':return '执行测试场景'
    labels={'V1':'第一次更新','V2':'第二次更新','V3':'第三次更新','V4':'第四次更新','V5':'前一次更新','V6':'后一次更新'}
    if p['kind']=='example': return '当前示例范围：'+FRIENDLY_QUESTIONS[QUESTIONS.index(p['question'])]
    if p['kind'] in ('metric','prediction'):
        return ('剧情开始情况：' if p['kind']=='metric' else '剧情参与预测：')+'、'.join(labels[v] for v in p['versions'])+'；获得资格后 72 小时；整体样本'
    if p['kind']=='cluster':
        return '玩家分组：'+{'fit_V3main':'第三次更新的记录','replay_V5main':'前一次更新的记录','replay_V6main':'后一次更新的记录'}[p['snapshot']]+('；第 '+p['group'][1:].lstrip('0')+' 组' if p.get('group') else '；全部三组')
    if p['kind']=='rules': return '玩法关联：'+' → '.join(catalog()['activities'][a] for a in p['pair'])+'；'+{'discovery_V1_V3':'前三次更新','validation_V4':'第四次更新','validation_V5':'前一次更新','validation_V6':'后一次更新'}[p['evaluation']]
    return '查阅已登记的业务资料：'+p['query']


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text).lower())


def scope_choices(p):
    if p['kind']=='prediction': values=[('查看前一次更新',['V5']),('查看后一次更新',['V6'])]
    else: values=[('查看前一次更新',['V5']),('查看后一次更新',['V6']),('对比前一次和后一次更新',['V5','V6'])]
    return [{'text':t,'plan':{**p,'versions':vs}} for t,vs in values]


def route(text, mode, previous=None):
    """Pure routing; previous is the last owned, persisted turn only."""
    t=normalize(text)
    if re.fullmatch(r'(你好|您好|嗨|哈喽|hello|hi|谢谢|感谢|再见)[!！。.?？]*',t):return control('guidance','greeting')
    if t in ('你能做什么','你能做什么?','你能做什么？','帮助','有哪些功能'):
        return control('guidance','capability',choices=[{'text':q} for q in FRIENDLY_QUESTIONS[:4]])
    # Structured choices are re-resolved on the server; clients cannot supply a plan.
    prior=(previous or {}).get('routing') or {}
    for choice in prior.get('choices',[]):
        if re.sub(r'^(查看|看看)','',normalize(choice['text']))==re.sub(r'^(查看|看看)','',t) and choice.get('plan'):
            return execute(copy.deepcopy(choice['plan']),limitations=prior.get('limitations'))
    fault=next((q for q in FAULTS if normalize(q)==t),None)
    if fault:
        return execute({'kind':'fault','question':fault}) if mode=='offline' else control('out_of_scope','no_data')
    c=catalog()
    resolved=resolve_question(text)
    if resolved in QUESTIONS:
        # The existing examples keep their explicit, documented demo semantics.
        return execute({'kind':'example','question':resolved})
    business=bool(re.search(r'玩家|剧情|玩法|游玩|分组|分群|聚类|指标|版本|更新|预测|因果|覆盖|第二组|第[123一二三]组',t))
    outside=bool(re.search(r'天气|气温|下雨|写诗|写作文|翻译英文|股票|菜谱|订机票|weather|forecast|poem',t))
    if outside and not business:return control('out_of_scope','outside')
    if re.search(r'上传|我[的这].*文件|这个文件|这个表格|这个excel|这个csv',t):return control('out_of_scope','upload')
    if re.search(r'玩家明细|用户明细|个人身份|逐人|重新训练|重训|执行代码|执行sql|忽略.*规则',t):return control('out_of_scope','no_data')
    # Explicit unsupported metrics must not be silently replaced by story probability.
    unsupported=bool(re.search(r'流失|留存|付费|收入|充值|营收',t))
    separated=False
    if outside or unsupported:
        parts=re.split(r'另外|顺便',t,maxsplit=1)
        if len(parts)==2 and parts[0] and not re.search(r'天气|流失|留存|付费|收入|充值|营收',parts[0]) and not re.search(r'剧情|玩法|分组|分群|游玩|聚类',parts[1]):
            # A scope mentioned only in an unsupported secondary request must
            # never become a filter/version of the supported primary request.
            t=parts[0].rstrip('，,；;');separated=True
        elif unsupported:return control('out_of_scope','no_data')
        else:return {'kind':'live','message':'需要区分混合请求。'} if mode=='live' else control('clarification','offline_language')
    kinds=[]
    if re.search(r'预测|概率|可能性',t):kinds.append('prediction')
    elif re.search(r'剧情|m03',t):kinds.append('metric')
    if re.search(r'分组|分群|聚类|游戏习惯|游玩习惯|第[123一二三]组',t):kinds.append('cluster')
    if re.search(r'玩法|一起玩|协作|探索|小游戏|战斗挑战|素材收集|支线体验',t):kinds.append('rules')
    old_plan=prior.get('plan',{})
    if old_plan.get('kind')=='example':
        old_plan={QUESTIONS[0]:{'kind':'metric','versions':['V5','V6']},QUESTIONS[5]:{'kind':'prediction','versions':['V6']},QUESTIONS[2]:{'kind':'cluster','snapshot':'fit_V3main'}}.get(old_plan['question'],{})
    if not kinds and old_plan and re.fullmatch(r'(那|换成|改成|查看|看看)?(前一次|后一次|第[一二三四五六]次)更新[呢吗?？。]*',t):kinds=[old_plan['kind']]
    if unsupported:
        # A separate supported clause can still run, with a visible limitation.
        if not separated or not kinds:return control('out_of_scope','no_data')
    if len(set(kinds))>1:
        return control('clarification','capability',choices=[{'text':q} for q in FRIENDLY_QUESTIONS[:4]])
    limitations=[]
    if outside:limitations.append(REASONS['outside'])
    if unsupported:limitations.append(REASONS['no_data'])
    query=t if separated else text
    if not kinds:
        if re.search(r'因果|指标.*含义|覆盖.*含义',t):return execute({'kind':'knowledge','query':query[:256]},limitations=limitations)
        return {'kind':'live','message':'按当前数据和工具判断可回答范围。'} if mode=='live' else control('clarification','offline_language')
    kind=kinds[0]
    if re.search(r'怎么算|如何计算|什么意思|是什么|怎么看|输入.*哪些|使用.*信息|算法|定义|口径',t) and not re.search(r'对比|比较',t):
        return execute({'kind':'knowledge','query':query[:256]},limitations=limitations)
    if re.search(r'为什么|原因|导致|意愿|不愿意|因果',t):limitations.append(REASONS['causality'])
    # These constraints require a richer planner; never drop them in the local path.
    if re.search(r'不要|不是|除了|排除|只看|按地区|按语言|按设备|新玩家|老玩家|男性|女性|最近|今天|昨天|上周|本周|近[0-9一二三四五六七八九十]+天|\d+岁|\d+级',t):
        return {'kind':'live','message':'需要结合完整约束判断。'} if mode=='live' else control('clarification','offline_language')
    # Only execute a fully covered local grammar. Topic keywords alone are not
    # sufficient: unknown qualifiers (payments, geography, custom filters, etc.)
    # must go to a model/clarification instead of changing the user's question.
    residual=t
    vocabulary=['你好','您好','请','帮我','我想','想知道','了解','看一下','看看','查看','查询','统计','分析','展示',
        '对比','比较','差异','变化','情况','有多少','多少','比例','人数','玩家','用户','剧情','开始','未开始','没开始',
        '没有开始','仍然','仍','还','获得资格','资格','参与','更新后','更新','版本','第一次','第二次','第三次','第四次','第五次','第六次',
        '前一次','后一次','这次','那次','两次','两个','预测','概率','可能性','游戏习惯','游玩习惯','游戏','游玩',
        '分组','分群','聚类','不同','区别','每组','各组','全部','所有','通常','每次','次数','时长','分钟',
        '玩法','一起玩','一起','体验','也会玩','会玩','玩','同时','哪些','什么','怎么','怎么样','是否','是不是',
        '第1组','第2组','第3组','第一组','第二组','第三组','第一','第二','第三','组','换成','改成','那',
        '为什么','原因','导致','意愿','不愿意','因果','更','减少','增加','不','有没有','能否','能不能',
        '天气','气温','下雨','帮我看看','顺便','另外','以及','并且','流失','留存','付费','收入','充值','营收',
        '小时','天','三天','72','3','m03','和','与','的','了','吗','呢','后','在','中','一下','是多少','是不是','是','有','会这样','请问','数据']+list(c['activities'].values())
    residual=re.sub(r'v\d+','',residual)
    for word in sorted(vocabulary,key=len,reverse=True):residual=residual.replace(word,'')
    residual=re.sub(r'[，,。.!！?？:：;；、\-→]','',residual)
    if residual:
        return {'kind':'live','message':'需要理解问题中的额外条件。'} if mode=='live' else control('clarification','offline_language')
    versions=re.findall(r'(?<![a-z])v(\d+)',t)
    versions=['V'+v for v in versions]
    for word,v in [('第一次更新','V1'),('第二次更新','V2'),('第三次更新','V3'),('第四次更新','V4'),('第五次更新','V5'),('第六次更新','V6'),('前一次','V5'),('后一次','V6')]:
        if word in t:versions.append(v)
    versions=list(dict.fromkeys(versions))
    if any(v not in c['versions'] for v in versions):return control('out_of_scope','no_data')
    if kind in ('metric','prediction'):
        if not versions:
            p={'kind':kind}
            r=control('clarification','scope',choices=scope_choices(p),pending=p);r['limitations']=limitations;return r
        if len(versions)>2 or kind=='prediction' and any(v not in c['prediction_versions'] for v in versions):return control('out_of_scope','no_data')
        if re.search(r'对比|比较|差异|变化',t) and len(versions)<2:
            r=control('clarification','scope',choices=scope_choices({'kind':kind}));r['limitations']=limitations;return r
        hours=re.findall(r'(\d+)小时',t);days=re.findall(r'(\d+)天',t)
        if any(x!='72' for x in hours) or any(x!='3' for x in days):return control('out_of_scope','no_data')
        p={'kind':kind,'versions':sorted(versions,key=lambda v:int(v[1:]))}
    elif kind=='cluster':
        snapshots={'V3':'fit_V3main','V5':'replay_V5main','V6':'replay_V6main'}
        if len(versions)>1 or versions and versions[0] not in snapshots:return control('out_of_scope','no_data')
        group=re.search(r'第([123一二三])组',t)
        p={'kind':kind,'snapshot':snapshots[versions[0]] if versions else old_plan.get('snapshot','fit_V3main')}
        if group:p['group']='G0'+str({'一':1,'二':2,'三':3}.get(group[1],group[1]))
    else:
        items=[(t.find(name),key) for key,name in c['activities'].items() if name in t]
        pair=[key for _,key in sorted(items)]
        if len(pair)!=2:return control('clarification','pair',choices=[{'text':'玩休闲小游戏的玩家，也会玩协作玩法吗？'},{'text':'玩地图探索的玩家，也会玩支线体验吗？'}])
        if not any(r['antecedent']==pair[:1] and r['consequent']==pair[1:] for r in c['rules']):return control('out_of_scope','no_data')
        if len(versions)>1:return control('clarification','scope')
        evaluation='validation_'+versions[0] if versions else 'discovery_V1_V3'
        if evaluation not in c['evaluations']:return control('out_of_scope','no_data')
        p={'kind':'rules','pair':pair,'evaluation':evaluation}
    return execute(p,limitations=limitations)


def model_control(value):
    """No model-authored factual prose is admitted through the control protocol."""
    if type(value) is not dict or set(value)!={'response_type','reason'}:raise ValueError('invalid control response')
    kind,reason=value['response_type'],value['reason']
    allowed={'clarification':('capability','scope','pair'), 'out_of_scope':('outside','no_data','upload')}
    if kind not in allowed or reason not in allowed[kind]:raise ValueError('invalid control reason')
    return control(kind,reason)
