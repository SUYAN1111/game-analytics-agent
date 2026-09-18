"""Literal authority for numeric filters; model guesses never grant scope."""
import re
import unicodedata
from agent_runtime.common import require

DIMENSIONS = {'region_id': r'地区|区域|城市|地域|region', 'language': r'语言|language',
              'client': r'设备|客户端|平台|client', 'new_player': r'新玩家|老玩家|新老|new_player'}

def contract(text, previous=None):
    t=unicodedata.normalize('NFKC',text).lower()
    values={'region_id':re.findall(r'(?<![a-z0-9])r[123](?![a-z0-9])',t),
            'language':re.findall(r'(?<![a-z0-9])l[123](?![a-z0-9])',t),
            'client':re.findall(r'(?<![a-z])(?:pc|mobile)(?![a-z])',t),
            'new_player':[]}
    if '电脑端' in t:values['client'].append('pc')
    if '手机端' in t or '移动端' in t:values['client'].append('mobile')
    if '新玩家' in t:values['new_player'].append('1')
    if '老玩家' in t:values['new_player'].append('0')
    dimensions=[k for k,p in DIMENSIONS.items() if re.search(p,t) or values[k]]
    all_groups=[k for k,p in DIMENSIONS.items() if re.search(r'(?:按|各|每个|不同)(?:'+p+r')',t)]
    unresolved=[k for k in dimensions if not values[k] and k not in all_groups]
    versions=re.findall(r'(?<![a-z0-9])v(\d+)(?!\d)',t)
    for i,word in enumerate('一二三四五六',1):
        if f'第{word}次' in t or f'第{i}次更新' in t:versions.append(str(i))
    for word,v in [('前一次','5'),('后一次','6')]:
        if word in t:versions.append(v)
    inherited=previous or {}
    follow=bool(re.search(r'沿用|刚才|那|继续|同一',t))
    if follow:
        for k in list(unresolved):
            if re.search(r'(?:刚才|原来|同一|相同)(?:的)?(?:'+DIMENSIONS[k]+r')',t) and inherited.get('values',{}).get(k):
                values[k]=inherited['values'][k];unresolved.remove(k)
    if follow and not dimensions:
        values=inherited.get('values',values);dimensions=inherited.get('dimensions',[]);all_groups=inherited.get('all_groups',[])
    if follow and not versions:versions=inherited.get('versions',[])
    # Negated filters need a richer set-expression contract; never treat their
    # literal IDs as positive authorization.
    if dimensions and re.search(r'排除|除了|不要.*(?:r[123]|地区|区域)|不看|非r[123]',t):unresolved.extend(dimensions)
    segments=re.findall(r'(?<![a-z0-9])g0([123])(?!\d)',t)
    for i,w in enumerate('一二三',1):
        if f'第{w}组' in t or f'第{i}组' in t:segments.append(str(i))
    if follow and not segments:segments=inherited.get('segments',[])
    return {'values':values,'dimensions':dimensions,'all_groups':all_groups,'unresolved':unresolved,'versions':list(dict.fromkeys(versions)),'segments':segments}

def validate_selections(answer, bound):
    if answer.get('status')=='control_checked':return
    selections=answer['selections']
    if any(selections[k] for k in ('claims','cluster_selections','rule_selections')):
        require(not bound['unresolved'],'scope_authority','Unresolved user filter; ask for a registered value, never substitute.')
    for selection in selections['claims']:
        s=selection['scope'];dimension=s.get('group_by','none');value=s.get('group_value')
        versions=[str(s[k]).removeprefix('V') for k in ('version_id','left_version','right_version') if k in s]
        require(not bound['versions'] or all(v in bound['versions'] for v in versions),'scope_authority','Answer version differs from explicit user scope.')
        if dimension!='none':
            require(dimension in bound['dimensions'],'scope_authority','Grouping not requested by user.')
            require(dimension in bound['all_groups'] or str(value).lower() in bound['values'].get(dimension,[]),
                    'scope_authority','Selected group has no literal or registered alias authority in user request.')
        elif bound['dimensions']:
            require(all(k in bound['all_groups'] for k in bound['dimensions']),'scope_authority','Overall result cannot replace a requested filter.')
    for selection in selections['cluster_selections']:
        s=selection['scope'];v=re.search(r'_V(\d+)',s['snapshot_id'])
        require(not bound['versions'] or v and v[1] in bound['versions'],'scope_authority','Cluster snapshot differs from requested version.')
        require(not bound['segments'] or s.get('segment_id') in ['G0'+g for g in bound['segments']], 'scope_authority','Cluster differs from requested group.')
    for selection in selections['rule_selections']:
        v=re.fullmatch(r'validation_V(\d+)',selection['scope']['evaluation_id'])
        require(not bound['versions'] or v and v[1] in bound['versions'],'scope_authority','Displayed rules differ from requested evaluation period.')

def validate_context(calls, turn_id):
    attempts=0
    for call in calls:
        require(call['turn_id']==turn_id,'context','Context must belong to current turn.')
        require(call['name']=='inspect_context','context','Business tool ran before successful current context.')
        attempts+=1
        require(attempts<=2,'context','At most one context parameter correction is permitted.')
        r=call['result']
        if r.get('error') is None and r.get('status')=='ok' and r.get('evidence_id'):return
    require(False,'context','Missing successful current context.')
