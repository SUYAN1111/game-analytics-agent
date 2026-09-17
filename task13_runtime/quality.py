"""Trusted startup binding; calculation remains in accepted Task01–Task03."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from task13_runtime.common import ROOT,read,sha,require,digest,now

def bind(host,binding):
    require(binding is None,'quality_identity','evaluation fixture binding not supported in product')
    return deepcopy(host)

def make_service(host,directory,progress,binding=None):
    require(binding is None,'quality_identity','no evaluation fixtures')
    from analysis_tools.host import make_service as original
    return original(host,directory,progress)

def not_applicable(analysis,name,args):
    return {'request_id':'req'+uuid4().hex,'session_id':analysis.session_id,'tool_name':name,
        'status':'not_applicable','validated_arguments':None,'data':None,'evidence_id':None,
        'source_identities':analysis.registry.identities,'warnings':[],
        'error':{'type':'ToolError','code':'not_applicable','message':'该冻结资产不适用于本次绑定的质量数据集。'},
        'runtime':{'transport':'mcp','started_at':now(),'executed_at':now(),'elapsed_seconds':0.0,
                   'cache_hit':False,'content_fingerprint':None}}

def public_prompt(binding,definition):
    common=('\n\nTask13 公共适配（两组一致）：每轮数字证据只可引用本轮成功工具结果，历史证据须重新查询。'
        '新增固定 note：metric_not_computable，仅本轮总体实际 denominator=0 且 rate=null 时使用，表示不可计算；'
        'metric_data_error，仅本轮实际工具 data_error 且 data=null 时使用，表示无法提供可靠指标。'
        '不得从通用错误推断具体输入冲突，不得将 null 写成0；仍须严格五字段JSON。')
    if binding:
        common+='\n本会话数据绑定优先于基础提示词中的主案例身份：'+str({k:definition[k] for k in
            ('case_id','metric_id','snapshot_set_id','cohorts','snapshots','identities')})+\
            '。这是固定模拟质量案例，仅总体查询；预测、模型卡、分群和活动规则不适用于此数据身份。'
    return common
