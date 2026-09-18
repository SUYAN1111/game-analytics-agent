"""Synchronous durable reservations. No remote model call before Postgres commits."""
import copy
import time
from contextlib import contextmanager
from agent_runtime.common import replace, require, HostError
from product_core.budget import GlobalBudget


class CloudBudget(GlobalBudget):
    def __init__(self, store, path, jid, token, logical_session):
        self.store, self.jid, self.token, self.logical_session = store, jid, token, logical_session
        state = store.ledger()
        super().__init__(path, state['limit_cny'])
        replace(self.path, state)

    @contextmanager
    def locked(self, operation='update'):
        require(self.commit_error is None, 'budget_write', 'cloud budget commit was not confirmed')
        import json
        try:
            with self.store.connect() as db:
                state = self.store.ledger()
                before = copy.deepcopy(state)
                if operation in ('reserve','tool','revise'):
                    run = db.execute('SELECT e.*,j.status FROM executions e JOIN jobs j ON j.id=e.job_id WHERE e.job_id=?', (self.jid,)).fetchone()
                    require(run and run['token']==self.token and not run['finished'] and run['deadline']>time.time()
                            and run['status']=='running', 'session_closed', 'execution lease expired or cancelled')
                    own = [a for a in state['attempts'] if a.get('logical_session') == self.logical_session]
                    if operation == 'reserve': require(len(own)<12, 'model_limit', '12 conversation requests reached')
                    if operation == 'tool':
                        require(sum(a.get('logical_session')==self.logical_session for a in state.get('tools',[]))<24,
                                'tool_limit', '24 conversation tools reached')
                yield state
                for collection in ('attempts','tools'):
                    for item in state.get(collection, [])[len(before.get(collection,[])):]:
                        item['logical_session'] = self.logical_session
                own = [a for a in state['attempts'] if a.get('logical_session') == self.logical_session]
                require(sum(a.get('actual_cny', a['reserved_cny']) for a in own)<=5, 'session_budget', 'conversation budget exceeded')
                db.execute('UPDATE budgets SET payload=? WHERE id=1', (json.dumps(state),))
            # This file is an audit mirror for the existing controller, not authority.
            replace(self.path, state)
        except HostError:
            raise
        except Exception as exc:
            self.commit_error = {'code':'budget_write'}
            raise HostError('budget_write', 'cloud budget commit unavailable; no automatic retry') from exc

    def quota(self, session, turn_id):
        state=self.store.ledger()
        own=[a for a in state['attempts'] if a.get('logical_session')==self.logical_session]
        tools=[a for a in state.get('tools',[]) if a.get('logical_session')==self.logical_session]
        n=sum(a['turn_id']==turn_id for a in own); t=sum(a['turn_id']==turn_id for a in tools)
        return {'requests_used':n,'requests_remaining':6-n,'tools_used':t,'tools_remaining':12-t,
                'task_requests_remaining':12-len(own),'task_tools_remaining':24-len(tools)}
