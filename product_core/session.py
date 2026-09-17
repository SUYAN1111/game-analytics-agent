"""Serial turns, independently cancellable sessions, and durable service budgets."""
import math
import threading
from uuid import uuid4
from product_core.paths import STATE, ASSETS, within_state
from product_core.release import verify
from product_core.budget import Coordinator, GlobalBudget
from task13_runtime.host import Host
from agent_runtime.common import write, read, now


class Runtime:
    def __init__(self, budget_cny=5, *, service_directory=None, service_identity=None):
        if type(budget_cny) not in (int, float) or not math.isfinite(budget_cny) or not 0 < budget_cny <= 5:
            raise ValueError('budget must be finite and in (0, 5] CNY')
        verify()
        self.state_lock = threading.RLock()
        self.close_lock = threading.Lock()
        self.status = 'open'
        self.sessions = []
        self.directory = STATE / ('runtime-' + uuid4().hex)
        ledger_directory = self.directory
        if service_directory is not None:
            ledger_directory = within_state(service_directory)
            ledger_directory.mkdir(parents=True, exist_ok=True)
            binding = ledger_directory / 'identity.json'
            expected = {'schema': 1, 'identity': service_identity, 'limit_cny': budget_cny}
            if binding.exists():
                if read(binding) != expected or not (ledger_directory / 'budget.json').is_file():
                    raise ValueError('persistent budget identity mismatch or missing ledger; manual recovery required')
            else:
                if (ledger_directory / 'budget.json').exists():
                    raise ValueError('unbound existing budget; manual recovery required')
                write(binding, expected)
            self.directory = ledger_directory / 'runs' / uuid4().hex
        self.directory.mkdir(parents=True)
        from product_core.provenance import record
        record(self.directory)
        self.ledger = GlobalBudget(ledger_directory / 'budget.json', budget_cny)
        state = read(self.ledger.path)
        if state['limit_cny'] != budget_cny:
            raise ValueError('persistent budget limit differs')
        if self.ledger.path.with_suffix('.lock').exists() or self.ledger.failure_path.exists():
            raise ValueError('budget recovery blocked by preserved lock/commit failure')
        if any(a['status'] == 'reserved_fee_unknown' for a in state['attempts']):
            self.ledger.stop('service restarted with unsettled requests; original reservations retained')
        self.coordinator = Coordinator(self.ledger, lambda: verify())

    def session(self, *, mode='offline', offline_base_url=None, summary=False, defer_open=False):
        with self.state_lock:
            if self.status != 'open': raise ValueError('runtime closed or closing')
            s = Session(self, mode, offline_base_url, summary)
            self.sessions.append(s)
        if not defer_open: s.open()
        return s

    def close(self):
        with self.close_lock:
            if self.status == 'closed': return
            with self.state_lock:
                self.status = 'closing'
                sessions = list(self.sessions)
            failures = []
            for session in sessions:
                try: session.close()
                except Exception as exc: failures.append(exc)
            try: self.coordinator.close()
            except Exception as exc: failures.append(exc)
            self.status = 'close_failed' if failures else 'closed'
            if failures: raise ExceptionGroup('runtime cleanup failed', failures)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class Session:
    def __init__(self, runtime, mode, url, summary):
        self.id = 'session-' + uuid4().hex
        self.runtime = runtime
        self.lock = threading.Lock()
        self.control = threading.RLock()
        self.status = 'new'
        self.host = Host(runtime.directory / 'sessions' / self.id, association_asset=ASSETS / 'association',
                         admission=runtime.coordinator.capability(self.id), condition='H1' if summary else 'H0',
                         mode=mode, offline_base_url=url, budget_file=runtime.ledger.path)

    @property
    def closed(self): return self.status == 'closed'
    @property
    def directory(self): return self.host.directory

    def open(self):
        with self.control:
            if self.status != 'new': raise ValueError('session cannot open')
            self.status = 'opening'
        try:
            self.host.open()
            with self.control:
                if self.status != 'opening': raise ValueError('session cancelled during open')
                self.status = 'open'
        except BaseException:
            self.close()
            raise
        return self

    def turn(self, text, *, timeout=900, require_rule_discovery=False, turn_id=None, on_progress=None):
        if not isinstance(text, str) or not text.strip(): raise ValueError('nonempty text required')
        if not self.lock.acquire(blocking=False): raise ValueError('same session is already executing')
        try:
            with self.control:
                if self.status != 'open': raise ValueError('session is not open')
            answer = self.host.turn(text, turn_id=turn_id, timeout=timeout, require_rule_discovery=require_rule_discovery, on_progress=on_progress)
            with self.control:
                if self.status != 'open': raise ValueError('cancelled result discarded')
            return answer
        except (TimeoutError, KeyboardInterrupt):
            self.cancel()
            raise
        finally: self.lock.release()

    def cancel(self): self.close()

    def close(self):
        with self.control:
            if self.status == 'closed': return
            self.status = 'closing'
            try: self.host.close()
            except BaseException:
                self.status = 'close_failed'
                raise
            self.status = 'closed'
            write(self.directory / 'closed.json', {'session': self.id, 'at': now(),
                  'policy': 'owned Windows job terminated; unknown fees retained; conservative global stop'})

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
