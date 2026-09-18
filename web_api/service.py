"""Durable admission + one analysis worker + independent cancellation control."""
import json
import re
import threading
import time
from uuid import uuid4
from agent_runtime.common import read
from product_core.paths import STATE
from product_core.session import Runtime
from web_api.store import Store
from web_api.scenarios import FRIENDLY_QUESTIONS as QUESTIONS, FAULTS, script
from web_api.evidence import snapshots
from web_api.capabilities import route, control, public_capabilities

ACTIVE = ('queued', 'running', 'cancelling')
ERRORS = {
    'failed': '这次分析没有完成，请新建对话再试一次。',
    'reference_failed': '这次回答的数据依据未能核对通过，请新建对话再试一次。',
    'timed_out': '这次分析等待时间过长，已停止。请新建对话再试一次。',
    'cancelled': '本次任务已取消，此对话已结束，可新建对话。',
    'queued_cancelled': '排队任务已撤销，此对话可以继续。',
    'budget_stopped': '本次体验的可用额度已暂停，请联系管理员后再试。',
    'quota_reached': '本轮或本对话已达到调用或费用上限，不会自动重试。可新建对话；共享预算仍按原账本约束。',
    'asset_missing': '分析所需的数据暂时不可用，请联系管理员检查数据源。',
    'offline_unsupported': '当前演示使用固定示例，暂时无法理解这个问题。你的原问题已保留，可以修改后再试，或展开分析方向参考示例。',
    'close_failed': '对话暂时未能结束，请再次点击“结束对话”重试。',
    'interrupted': '服务已重启，任务中断且未重发。历史对话只读，请新建对话。',
}


class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class Service:
    def __init__(self, mode='live', period='live-main', queue_limit=8, timeout=900, budget=4.9, summary=False):
        if mode not in ('offline', 'live') or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', period):
            raise ValueError('invalid local mode/period')
        if not 1 <= queue_limit <= 32 or not 1 <= timeout <= 900: raise ValueError('invalid queue/timeout')
        self.mode, self.period, self.queue_limit, self.timeout, self.summary = mode, period, queue_limit, timeout, summary
        self.home = STATE / 'web' / mode / period
        self.home.mkdir(parents=True, exist_ok=True)
        # Windows byte-range lock is released by OS on process exit, including crashes.
        import msvcrt
        self.guard = (self.home / 'service.lock').open('a+b')
        self.guard.seek(0); self.guard.write(b'0'); self.guard.flush(); self.guard.seek(0)
        try: msvcrt.locking(self.guard.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.guard.close()
            raise ValueError('this mode and budget period already has a running service')
        self.cv = threading.Condition(threading.RLock())
        self.cores, self.opening, self.controllers = {}, set(), []
        self.executing = set()
        self.stopping = False
        self.runtime = None
        self.stub = None
        try:
            self.store = Store(self.home / 'web.sqlite3')
            with self.store.connect() as db:
                for row in db.execute("SELECT id FROM jobs WHERE status IN ('queued','running','cancelling')").fetchall():
                    self.transition(db, row['id'], 'interrupted', error=self.error('interrupted'))
                db.execute("UPDATE sessions SET status='read_only' WHERE status!='closed'")
            self.runtime = Runtime(budget, service_directory=self.home / 'budget', service_identity={'mode': mode, 'period': period})
            if mode == 'offline':
                from product_core.offline_stub import ModelStub
                self.stub = ModelStub(self.runtime.directory / 'provider')
            self.worker = threading.Thread(target=self.work, name='analysis-worker', daemon=True)
            self.worker.start()
        except BaseException:
            if self.runtime: self.runtime.close()
            self.guard.close()
            raise

    @staticmethod
    def error(code): return {'code': code, 'message': ERRORS[code]}

    @staticmethod
    def public_session(row):
        # The HttpOnly owner capability is never reflected into JavaScript DTOs.
        return {key:row[key] for key in ('id','title','status','created')}

    @staticmethod
    def transition(db, job_id, status, *, answer=None, error=None):
        at = time.time()
        db.execute('UPDATE jobs SET status=?,updated=?,answer=?,error=? WHERE id=?',
                   (status, at, json.dumps(answer, ensure_ascii=False) if answer else None,
                    json.dumps(error, ensure_ascii=False) if error else None, job_id))
        db.execute('INSERT INTO events(job_id,status,at) VALUES(?,?,?)', (job_id, status, at))

    def progress(self, sid, jid, tid, event):
        from task13_runtime.progress import CODES
        from task13_runtime.common import TOOLS
        code = event.get('code')
        if event.get('turn_id') != tid or code not in CODES: return
        tool, operation = event.get('tool', ''), event.get('operation', '')
        if code.startswith('tool_') and tool not in TOOLS: return
        if not isinstance(operation, str) or len(operation)>64: return
        detail = {'code':code, 'tool':tool if tool in TOOLS else '', 'operation':operation}
        key = json.dumps(detail, sort_keys=True)
        with self.cv, self.store.connect() as db:
            row = db.execute('SELECT status,session_id,turn_id FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row or row['status']!='running' or row['session_id']!=sid or row['turn_id']!=tid: return
            db.execute('INSERT OR IGNORE INTO events(job_id,status,at,detail,event_key) VALUES(?,?,?,?,?)',
                       (jid,'running',time.time(),json.dumps(detail),key))

    @staticmethod
    def owned(db, owner, sid):
        row = db.execute('SELECT * FROM sessions WHERE id=? AND owner=?', (sid, owner)).fetchone()
        if not row: raise APIError(404, 'not_found', '记录不存在。')
        return row

    def budget(self):
        state = read(self.runtime.ledger.path)
        attempts = state['attempts']
        return {'limit_cny': state['limit_cny'], 'actual_cny': sum(a.get('actual_cny', 0) for a in attempts),
                'reserved_unknown_cny': sum(a['reserved_cny'] for a in attempts if 'actual_cny' not in a),
                'request_count': len(attempts), 'stopped': state['stopped'] or self.runtime.ledger.failure_path.exists() or self.runtime.ledger.commit_error is not None}

    def health(self):
        budget = self.budget()
        return {'mode': self.mode, 'period': self.period, 'assets_ready': True,
                'budget': budget if self.mode == 'offline' else {'stopped': budget['stopped']},
                'capabilities': [
                    {'title':'版本对比','description':'比较两次游戏更新后，玩家开始剧情的情况。重点看：已经可以开始剧情，但过了 3 天仍没开始的比例。','examples':[QUESTIONS[0]]},
                    {'title':'参与预测','description':'看看模型如何估计玩家未开始剧情的可能性，并了解哪些对象有预测结果。使用历史数据演示，预测不等于实际结果。','examples':[QUESTIONS[5],QUESTIONS[1]]},
                    {'title':'玩家分组','description':'按游戏习惯认识不同类型的玩家：每组有多少人，最近两周玩了多少次，每次通常玩多久。','examples':[QUESTIONS[2]]},
                    {'title':'玩法关联','description':'了解同一批玩家通常会玩哪些内容，比如地图探索、战斗挑战或休闲小游戏。这里统计同一周内的游玩记录，不代表喜好或游玩顺序。','examples':[QUESTIONS[3]]},
                    {'title':'指标说明','description':'看不懂某个数字？了解它是怎么算出来的、统计了哪些人，以及适合用来回答什么问题。','examples':[QUESTIONS[6]]}],
                'capability_contract':public_capabilities(),
                'queue_limit': self.queue_limit, 'questions': QUESTIONS, 'fault_questions': FAULTS if self.mode == 'offline' else [],
                'mode_label': '本地模式' if self.mode == 'offline' else 'DeepSeek', 'simulated_data': True}

    def usage_attempts(self):
        return read(self.runtime.ledger.path)['attempts'] if self.mode == 'live' else []

    def public_job(self, db, row, after=0, attempts=None):
        from web_api.usage import summarize
        result = self.store.job(db, row, after)
        result['usage'] = summarize(self.usage_attempts() if attempts is None else attempts, {row['turn_id']}, self.mode)
        return result

    def sessions(self, owner, create=False):
        with self.cv, self.store.connect() as db:
            if create:
                sid = uuid4().hex
                db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (sid, owner, '新对话', 'open', time.time()))
                return self.public_session(self.owned(db, owner, sid))
            return [self.public_session(r) for r in db.execute('SELECT * FROM sessions WHERE owner=? ORDER BY created DESC', (owner,))]

    def session(self, owner, sid):
        with self.cv, self.store.connect() as db:
            row = self.owned(db, owner, sid)
            from web_api.usage import summarize
            attempts = self.usage_attempts()
            jobs = [self.public_job(db, r, attempts=attempts) for r in db.execute('SELECT * FROM jobs WHERE session_id=? ORDER BY created', (sid,))]
            return {**self.public_session(row), 'jobs': jobs,
                    'usage': summarize(attempts, {j['turn_id'] for j in jobs}, self.mode)}

    def submit(self, owner, sid, text, idem):
        with self.cv, self.store.connect() as db:
            session = self.owned(db, owner, sid)
            previous = db.execute('SELECT * FROM jobs WHERE session_id=? AND idem=?', (sid, idem)).fetchone()
            if previous:
                if previous['text'] != text: raise APIError(409, 'idempotency_conflict', '同一提交标识不能用于不同问题。')
                return self.public_job(db, previous)
            if self.stopping or session['status'] != 'open': raise APIError(409, 'read_only', '对话已结束或只读，请新建对话。')
            if db.execute("SELECT 1 FROM jobs WHERE session_id=? AND status IN ('queued','running','cancelling')", (sid,)).fetchone():
                raise APIError(409, 'busy', '此对话仍有任务在执行。')
            previous=None
            for old in db.execute("SELECT * FROM jobs WHERE session_id=? AND status IN ('succeeded','partial','clarification') ORDER BY created DESC LIMIT 8",(sid,)):
                candidate=self.store.job(db,old)
                if candidate.get('routing'):
                    previous=candidate;break
            decision=route(text,self.mode,previous)
            from task13_runtime.request_scope import contract
            decision['scope_contract']=contract(text,((previous or {}).get('routing') or {}).get('scope_contract'))
            local=decision['kind'] in ('guidance','clarification','out_of_scope')
            if not local and self.budget()['stopped']: raise APIError(409, 'budget_stopped', ERRORS['budget_stopped'])
            if not local and db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0] >= self.queue_limit:
                raise APIError(429, 'queue_full', '等待队列已满，请稍后手动提交。')
            jid, tid, at = uuid4().hex, 'turn'+uuid4().hex, time.time()
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)', (jid, sid, tid, idem, text, 'queued', at, at, None, None))
            db.execute('INSERT INTO routing VALUES(?,?)',(jid,json.dumps(decision,ensure_ascii=False)))
            db.execute("UPDATE sessions SET title=? WHERE id=? AND title='新对话'", (text[:40], sid))
            self.transition(db, jid, decision['kind'] if local else 'queued', answer={'status':'control','message':decision['message'],'choices':[{'text':c['text']} for c in decision.get('choices',[])]} if local else None)
            self.cv.notify_all()
            return self.public_job(db, db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone())

    def job(self, owner, jid, after=0):
        with self.cv, self.store.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row: raise APIError(404, 'not_found', '记录不存在。')
            self.owned(db, owner, row['session_id'])
            return self.public_job(db, row, after)

    def evidence(self, owner, sid, tid, eid):
        with self.cv, self.store.connect() as db:
            self.owned(db, owner, sid)
            row = db.execute('SELECT payload FROM evidence WHERE id=? AND session_id=? AND turn_id=?', (eid, sid, tid)).fetchone()
            if not row: raise APIError(404, 'not_found', '证据不属于当前对话和轮次。')
            return json.loads(row['payload'])

    def control_thread(self, fn, *args):
        thread = threading.Thread(target=fn, args=args, daemon=True, name='session-control')
        self.controllers.append(thread); thread.start()

    def cancel(self, owner, jid):
        with self.cv, self.store.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row: raise APIError(404, 'not_found', '记录不存在。')
            self.owned(db, owner, row['session_id'])
            if row['status'] == 'queued':
                self.transition(db, jid, 'cancelled', error=self.error('queued_cancelled'))
            elif row['status'] == 'running':
                self.transition(db, jid, 'cancelling')
                db.execute("UPDATE sessions SET status='closing' WHERE id=?", (row['session_id'],))
                self.control_thread(self.cleanup, row['session_id'], jid)
            self.cv.notify_all()
        return self.job(owner, jid)

    def close_session(self, owner, sid):
        with self.cv, self.store.connect() as db:
            row = self.owned(db, owner, sid)
            if row['status'] not in ('closed', 'closing', 'read_only'):
                for job in db.execute("SELECT * FROM jobs WHERE session_id=? AND status IN ('queued','running')", (sid,)).fetchall():
                    self.transition(db, job['id'], 'cancelled' if job['status']=='queued' else 'cancelling',
                                    error=self.error('queued_cancelled') if job['status']=='queued' else None)
                db.execute("UPDATE sessions SET status='closing' WHERE id=?", (sid,))
                job = db.execute("SELECT id FROM jobs WHERE session_id=? AND status IN ('cancelling','close_failed') ORDER BY created DESC", (sid,)).fetchone()
                self.control_thread(self.cleanup, sid, job['id'] if job else None)
            self.cv.notify_all()
        return self.session(owner, sid)

    def cleanup(self, sid, jid=None):
        with self.cv:
            while sid in self.opening: self.cv.wait(.1)
            core = self.cores.get(sid)
        failure = False
        try:
            if core: core.cancel()
        except Exception:
            failure = True
        with self.cv, self.store.connect() as db:
            db.execute('UPDATE sessions SET status=? WHERE id=?', ('close_failed' if failure else 'closed', sid))
            if jid:
                self.transition(db, jid, 'close_failed' if failure else 'cancelled', error=self.error('close_failed' if failure else 'cancelled'))
            self.cv.notify_all()

    def delete_session(self, owner, sid):
        """Remove web history only after its worker and cleanup have stopped writing."""
        deadline = time.monotonic() + 30
        with self.cv:
            # Ownership is checked before closing or touching any records.
            self.close_session(owner, sid)
            while True:
                with self.store.connect() as db:
                    row = db.execute('SELECT status FROM sessions WHERE id=? AND owner=?', (sid, owner)).fetchone()
                    if row is None: return {'id': sid, 'deleted': True}
                    status = row['status']
                if status == 'close_failed':
                    raise APIError(409, 'close_failed', '对话尚未能停止，没有删除任何记录，请稍后重试删除。')
                if status != 'closing' and sid not in self.executing and sid not in self.opening:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise APIError(409, 'delete_pending', '对话仍在停止中，没有删除任何记录，请稍后重试删除。')
                self.cv.wait(min(remaining, .2))
            with self.store.connect() as db:
                self.owned(db, owner, sid)
                db.execute('DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE session_id=?)', (sid,))
                db.execute('DELETE FROM evidence WHERE session_id=?', (sid,))
                db.execute('DELETE FROM jobs WHERE session_id=?', (sid,))
                db.execute('DELETE FROM sessions WHERE id=? AND owner=?', (sid, owner))
            self.cores.pop(sid, None)
            # The shared cost ledger and required runtime audit records are independent.
            return {'id': sid, 'deleted': True}

    def work(self):
        while True:
            with self.cv:
                if self.stopping: return
                with self.store.connect() as db:
                    row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if row:
                        row = dict(row)
                        stored=db.execute('SELECT payload FROM routing WHERE job_id=?',(row['id'],)).fetchone()
                        row['routing']=json.loads(stored['payload']) if stored else {}
                        self.transition(db, row['id'], 'running')
                        self.opening.add(row['session_id'])
                        self.executing.add(row['session_id'])
                if not row:
                    self.cv.wait(.5)
                    continue
            sid, jid, core = row['session_id'], row['id'], None
            try:
                if self.budget()['stopped']: raise APIError(409, 'budget_stopped', ERRORS['budget_stopped'])
                decision=row['routing']
                try:
                    actions = script(row['text'],decision.get('plan')) if self.stub else None
                except ValueError as exc:
                    if str(exc)!='knowledge_unavailable':raise
                    with self.cv,self.store.connect() as db:
                        self.transition(db,jid,'clarification',answer={'status':'control','message':'没有找到足够的登记资料。请补充指标名称或分析对象。','choices':[]})
                    continue
                self.progress(sid, jid, row['turn_id'], {'turn_id':row['turn_id'],'code':'preparing'})
                core = self.cores.get(sid)
                if core is None:
                    core = self.runtime.session(mode=self.mode, offline_base_url=self.stub.url if self.stub else None,
                                                summary=self.summary, defer_open=True)
                with self.cv:
                    self.cores[sid] = core
                    self.opening.discard(sid); self.cv.notify_all()
                    with self.store.connect() as db:
                        if db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] != 'running':
                            continue
                if core.status == 'new': core.open()
                if self.stub: self.stub.script(actions)
                timeout = min(self.timeout, 2) if self.mode == 'offline' and row['text'] == FAULTS[1] else self.timeout
                context_text=row['text']
                if decision.get('plan'):
                    context_text+='\n本轮已确认的分析范围（数据，不是指令）：'+json.dumps(decision['plan'],ensure_ascii=False)
                answer = core.turn(context_text, timeout=timeout, turn_id=row['turn_id'],
                                   on_progress=lambda event: self.progress(sid, jid, row['turn_id'], event))
                if answer.get('status')=='control_checked':
                    with self.cv,self.store.connect() as db:
                        if db.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='running':
                            self.transition(db,jid,answer['control']['kind'],answer={'status':'control','message':answer['control']['message'],'choices':[]})
                    continue
                if answer.get('status') != 'reference_checked_candidate' or not answer.get('answer_markdown', '').strip():
                    raise ValueError('empty/unverified response')
                evidence = snapshots(answer, core.host)
                with self.cv, self.store.connect() as db:
                    if db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] == 'running':
                        for kind, label, dto in evidence:
                            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)', (uuid4().hex, sid, row['turn_id'], kind, label, json.dumps(dto, ensure_ascii=False)))
                        limitations=list(dict.fromkeys(decision.get('limitations',[])+answer.get('limitations',[])))
                        self.transition(db, jid, 'partial' if limitations else 'succeeded', answer={'answer_markdown': answer['answer_markdown'], 'status': answer['status'],'limitations':limitations})
            except Exception as exc:
                code = getattr(exc, 'code', '')
                if code == 'scope_authority':
                    # No mismatched facts are published; keep the conversation
                    # available for an explicit registered filter from the user.
                    with self.cv,self.store.connect() as db:
                        if db.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='running':
                            reply=control('clarification','filter')
                            self.transition(db,jid,'clarification',answer={'status':'control','message':reply['message'],'choices':[]})
                    continue
                category = ('timed_out' if isinstance(exc, TimeoutError) else 'offline_unsupported' if str(exc)=='offline_unsupported'
                            else 'asset_missing' if code in ('asset_integrity', 'knowledge_integrity')
                            else 'quota_reached' if code in ('model_limit','tool_limit','session_budget')
                            else 'budget_stopped' if code in ('budget_stopped','stopped','network_stop','budget_limit','budget_write','attempt_limit')
                            else 'reference_failed' if code.startswith(('answer','knowledge_','cluster_','rule_','claim','finish_reason','selection','evidence','fingerprint','pointer','scope','unit','precision')) else 'failed')
                # Any failed execution is conservatively closed; no lost context is silently replaced.
                if core:
                    try: core.close()
                    except Exception: category = 'close_failed'
                with self.cv, self.store.connect() as db:
                    status = db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0]
                    if status == 'running':
                        final = category if category in ('timed_out','budget_stopped','close_failed') else 'failed'
                        self.transition(db, jid, final, error=self.error(category))
                        if core: db.execute('UPDATE sessions SET status=? WHERE id=?', ('close_failed' if category=='close_failed' else 'closed', sid))
            finally:
                with self.cv:
                    self.opening.discard(sid); self.cv.notify_all()
                    while True:
                        with self.store.connect() as db:
                            cancelling = db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] == 'cancelling'
                        if not cancelling: break
                        self.cv.wait(.1)
                    self.executing.discard(sid); self.cv.notify_all()

    def close(self):
        with self.cv:
            self.stopping = True
            with self.store.connect() as db:
                for row in db.execute("SELECT * FROM jobs WHERE status IN ('queued','running')").fetchall():
                    self.transition(db, row['id'], 'interrupted', error=self.error('interrupted'))
            self.cv.notify_all()
        failures = []
        try: self.runtime.close()
        except Exception as exc: failures.append(exc)
        self.worker.join(20)
        for thread in self.controllers: thread.join(15)
        if self.stub: self.stub.close()
        self.guard.close()
        if self.worker.is_alive(): failures.append(RuntimeError('analysis worker did not exit'))
        if failures: raise ExceptionGroup('service cleanup failed', failures)
