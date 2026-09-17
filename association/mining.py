"""Level-wise Apriori, exact thresholds/order and frozen-list evaluation."""
from fractions import Fraction
from itertools import combinations
from collections import Counter
from association.contract import *

def transactions(baskets):
    seen=set();out=[]
    for r in baskets:
        key=r['basket_id'];require(key not in seen,'basket','duplicate basket identity');seen.add(key)
        if r['state']=='coverage_incomplete':require(r['items'] is None,'basket','incomplete must be null');continue
        require(r['state'] in ('eligible_empty','eligible_nonempty') and type(r['items']) is list and
                r['items']==sorted(set(r['items'])) and set(r['items'])<=set(ITEMS),'basket','invalid activity items')
        require(bool(r['items'])==(r['state']=='eligible_nonempty'),'basket','state/items mismatch')
        out.append(frozenset(r['items']))
    return out

def rule_id(A,B):return stable('rule_',config()['contract'],list(A),list(B))

def validate_rule(rule):
    A,B=rule['antecedent'],rule['consequent']
    require(type(A) is list and type(B) is list and len(A) in (1,2) and len(B)==1 and A==sorted(set(A)) and
            B==sorted(set(B)) and not set(A)&set(B) and set(A+B)<=set(ITEMS),'rule','invalid rule direction/items')
    require(rule['rule_id']==rule_id(A,B),'rule','rule ID does not match direction/contract')

def ratios(N,nA,nB,nAB):
    require(all(type(x) is int and x>=0 for x in (N,nA,nB,nAB)) and nAB<=min(nA,nB) and
            max(nA,nB)<=N and N-nA-nB+nAB>=0,'counts','invalid contingency counts')
    return {'support':Fraction(nAB,N) if N else None,'confidence':Fraction(nAB,nA) if nA else None,
            'lift':Fraction(nAB*N,nA*nB) if N and nA and nB else None}

def metric_row(rule,N,nA,nB,nAB):
    validate_rule(rule);exact=ratios(N,nA,nB,nAB);thresholds=config()['thresholds'];reasons=[]
    for k in ('support','confidence','lift'):
        if exact[k] is None:reasons.append(k+':zero denominator')
        elif exact[k]<Fraction(thresholds[k]):reasons.append(k+':below fixed threshold')
    if nAB<thresholds['joint_count']:reasons.append('joint_count:below 50')
    return {**rule,'N':N,'antecedent_count':nA,'consequent_count':nB,'joint_count':nAB,
        **{k:None if v is None else float(v) for k,v in exact.items()},
        'exact':{k:None if v is None else str(v) for k,v in exact.items()},
        'cells':{'n11':nAB,'n10':nA-nAB,'n01':nB-nAB,'n00':N-nA-nB+nAB},
        'meets_discovery_thresholds':not reasons,'reasons':reasons,
        'null_reasons':{k:'N=0' if N==0 else 'nA=0' if nA==0 else 'nB=0' for k,v in exact.items() if v is None}}

def sort_key(r):
    return (-Fraction(r['exact']['lift']),-Fraction(r['exact']['confidence']),-Fraction(r['exact']['support']),
            len(r['antecedent']),tuple(r['antecedent']),tuple(r['consequent']))

def count_rules(baskets,rules):
    tx=transactions(baskets);cache={};seen=set();out=[]
    def count(items):
        key=tuple(sorted(items))
        if key not in cache:cache[key]=sum(set(key)<=t for t in tx)
        return cache[key]
    for rule in rules:
        validate_rule(rule);require(rule['rule_id'] not in seen,'rule','duplicate directed rule');seen.add(rule['rule_id'])
        out.append(metric_row(rule,len(tx),count(rule['antecedent']),count(rule['consequent']),count(rule['antecedent']+rule['consequent'])))
    return out



def evaluate(baskets,frozen,evaluation_id):
    require(evaluation_id in EVALUATIONS and all(r['version_id'] in EVALUATIONS[evaluation_id] for r in baskets),
            'partition','basket outside evaluation')
    tx=transactions(baskets);states=Counter(r['state'] for r in baskets);N=len(tx)
    counts={'candidate_basket_count':len(baskets),'eligible_basket_count':N,'nonempty_basket_count':states['eligible_nonempty'],
        'empty_basket_count':states['eligible_empty'],'coverage_incomplete_count':states['coverage_incomplete'],
        'eligible_unique_player_count':len({r['user_id'] for r in baskets if r['items'] is not None}),
        'frozen_rule_count':len(frozen['rules']),'displayed_rule_count':len(frozen['display_rule_ids'])}
    windows={r['window_id']:{k:r[k] for k in ('window_id','version_id','region_id','w_start','w_end','as_of')} for r in baskets}
    return {'evaluation_id':evaluation_id,'rule_set_id':frozen['rule_set_id'],'counts':counts,
        'windows':sorted(windows.values(),key=lambda w:w['window_id']),
        'basket_size':{str(i):sum(len(t)==i for t in tx) for i in range(7)},
        'activities':[{'activity_id':k,'name':config()['activities'][k],'count':sum(k in t for t in tx),
                       'participation_rate':sum(k in t for t in tx)/N if N else None} for k in ITEMS],
        'rules':count_rules(baskets,frozen['rules']),'display_rule_ids':frozen['display_rule_ids'],
        'status':'no_eligible_baskets' if not N else frozen['status']}
