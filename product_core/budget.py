"""One controller-owned ledger. Agent workers only hold per-session pipe capabilities."""
import threading
from multiprocessing.connection import Listener, Client
from uuid import uuid4
from agent_runtime.budget import Budget, cost
from task13_runtime.common import require, read, now

class GlobalBudget(Budget):
    def reserve_for(self, session, turn_id, byte_count, max_tokens=4096, request_sha256=None):
        require(type(byte_count) is int and 0 <= byte_count <= 262144, 'body_limit', 'request exceeds 262144 bytes')
        require(max_tokens == 4096, 'output_limit', 'output must be 4096')
        require(type(request_sha256) is str and len(request_sha256)==64, 'request_hash', 'final request hash required')
        amount = cost(byte_count+1024,0,4096)
        with self.locked('reserve') as state:
            require(not state['stopped'], 'stopped', 'global ledger stopped')
            attempts = state['attempts']; own = [a for a in attempts if a['session']==session]
            require(session not in state.get('closed_sessions',[]), 'session_closed', 'task authorization closed')
            require(len(attempts)<336, 'attempt_limit', '336 global requests reached')
            require(len(own)<12 and sum(a['turn_id']==turn_id for a in own)<6,
                    'model_limit','12 task / 6 turn requests reached')
            committed = lambda rows: sum(a.get('actual_cny',a['reserved_cny']) for a in rows)
            require(committed(own)+amount<=5, 'session_budget', 'task cumulative reservation exceeds 5 CNY')
            require(committed(attempts)+amount<=state['limit_cny'], 'budget_limit', 'global cumulative budget insufficient')
            item={'attempt_id':uuid4().hex,'session':session,'turn_id':turn_id,'request_bytes':byte_count,
                  'request_body_sha256':request_sha256,'reserved_cny':amount,'status':'reserved_fee_unknown','at':now()}
            attempts.append(item)
        return item

    def tool(self, session, turn_id, call_id):
        with self.locked('tool') as state:
            require(not state['stopped'] and session not in state.get('closed_sessions',[]),'stopped','authorization closed')
            attempts=state.setdefault('tools',[])
            require(not any(x['session']==session and x['call_id']==call_id for x in attempts),'call_id','duplicate tool attempt')
            own=[x for x in attempts if x['session']==session]
            require(len(own)<24 and sum(x['turn_id']==turn_id for x in own)<12,'tool_limit','24 task / 12 turn tools reached')
            attempts.append({'session':session,'turn_id':turn_id,'call_id':call_id})
        return self.quota(session,turn_id)

    def quota(self, session, turn_id):
        state=read(self.path)
        own=[a for a in state['attempts'] if a['session']==session]
        tools=[a for a in state.get('tools',[]) if a['session']==session]
        n=sum(a['turn_id']==turn_id for a in own); t=sum(a['turn_id']==turn_id for a in tools)
        return {'requests_used':n,'requests_remaining':6-n,'tools_used':t,'tools_remaining':12-t,
                'task_requests_remaining':12-len(own),'task_tools_remaining':24-len(tools)}

    def close_session(self, session):
        with self.locked('close_session') as state:
            if session not in state.setdefault('closed_sessions',[]):state['closed_sessions'].append(session)
            pending=[a for a in state['attempts'] if a['session']==session and a['status']=='reserved_fee_unknown']
            if pending:
                state['stopped']=True
                for a in pending:a['status']='interrupted_fee_unknown'
        return {'closed':session,'pending':len(pending)}

    def revise(self, limit):
        require(type(limit) in (float,int) and 0<limit<1e6,'budget','finite explicit cumulative budget required')
        with self.locked('revise') as state:
            require(not state['stopped'],'stopped','resume cannot bypass fatal stop')
            require(limit>=state['limit_cny'],'budget','cannot reduce committed run limit')
            state.setdefault('revisions',[]).append({'old':state['limit_cny'],'new':limit,'at':now()})
            state['limit_cny']=limit

class Coordinator:
    def __init__(self, ledger, verify):
        self.ledger,self.verify=ledger,verify
        self.auth=bytes.fromhex(uuid4().hex+uuid4().hex)
        self.address=r'\\.\pipe\task13-'+uuid4().hex
        self.sessions=set();self.errors=[]
        self.listener=Listener(self.address,family='AF_PIPE',authkey=self.auth)
        self.thread=threading.Thread(target=self.serve,daemon=True);self.thread.start()

    def capability(self, session):
        require(session not in self.sessions,'session','session already authorized')
        self.sessions.add(session)
        return {'address':self.address,'auth':self.auth.hex(),'session':session}

    def dispatch(self, request):
        session,op,args=(request[k] for k in ('session','operation','arguments'))
        require(session in self.sessions,'unauthorized','unknown session capability')
        if op=='reserve':
            self.verify()  # Controller-only independent release verification.
            return self.ledger.reserve_for(session,**args)
        if op=='settle':
            require(any(a['attempt_id']==args['attempt_id'] and a['session']==session
                        for a in read(self.ledger.path)['attempts']),'attempt_id','cross-session settlement')
            return self.ledger.settle(**args)
        if op=='tool':return self.ledger.tool(session,**args)
        if op=='quota':return self.ledger.quota(session,**args)
        if op=='close':return self.ledger.close_session(session)
        if op=='fatal':return self.ledger.stop(args['reason'])
        raise ValueError('unregistered coordinator operation')

    def serve(self):
        while True:
            request={}
            try:
                with self.listener.accept() as conn:
                    request=conn.recv()
                    if request=={'shutdown':True}:conn.send(True);break
                    try:reply={'result':self.dispatch(request)}
                    except Exception as exc:
                        error={'type':type(exc).__name__,'code':getattr(exc,'code','coordinator'),'message':str(exc),
                               'session':request.get('session'),'operation':request.get('operation'),
                               'turn_id':request.get('arguments',{}).get('turn_id')}
                        self.errors.append(error);reply={'error':error}
                    conn.send(reply)
            except (EOFError,OSError) as exc:
                self.errors.append({'type':type(exc).__name__,'code':'coordinator_disconnect','message':str(exc),
                    'session':request.get('session'),'operation':request.get('operation')})
                if request.get('operation') in ('reserve','settle'):
                    self.ledger.stop('reservation/settlement reply lost; retain unknown fees')

    def close(self):
        require(self.thread.is_alive(),'coordinator','coordinator failed before shutdown')
        with Client(self.address,family='AF_PIPE',authkey=self.auth) as conn:
            conn.send({'shutdown':True});conn.recv()
        self.thread.join(10);self.listener.close()
        require(not self.thread.is_alive(),'coordinator','coordinator did not stop')
