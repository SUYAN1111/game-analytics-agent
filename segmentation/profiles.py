"""Frozen nearest-center assignment, current profiles, whole-view disclosure gate."""
from collections import Counter
from segmentation.contract import FEATURES, STATES, matrix, require
from segmentation.model import distances

def assign(snapshot, model):
    import numpy as np
    eligible=[r for r in snapshot['rows'] if r['state']=='eligible']
    counts=Counter(r['state'] for r in snapshot['rows'])
    require(set(counts)<=set(STATES),'state','unknown candidate state')
    N=len(snapshot['rows']); available=model['status']=='available';assigned=[];groups=[]
    if available:
        X=matrix([r['X'] for r in eligible]);labels,d,margin=distances(X,model)
        assigned=[{'user_id':r['user_id'],'segment_id':f'G{int(labels[i])+1:02}',
                   'squared_distances':d[i].tolist(),'nearest_distance_margin':float(margin[i])}
                  for i,r in enumerate(eligible)]
        for j in range(model['selected_k']):
            sub=X[labels==j];size=len(sub)
            stats={f:{'mean':float(sub[:,p].mean()) if size else None,
                      'median':float(np.median(sub[:,p])) if size else None,
                      'p25':float(np.quantile(sub[:,p],.25,method='linear')) if size else None,
                      'p75':float(np.quantile(sub[:,p],.75,method='linear')) if size else None}
                   for p,f in enumerate(FEATURES)}
            groups.append({'segment_id':f'G{j+1:02}','player_count':size,
                'share_of_assigned':size/len(eligible) if eligible else None,'features':stats})
    totals={'candidate_count':N,'eligible_count':len(eligible),'assigned_count':len(assigned),
        'unassigned_eligible_count':len(eligible)-len(assigned),
        **{s+'_count':counts[s] for s in STATES if s!='eligible'},
        'assignment_coverage':len(assigned)/N if N else None}
    require(sum(counts.values())==N,'counts','candidate partition mismatch')
    return {'snapshot_id':snapshot['snapshot_id'],'S':snapshot['S'],'segmentation_model_id':model['segmentation_model_id'],
            'status':'ok' if available else 'model_unavailable','counts':totals,'groups':groups,
            'assignments':assigned,'source_windows':snapshot['source_windows'],'feature_fingerprint':snapshot['feature_fingerprint']}

def public_view(result):
    import copy
    view=copy.deepcopy({k:v for k,v in result.items() if k!='assignments'})
    # Do not release detailed raw coverage records or per-user lists through the Agent.
    view['source_windows']={k:{n:v[n] for n in ('source_id','S','h','a','lag_seconds')}
                            for k,v in result['source_windows'].items()}
    sizes=[g['player_count'] for g in result['groups']]
    sizes += [result['counts'][s+'_count'] for s in STATES]
    restricted=any(0<n<20 for n in sizes)
    if restricted:
        view['status']='restricted_granularity';view['groups']=[]
        view['counts']={k:v if k=='candidate_count' else None for k,v in result['counts'].items()}
    view['disclosure']={'minimum_nonzero_count':20,'whole_snapshot_restricted':restricted,
                       'rule':'any nonempty cluster or candidate state of 1–19 hides all partitions and profiles'}
    view['method']={'assignment':'frozen standardized squared Euclidean; exact ties choose lowest canonical ID',
                    'interpretation':'descriptive cross-section; not migration, causality, payment preference or M03 labels',
                    'profile_scale':'original feature units; present snapshot, not training centers'}
    return view
