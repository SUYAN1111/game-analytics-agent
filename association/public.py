"""One disclosure view for tools, CSV/JSON and figures."""
import copy
from association.contract import require

def public_view(result,display_only=False):
    r=copy.deepcopy(result);c=r['counts'];N=c['eligible_basket_count']
    bins={str(i):r['basket_size'][str(i)] for i in range(4)}
    bins['4+']=sum(r['basket_size'][str(i)] for i in (4,5,6))
    partitions=[c[k] for k in ('nonempty_basket_count','empty_basket_count','coverage_incomplete_count')]+list(bins.values())
    partitions += [n for a in r['activities'] for n in (a['count'],N-a['count'])]
    partitions += [n for row in r['rules'] for n in row['cells'].values()]
    require(all(type(n) is int and n>=0 for n in partitions),'counts','negative/noninteger public cell')
    r['basket_size']=bins
    if any(0<n<20 for n in partitions):
        r['status']='restricted_granularity';r['counts']={k:v if k=='candidate_basket_count' else None for k,v in c.items()}
        r['activities']=[];r['basket_size']=None;r['rules']=[];r['display_rule_ids']=[]
        r['disclosure']='整评价分区受限：仅公开候选篮子数、身份及窗口；不公开触发格或其他细分。'
    else:r['disclosure']='固定20门槛；零格不触发，使用原开发展示名单和顺序。'
    for row in r['rules']:row.pop('exact',None)
    if display_only:
        return tool_view(r)
    return r

def tool_view(public):
    """Project a fully disclosure-checked partition to its frozen display list.

    Never rerun disclosure on just the top ten: hidden rules can suppress the
    entire partition. Export tables retain the complete allowed frozen list.
    """
    r=copy.deepcopy(public);lookup={row['rule_id']:row for row in r['rules']}
    r['rules']=[lookup[k] for k in r['display_rule_ids']]
    require(len(r['rules'])<=10,'contract','frozen display list exceeds ten')
    return r
