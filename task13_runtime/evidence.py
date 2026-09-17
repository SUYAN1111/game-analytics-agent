from agent_runtime.claims import EvidenceIndex
from task13_runtime.common import require

class CurrentEvidence(EvidenceIndex):
    def begin(self,turn_id):
        self.turn_id=turn_id;self.entries.clear();self.current_calls=[]

    def record(self,call):
        require(call['turn_id']==self.turn_id,'scope','stale turn evidence')
        self.current_calls.append(call)

    def metric_note(self,key,turn_id):
        require(turn_id==self.turn_id,'metric_note','old turn cannot release note')
        found=[]
        for call in self.current_calls:
            r=call['result'];args=call['arguments']
            if call['name'] not in ('query_metric','check_quality'):continue
            if args.get('case_id')!=self.definition['case_id']:continue
            if key=='metric_data_error' and r.get('error') and r['error']['code']=='data_error' and r['data'] is None:
                found.append({'request_id':r['request_id'],'scope':args,'evidence_id':None})
            elif key=='metric_not_computable' and r['error'] is None and r['evidence_id'] in self.entries:
                for row in r['data'].get('rows',[]):
                    if row.get('group_by')=='none' and row['denominator']==0 and row['rate'] is None:
                        found.append({'evidence_id':r['evidence_id'],'scope':{k:row[k] for k in
                            ('version_id','group_by','group_value')},'denominator':0,'rate':None})
        require(bool(found),'metric_note','no matching current actual overall evidence for '+key)
        return found
