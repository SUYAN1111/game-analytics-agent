"""Audit Python opens. Not an operating-system/native-code sandbox."""
import os,sys,json,threading,re
from pathlib import Path
from product_core.paths import ROOT,ASSETS,STATE
_installed=False

def install(directory):
    global _installed
    if _installed:return
    _installed=True
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    fd=os.open(directory/('read_boundary_'+str(os.getpid())+'.jsonl'),os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    stdlib=Path(sys.base_prefix).resolve()
    windows=Path(os.environ.get('SYSTEMROOT','C:/Windows')).resolve()
    allowed=[ROOT,ASSETS,STATE,Path(sys.prefix).resolve(),stdlib,windows]
    if os.name != 'nt': allowed += [Path('/etc/ssl/certs'), Path('/usr/share/zoneinfo')]
    local=threading.local();seen=set()
    def audit(event,args):
        if event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)) or getattr(local,'busy',False):return
        local.busy=True
        try:
            p=Path(os.fsdecode(args[0])).resolve()
            if os.name != 'nt' and str(p) in ('/dev/null','/dev/urandom'): return
            if str(p).lower() in ('nul','nUL') or str(p).lower().endswith('\\nul'):return
            ok=any(p.is_relative_to(r) for r in allowed)
            flags=args[2] if len(args)>2 else 0
            writing=isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if os.name!='nt' and not writing and re.fullmatch(r'/proc/\d+/stat',str(p)):ok=True
            if writing and not p.is_relative_to(STATE):ok=False
            key=(str(p),writing,ok)
            if key not in seen:
                seen.add(key);os.write(fd,(json.dumps({'path':str(p),'writing':writing,'allowed':ok},ensure_ascii=False)+'\n').encode('utf-8'))
            if not ok:raise PermissionError('product read/write boundary denied: '+str(p))
        finally:local.busy=False
    sys.addaudithook(audit)
