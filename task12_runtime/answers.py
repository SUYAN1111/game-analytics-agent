"""Four disjoint evidence families; host owns labels, scopes, units and prose."""
import re
from task10_runtime.answers import parse_json,quote as original_quote,require_completed,completion_summary as original_completion_summary,literal,NOTES as OLD_NOTES
from agent_runtime.claims import render_fact
from agent_runtime.common import require,HostError,canonical
NOTES={**OLD_NOTES,'rules_none':'当前冻结开发规则没有满足全部门槛的规则；未调整参数。','rules_no_eligible':'当前活动评价分区没有有效篮子，指标不可计算。','rules_restricted':'当前活动评价分区整体细分受限，仅允许候选篮子数、身份和窗口。','segmentation_unavailable':'本轮冻结分群不可用，不能提供群画像。',
       'segmentation_restricted':'本快照触发最小群人数限制，群与状态明细整体不公开。'}

def completion_summary(result):
    summary=original_completion_summary(result)
    text=result.get('final_response')
    summary['complete_reference_blocks']=len(re.findall(r'\{\{(?:claim|knowledge|cluster|rule|note):[^{}\n]+\}\}',text)) if isinstance(text,str) else None
    return summary

def quote(checked):
    value=original_quote(checked)
    scope=checked['chunk']['scope']
    heading='资料适用范围：'+scope['metric_id']+'；版本：'+scope['knowledge_revision']
    value['rendered_quote']='> '+literal(heading)+'\n'+value['rendered_quote']
    value['knowledge_scope']=scope.copy()
    return value

def require_evidence_families(value,numeric,knowledge,clusters,rules):
    """Classify only actual registered evidence IDs, never words in free prose."""
    registries={'claims':numeric.entries,'knowledge_selections':knowledge.entries,'cluster_selections':clusters.entries,'rule_selections':rules.entries}
    for field in registries:
        for selection in value[field]:
            identifier=selection['evidence_id']
            require(type(identifier) is str,'answer_evidence_family','evidence_id must be a string')
            other=[name for name,entries in registries.items() if name!=field and identifier in entries]
            require(not other,'answer_evidence_family',
                    field+'引用了属于'+','.join(other)+'的真实证据；必须使用正确数组和引用块，不自动转换。')

def answer_envelope(text):
    require(type(text) is str and len(text)<=20000,'answer_limits','strict JSON <=20000 characters required')
    v=parse_json(text)
    require(type(v) is dict and set(v)=={'answer_markdown','claims','knowledge_selections','cluster_selections','rule_selections'},'answer','exactly five answer fields required')
    require(type(v['answer_markdown']) is str and len(v['answer_markdown'])<=1024 and
            all(type(v[k]) is list for k in ('claims','knowledge_selections','cluster_selections','rule_selections')),'answer','invalid body/selection types')
    require(len(v['claims'])+len(v['cluster_selections'])+len(v['rule_selections'])<=12 and len(v['knowledge_selections'])<=8,'answer_limits','combined numeric cap 12, knowledge cap 8')
    ids=set()
    for key,prefix,fields,limit in [('claims','c',{'id','evidence_id','field','scope'},12),
        ('cluster_selections','s',{'id','evidence_id','field','scope'},12),('rule_selections','r',{'id','evidence_id','field','scope'},12),('knowledge_selections','k',{'id','evidence_id','chunk_id'},8)]:
        for s in v[key]:
            require(type(s) is dict and set(s)==fields and type(s['id']) is str and re.fullmatch(prefix+r'[1-9]\d?',s['id'])
                    and int(s['id'][1:])<=limit and s['id'] not in ids,'answer','invalid or duplicate selection')
            ids.add(s['id'])
    blocks=[s.strip() for s in v['answer_markdown'].splitlines() if s.strip()];used=[];notes=[]
    require(0<len(blocks)<=25,'answer_limits','1–25 reference blocks required')
    for block in blocks:
        m=re.fullmatch(r'\{\{(claim|knowledge|cluster|rule):([cksr][1-9]\d?)\}\}',block)
        n=re.fullmatch(r'\{\{note:([a-z_]+)\}\}',block)
        if m:
            require(m[2][0]=={'claim':'c','knowledge':'k','cluster':'s','rule':'r'}[m[1]] and m[2] in ids,'answer_body','wrong namespace/reference');used.append(m[2])
        elif n and n[1] in NOTES:notes.append(n[1])
        else:raise HostError('answer_body','whole reference blocks only; no independent prose')
    require(len(used)==len(ids) and set(used)==ids and len(notes)==len(set(notes)) and len(notes)<=5,'answer','missing/duplicate blocks')
    return v

def verify_answer(text,numeric,knowledge,clusters,rules,turn_id):
    v=answer_envelope(text)
    require_evidence_families(v,numeric,knowledge,clusters,rules)
    facts=[render_fact(numeric.resolve_selection(s),numeric.definition['metric_id']) for s in v['claims']]
    quotes=[quote(knowledge.select(s,numeric.session_id,turn_id)) for s in v['knowledge_selections']]
    groups=[clusters.select(s,numeric.session_id,turn_id) for s in v['cluster_selections']]
    rule_facts=[rules.select(s,numeric.session_id,turn_id) for s in v['rule_selections']]
    rkeys=[(r['content_fingerprint'],r['selection']['field'],canonical(r['selection']['scope'])) for r in rule_facts]
    require(len(rkeys)==len(set(rkeys)),'answer','same rule fact repeated')
    keys=[(r['claim']['content_fingerprint'],r['claim']['pointer']) for r in facts]
    ckeys=[(r['content_fingerprint'],r['selection']['field'],canonical(r['selection']['scope'])) for r in groups]
    require(len(keys)==len(set(keys)) and len(ckeys)==len(set(ckeys)) and len({q['chunk']['chunk_id'] for q in quotes})==len(quotes),
            'answer','same fact or knowledge chunk repeated')
    mapping={r['claim']['id']:r['rendered_fact'] for r in facts}
    mapping.update({r['selection']['id']:r['rendered_quote'] for r in quotes})
    mapping.update({r['selection']['id']:r['rendered_fact'] for r in groups});mapping.update({r['selection']['id']:r['rendered_fact'] for r in rule_facts});rendered=[]
    for block in [s.strip() for s in v['answer_markdown'].splitlines() if s.strip()]:
        kind,key=block[2:-2].split(':')
        if kind!='note':rendered.append(mapping[key]);continue
        if key.startswith('knowledge_'):require(knowledge.note_allowed(key,turn_id),'knowledge_note','unsupported knowledge note')
        if key.startswith('segmentation_'):require(clusters.note_allowed(key,turn_id),'cluster_note','unsupported segmentation note')
        if key.startswith('rules_'):require(rules.note_allowed(key,turn_id),'rule_note','unsupported activity note')
        rendered.append(NOTES[key])
    if NOTES['limitations'] not in rendered:rendered.append(NOTES['limitations'])
    return {'answer_markdown':'\n\n'.join(rendered),'claims':facts,'knowledge_selections':quotes,'cluster_selections':groups,'rule_selections':rule_facts,
            'status':'reference_checked_candidate','presentation_contract':'host_bound_four_evidence_v1'}
