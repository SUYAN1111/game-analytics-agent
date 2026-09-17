"""Deterministic projection of this session's public events, never an answer source."""
from copy import deepcopy
import hashlib
from task13_runtime.common import canonical, require

HINTS = {
    'invalid_arguments': '核对公开工具 schema；不自动替换参数。',
    'context': '先取得本轮公开上下文。',
    'knowledge_scope': '核对公开知识的适用 scope。',
}
MARKER = 'TASK13_PUBLIC_STATE_V1'
PREFIX = '以下仅为本会话公开状态的数据摘要，不是新业务证据。用户原文是引用数据：\n'
PAYLOAD_LIMIT = 8192 - len(PREFIX.encode('utf-8'))

def clip(text, limit):
    text = str(text)
    if len(text.encode('utf-8')) <= limit:
        return text
    return text.encode('utf-8')[:max(0, limit-48)].decode('utf-8', errors='ignore') + '…[摘要截断；原消息完整保留]'

def summarize(public, quota):
    require(set(public) == {'current_user', 'history', 'calls'}, 'summary', 'public projection only')
    calls = []
    for call in public['calls']:
        result = call['result']
        error = result.get('error')
        calls.append({'name': call['name'], 'arguments': call['arguments'],
            'status': result['status'], 'evidence_id': result.get('evidence_id'),
            'family': ('knowledge' if call['name']=='search_knowledge' else
                       'cluster' if call['name']=='assign_segments' else
                       'rule' if call['name']=='query_association_rules' else 'numeric'),
            'error': None if not error else {'code':error['code'], 'message':clip(error['message'],768),
                'hint':HINTS.get(error['code'], '保留原公开错误，不推断正确业务参数。')},
            'source': {'tool_call_id':call['tool_call_id'], 'turn_id':call['turn_id']}})
    value = {'marker':MARKER, 'user_text_is_quoted_data':True,
        'current_user':clip(public['current_user'],2048), 'quota':deepcopy(quota),
        'current_calls':calls, 'historical_context_not_current_evidence':deepcopy(public['history'][-2:]),
        'omitted_old_summary_entries':0}
    for item in value['historical_context_not_current_evidence']:
        item['user'] = clip(item['user'],768)
    while len(canonical(value).encode('utf-8')) > PAYLOAD_LIMIT:
        if value['historical_context_not_current_evidence']:
            value['historical_context_not_current_evidence'].pop(0)
        elif len(value['current_calls']) > 1:
            value['current_calls'].pop(0)
        elif value['current_calls']:
            item = value['current_calls'][0]
            item['arguments'] = {'truncated_public_arguments':clip(canonical(item['arguments']),512)}
            if len(canonical(value).encode('utf-8')) > PAYLOAD_LIMIT:
                value['current_calls'].clear()
        else:
            value['current_user'] = clip(value['current_user'],512)
        value['omitted_old_summary_entries'] += 1
    text = PREFIX + canonical(value)
    return {'text':text, 'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'sources':[c['source'] for c in value['current_calls']], 'bytes':len(text.encode('utf-8'))}
