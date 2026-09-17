from knowledge_core.service import KnowledgeService,TOOL
from task11_runtime.segments import SegmentService
from task12_runtime.rules import RuleService
from agent_runtime.common import append

class Surface:
    def __init__(self,analysis,corpus,directory,asset,trust,association_asset,association_trust):
        self.analysis=analysis;self.directory=directory
        self.knowledge=KnowledgeService(corpus,analysis.session_id)
        self.segments=SegmentService(asset,analysis.session_id,trust)
        self.rules=RuleService(association_asset,analysis.session_id,association_trust)
    def catalog(self):return self.analysis.catalog()+[TOOL,self.segments.catalog(),self.rules.catalog()]
    def dispatch(self,name,args,turn_id,transport='mcp'):
        if name=='search_knowledge':result=self.knowledge.dispatch(args,turn_id)
        elif name=='assign_segments':result=self.segments.dispatch(args,turn_id)
        elif name=='query_association_rules':result=self.rules.dispatch(args,turn_id)
        else:result=self.analysis.dispatch(name,args,transport=transport)
        append(self.directory/'surface_calls.jsonl',{'name':name,'turn_id':turn_id,'result':result})
        return result
