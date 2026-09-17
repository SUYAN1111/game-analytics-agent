"""Fixed offline model scripts, executed through the real DSH/MCP chain."""
import re
import unicodedata
from product_core.paths import ROOT, ASSETS
from agent_runtime.common import read

QUESTIONS = ['对比 V5 与 V6 的 M03', '冻结预测是什么意思？', '现有玩家分群有什么特点？',
             '活动关联规则能支持因果结论吗？', '这些结果能说明因果关系吗？', '查询 V6 冻结预测的公开汇总', 'M03 的分子分母和适用范围是什么？']
FRIENDLY_QUESTIONS = ['比较两个版本的剧情开始情况', '这些预测结果该怎么看？', '不同玩家的游戏习惯有什么区别？',
                      '玩休闲小游戏的玩家，也会玩协作玩法吗？', '这些结果能说明因果关系吗？', '查看示例数据中的剧情参与预测', '剧情开始情况是怎么算出来的？']
ALIASES = dict(zip(FRIENDLY_QUESTIONS, QUESTIONS))
ALIASES['查看 V6 的剧情参与预测'] = QUESTIONS[5]
ALIASES['哪些活动经常一起参加？'] = QUESTIONS[3]
ALIASES['哪些玩法经常被同一批玩家体验？'] = QUESTIONS[3]
FAULTS = ['测试：慢响应与取消', '测试：超时', '测试：错误模型回复']


def resolve_question(text):
    # Equivalent punctuation/spacing only, never guess an intent or substitute a different scope.
    def key(value):
        return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).rstrip('?.。')
    known = {key(q): q for q in QUESTIONS}
    known.update({key(alias): target for alias, target in ALIASES.items()})
    return known.get(key(text), text)


def script(text, plan=None):
    if plan and plan['kind'] not in ('example','fault'):
        return planned_script(plan)
    if plan: text=plan['question']
    text = resolve_question(text)
    if text not in QUESTIONS + FAULTS:
        raise ValueError('offline_unsupported')
    definition = read(ASSETS / 'runtime/host.json')['definition']
    base = read(ROOT / 'product_core/fixtures/sealed_examples.json')
    seg = read(ASSETS / 'segmentation/model.json')['segmentation_model_id']
    rules = read(ASSETS / 'association/rules.json')
    rule = rules['rule_set_id']
    def call(name, arguments): return {'name': name, 'arguments': arguments}
    actions = [{'calls': [call('inspect_context', {'case_id': definition['case_id']})]}]
    answer = {'answer_markdown': '{{note:causality}}', 'claims': [], 'knowledge_selections': [],
              'cluster_selections': [], 'rule_selections': []}
    blocks = []
    if text == QUESTIONS[0]:
        query = base['query_metric']['arguments']
        actions.append({'calls': [call('query_metric', {**query, 'cohort_id': 'cohort_'+v}) for v in ('V5', 'V6')]})
        actions.append({'calls': [call('compare_results', {'left_evidence_id': '$evidence:query_metric:cohort_V5',
                                                        'right_evidence_id': '$evidence:query_metric:cohort_V6'})]})
        for i, version in enumerate(('V5', 'V6'), 1):
            for field in ('numerator', 'denominator', 'rate'):
                identifier = 'c' + str(len(answer['claims'])+1)
                answer['claims'].append({'id': identifier, 'evidence_id': '$evidence:query_metric:cohort_'+version,
                    'field': field, 'scope': {'version_id': version, 'group_by': 'none', 'group_value': None, 'window_hours': 72}})
                blocks.append('{{claim:'+identifier+'}}')
        answer['claims'].append({'id':'c7', 'evidence_id':'$evidence:compare_results', 'field':'percentage_point_difference',
            'scope':{'left_version':'V5','right_version':'V6','group_by':'none','group_value':None,'window_hours':72}})
        blocks.append('{{claim:c7}}')
    elif text == QUESTIONS[5]:
        actions.append({'calls':[call('predict_registered',base['predict_registered']['arguments'])]})
        for i, field in enumerate(('expected_qualified_count','predicted_count','missing_count','mean_p','prediction_coverage'),1):
            answer['claims'].append({'id':'c'+str(i),'evidence_id':'$evidence:predict_registered','field':field,
                'scope':{'version_id':'V6','model_id':definition['model_id'],'time_mode':'frozen_t0_replay'}})
            blocks.append('{{claim:c'+str(i)+'}}')
    elif text in (QUESTIONS[1], QUESTIONS[6]):
        from task12_knowledge.corpus import Corpus
        query = 'M03 冻结预测 t0 特征 重放' if text == QUESTIONS[1] else 'M03 分子 分母 72小时'
        hits = Corpus().search({'query': query})['hits']
        actions.append({'calls': [call('search_knowledge', {'query': query}),
                                 call('read_model_card', {'case_id': definition['case_id'], 'model_id': definition['model_id']})]})
        for i, hit in enumerate(hits[:2], 1):
            answer['knowledge_selections'].append({'id': 'k'+str(i), 'evidence_id': '$evidence:search_knowledge', 'chunk_id': hit['chunk_id']})
            blocks.append('{{knowledge:k'+str(i)+'}}')
    elif text == QUESTIONS[2]:
        actions.append({'calls': [call('assign_segments', {'segmentation_model_id': seg, 'snapshot_id': 'fit_V3main'})]})
        public = read(ASSETS / 'segmentation/results/fit_V3main.json')
        fields = [(None, 'assigned_count')] + [(g['segment_id'], field) for g in public['groups']
                   for field in ('player_count','completed_sessions_14d.mean','median_session_minutes_14d.mean')]
        for i, (group, field) in enumerate(fields, 1):
            answer['cluster_selections'].append({'id': 's'+str(i), 'evidence_id': '$evidence:assign_segments', 'field': field,
                'scope': {'segmentation_model_id': seg, 'snapshot_id': 'fit_V3main', 'segment_id': group}})
            blocks.append('{{cluster:s'+str(i)+'}}')
    elif text == QUESTIONS[3]:
        actions.append({'calls': [call('query_association_rules', {'rule_set_id': rule, 'evaluation_id': 'discovery_V1_V3'})]})
        rid = read(ASSETS / 'association/public/discovery_V1_V3.json')['rules'][0]['rule_id']
        for i, field in enumerate(('support', 'confidence', 'lift'), 1):
            answer['rule_selections'].append({'id': 'r'+str(i), 'evidence_id': '$evidence:query_association_rules', 'field': field,
                'scope': {'rule_set_id': rule, 'evaluation_id': 'discovery_V1_V3', 'rule_id': rid}})
            blocks.append('{{rule:r'+str(i)+'}}')
    elif text in FAULTS[:2]:
        actions[0]['delay'] = 30
    elif text == FAULTS[2]:
        actions.append({'raw_answer': '{"answer_markdown":"未经核验的任意结论"}'})
        return actions
    answer['answer_markdown'] = '\n'.join(blocks + ['{{note:causality}}'])
    actions.append({'answer': answer, 'resolve_answer_refs': True})
    return actions


def planned_script(plan):
    """Compile explicit local intent/slots to real calls, never to canned numbers."""
    from web_api.capabilities import catalog
    c=catalog();base=read(ROOT/'product_core/fixtures/sealed_examples.json')
    actions=[{'calls':[{'name':'inspect_context','arguments':{'case_id':c['case_id']}}]}]
    answer={'claims':[],'knowledge_selections':[],'cluster_selections':[],'rule_selections':[],'answer_markdown':''}
    blocks=[]
    def call(name,arguments):return {'name':name,'arguments':arguments}
    def select(family,prefix,eid,field,scope):
        identifier=prefix+str(len(answer[family])+1)
        answer[family].append({'id':identifier,'evidence_id':'$evidence:'+eid,'field':field,'scope':scope})
        blocks.append('{{'+{'c':'claim','s':'cluster','r':'rule'}[prefix]+':'+identifier+'}}')
    kind=plan['kind']
    if kind=='metric':
        calls=[]
        for v in plan['versions']:
            cohort='cohort_'+v
            calls.extend([call('check_quality',{**base['check_quality']['arguments'],'cohort_id':cohort}),
                          call('query_metric',{**base['query_metric']['arguments'],'cohort_id':cohort})])
            for field in ('numerator','denominator','rate'):
                select('claims','c','query_metric:'+cohort,field,{'version_id':v,'group_by':'none','group_value':None,'window_hours':72})
        actions.append({'calls':calls})
        if len(plan['versions'])==2:
            a,b=plan['versions']
            actions.append({'calls':[call('compare_results',{'left_evidence_id':'$evidence:query_metric:cohort_'+a,'right_evidence_id':'$evidence:query_metric:cohort_'+b})]})
            select('claims','c','compare_results','percentage_point_difference',{'left_version':a,'right_version':b,'group_by':'none','group_value':None,'window_hours':72})
    elif kind=='prediction':
        actions.append({'calls':[call('predict_registered',{**base['predict_registered']['arguments'],'cohort_id':'cohort_'+v}) for v in plan['versions']]})
        for v in plan['versions']:
            for field in ('expected_qualified_count','predicted_count','missing_count','mean_p','prediction_coverage'):
                select('claims','c','predict_registered:cohort_'+v,field,{'version_id':v,'model_id':c['model_id'],'time_mode':'frozen_t0_replay'})
    elif kind=='cluster':
        snapshot=plan['snapshot'];actions.append({'calls':[call('assign_segments',{'segmentation_model_id':c['segmentation_model_id'],'snapshot_id':snapshot})]})
        public=read(ASSETS/'segmentation/results'/f'{snapshot}.json')
        for g in public['groups']:
            if plan.get('group') and plan['group']!=g['segment_id']:continue
            for field in ('player_count','completed_sessions_14d.mean','median_session_minutes_14d.mean'):
                select('cluster_selections','s','assign_segments',field,{'segmentation_model_id':c['segmentation_model_id'],'snapshot_id':snapshot,'segment_id':g['segment_id']})
    elif kind=='rules':
        rule=next(r for r in c['rules'] if r['antecedent']==plan['pair'][:1] and r['consequent']==plan['pair'][1:])
        actions.append({'calls':[call('query_association_rules',{'rule_set_id':c['rule_set_id'],'evaluation_id':plan['evaluation']})]})
        for field in ('support','confidence','lift'):
            select('rule_selections','r','query_association_rules',field,{'rule_set_id':c['rule_set_id'],'evaluation_id':plan['evaluation'],'rule_id':rule['rule_id']})
    elif kind=='knowledge':
        from task12_knowledge.corpus import Corpus
        query=plan['query'];hits=Corpus().search({'query':query})['hits']
        if not hits:raise ValueError('knowledge_unavailable')
        actions.append({'calls':[call('search_knowledge',{'query':query})]})
        for i,hit in enumerate(hits[:3],1):
            answer['knowledge_selections'].append({'id':'k'+str(i),'evidence_id':'$evidence:search_knowledge','chunk_id':hit['chunk_id']})
            blocks.append('{{knowledge:k'+str(i)+'}}')
    else:raise ValueError('invalid offline plan')
    answer['answer_markdown']='\n'.join(blocks+['{{note:causality}}'])
    actions.append({'answer':answer,'resolve_answer_refs':True})
    return actions
