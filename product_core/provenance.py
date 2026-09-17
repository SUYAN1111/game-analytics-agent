"""Import-location evidence; supplements Python open audit, not OS isolation."""
import sys,json,os
from pathlib import Path
from product_core.paths import ROOT
FIRST_PARTY={'product_core','agent_runtime','analysis_tools','analysis_core','metrics','preparation','features','modeling','case_adapters','knowledge_core','segmentation','association','task10_runtime','task11_runtime','task12_runtime','task13_runtime','task12_knowledge'}
def record(directory):
    modules={name:str(Path(m.__file__).resolve()) for name,m in list(sys.modules.items()) if name.split('.')[0] in FIRST_PARTY and getattr(m,'__file__',None)}
    if not modules or any(not Path(p).is_relative_to(ROOT) for p in modules.values()):raise RuntimeError('foreign first-party module import')
    if os.environ.get('PYTHONPATH'):raise RuntimeError('clear PYTHONPATH before starting product')
    p=Path(directory)/('imports-'+str(os.getpid())+'.json');p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({'modules':modules,'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'sys_path':sys.path},ensure_ascii=False,indent=2),'utf-8')
