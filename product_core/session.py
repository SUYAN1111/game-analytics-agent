"""Serial per-session host API; cancellation terminates its exact Windows job."""
import threading,math
from uuid import uuid4
from product_core.paths import STATE,ASSETS
from product_core.release import verify
from product_core.budget import Coordinator,GlobalBudget
from task13_runtime.host import Host
from agent_runtime.common import write,now

class Runtime:
    def __init__(self,budget_cny=5):
        if not isinstance(budget_cny,(int,float)) or isinstance(budget_cny,bool) or not math.isfinite(budget_cny) or not 0 < budget_cny <= 5:raise ValueError('budget must be finite and in (0, 5] CNY')
        verify();self.directory=STATE/('runtime-'+uuid4().hex);self.directory.mkdir(parents=True)
        from product_core.provenance import record
        record(self.directory)
        self.ledger=GlobalBudget(self.directory/'budget.json',budget_cny)
        self.coordinator=Coordinator(self.ledger,lambda:verify())
        self.sessions=[]
    def session(self,*,mode='offline',offline_base_url=None,summary=False):
        s=Session(self,mode,offline_base_url,summary);self.sessions.append(s);return s
    def close(self):
        for s in self.sessions:s.close()
        self.coordinator.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class Session:
    def __init__(self,runtime,mode,url,summary):
        self.id='session-'+uuid4().hex;self.runtime=runtime;self.lock=threading.Lock();self.closed=False
        self.host=Host(runtime.directory/'sessions'/self.id,association_asset=ASSETS/'association',
            admission=runtime.coordinator.capability(self.id),condition='H1' if summary else 'H0',mode=mode,
            offline_base_url=url,budget_file=runtime.ledger.path)
        try:self.host.open()
        except BaseException:
            self.host.close();raise
    @property
    def directory(self):return self.host.directory
    def turn(self,text,*,timeout=900,require_rule_discovery=False):
        if not isinstance(text,str) or not text.strip():raise ValueError('nonempty text required')
        if self.closed:raise ValueError('session closed')
        if not self.lock.acquire(blocking=False):raise ValueError('same session is already executing')
        try:
            return self.host.turn(text,timeout=timeout,require_rule_discovery=require_rule_discovery)
        except (TimeoutError,KeyboardInterrupt):
            self.cancel();raise
        finally:self.lock.release()
    def cancel(self):
        self.close()
    def close(self):
        if self.closed:return
        self.closed=True
        try:self.host.close()
        finally:write(self.directory/'closed.json',{'session':self.id,'at':now(),'policy':'owned Windows job terminated; unknown fees retained; conservative global stop'})
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
