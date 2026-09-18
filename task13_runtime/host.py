"""Original-environment controller, deadlines and evidence validation."""
import os
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
from task13_runtime.common import CONFIG, ROOT, HostError, append, clean_environment, lines, read, replace, require, verify_task08, write, within_run
from agent_runtime.claims import EvidenceIndex
from agent_runtime.processes import DriverProcess
from task12_knowledge.corpus import Corpus
from task11_runtime.segments import ClusterEvidence
from segmentation.assets import verify_trusted_asset,evidence_identity
from knowledge_core.service import KnowledgeEvidence
from task13_runtime.answers import verify_answer, require_completed, completion_summary


class Host:
    def __init__(self, directory, *, association_asset, admission, condition, quality_binding=None, mode="offline", budget_cny=5, offline_base_url=None, budget_file=None, offline_controls=None, offline_corpus=None):
        require(mode in ("offline", "live"), "mode", "mode must be explicit offline or live")
        require(0 < budget_cny <= 5, "budget", "this development host permits at most 5 CNY")
        self.mode = mode
        self.directory = within_run(directory); self.directory.mkdir(parents=True)
        self.config = read(CONFIG)
        self.registered = verify_task08(self.config)
        from task13_runtime.quality import bind,public_prompt
        from task13_runtime.evidence import CurrentEvidence
        require(condition in ('H0','H1'),'condition','fixed condition enum required')
        self.registered=bind(self.registered,quality_binding)
        self.evidence = CurrentEvidence(self.registered["definition"], self.registered["schemas"])
        self.history=[]
        self.request_scope = {}
        require(offline_corpus is None or mode == "offline", "mode", "fixture corpus is offline controller-only")
        self.corpus = Corpus(within_run(offline_corpus) if offline_corpus is not None else None)
        from task13_runtime.common import accepted_segmentation
        from task12_runtime.artifacts import host_asset_trust
        from task12_runtime.rules import RuleEvidence
        self.asset,self.asset_trust=accepted_segmentation()
        self.rule_asset=Path(association_asset).resolve()
        self.rule_trust=host_asset_trust(self.rule_asset,mode)
        self.rules=RuleEvidence(self.rule_asset,self.rule_trust)
        manifest=verify_trusted_asset(self.asset,self.asset_trust,live=mode=='live')
        self.clusters = ClusterEvidence(evidence_identity(self.asset,manifest),self.verify_frozen_asset)
        self.knowledge = KnowledgeEvidence(self.corpus)
        self.loaded_calls = 0
        self.canary = "task09-canary-"+uuid4().hex
        self.driver = None
        self.lifecycle_lock = threading.RLock()
        self.closing = False
        self.admission_closed = False
        self.cfg = {"directory": str(self.directory), "project_root": str(ROOT), "original_python": str(Path(sys.executable).resolve()),
            "condition":condition,"admission":admission,"quality_binding":quality_binding,
            "public_adaptation":public_prompt(quality_binding,self.registered['definition']),
            "mode": mode, "budget_cny": budget_cny, "budget_file": str(budget_file or self.directory/"budget.json"),
            "turn_file": str(self.directory/"turn.json"), "model_timeout_seconds": 180,
            "offline_base_url": offline_base_url if mode == "offline" else None,
            "knowledge_identity": self.corpus.identity,
            "segmentation_asset": str(self.asset),
            "segmentation_trust": self.asset_trust,
            "association_asset":str(self.rule_asset),"association_trust":self.rule_trust,
            "offline_corpus": str(self.corpus.home) if offline_corpus is not None else None}
        require(not offline_controls or mode == "offline", "mode", "offline controls cannot enter live host")
        if offline_controls:
            require(set(offline_controls) <= {"model_timeout_seconds", "network_probe", "workspace_canary", "reply_probe", "budget_commit_probe"}, "mode", "unknown offline control")
            self.cfg.update(offline_controls)
        write(self.directory/"config.json", self.cfg)
        write(self.directory/"turn.json", {"turn_id": "boot", "stopped": False})

    def verify_frozen_asset(self):
        self.rules.validate()
        return verify_trusted_asset(self.asset,self.asset_trust,live=self.mode=='live')

    def open(self):
        self.verify_frozen_asset()
        if os.name == 'nt':
            executable = (ROOT / self.config["host_python"]).resolve(strict=True)
            require(executable != Path(sys.executable).resolve(), "environment", "host must use independent venv")
            argv = [str(executable), "-m", "task13_runtime.dsh_driver"]
        else:
            require((ROOT/'_dsh_vendor/deepseek_harness').is_dir(), 'environment', 'isolated Linux SDK dependencies missing')
            argv = [sys.executable, '-S', '-m', 'cloud_api.dsh_bootstrap']
        env = clean_environment()
        if self.mode == "offline": env["TASK09_OFFLINE_CREDENTIAL"] = self.canary
        if self.mode == "live":
            require(bool(os.environ.get("DEEPSEEK_API_KEY")), "credential", "set DEEPSEEK_API_KEY locally; it is not read from global DSH config")
            env["DEEPSEEK_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
        with self.lifecycle_lock:
            require(not self.closing, 'session_closed', 'session cancelled before driver startup')
            self.driver = DriverProcess(argv, ROOT, env, self.directory/"controller")
        self.cfg["owned_job_name"] = self.driver.job.name
        replace(self.directory/"config.json", self.cfg)
        self.driver.send({"config": str(self.directory/"config.json")})
        initial = self.driver.receive(90)
        require(initial.get("ready") is True, "dsh_start", "actual DSH initialization failed; see driver diagnostics")
        return self

    def collect_evidence(self):
        calls = list(lines(self.directory/"mcp/tool_calls.jsonl"))
        for call in calls[self.loaded_calls:]:
            self.evidence.record(call)
            if call['result'].get('status')=='not_applicable':continue
            if call["name"] == "search_knowledge":
                self.knowledge.add(call["result"], self.evidence.session_id, call["turn_id"])
            elif call['name'] == 'assign_segments':
                self.clusters.add(call['result'], self.evidence.session_id, call['turn_id'],call['arguments'])
            elif call['name']=='query_association_rules':
                self.rules.add(call['result'],self.evidence.session_id,call['turn_id'],call['arguments'])
            else:
                self.evidence.add(call["result"])
        self.loaded_calls = len(calls)
        return calls

    def offline_new_session(self):
        require(self.mode == "offline", "mode", "only independent offline cases reset DSH history")
        self.driver.send({"op": "offline_new_session"})
        result = self.driver.receive(60)
        require(bool(result.get("new_session")), "session", "DSH did not create a fresh offline session")
        return result

    def turn(self, text, turn_id=None, *, validate=True, timeout=900, require_rule_discovery=False, on_progress=None):
        deadline = time.monotonic() + timeout
        require(type(require_rule_discovery) is bool, 'command', 'require_rule_discovery must be boolean')
        self.verify_frozen_asset()
        turn_id = turn_id or "turn"+uuid4().hex
        from task13_runtime.request_scope import contract, validate_context, validate_selections
        bound_scope = contract(text, self.request_scope)
        # A prior rejected/incomplete user turn may have produced MCP calls
        # without reaching collect_evidence. They remain in audit, not this index.
        self.loaded_calls=len(list(lines(self.directory/'mcp/tool_calls.jsonl')))
        self.evidence.begin(turn_id)
        replace(self.directory/'public_state.json',{'current_user':text,'history':self.history[-2:],'calls':[]})
        history_item={'user':text,'verified_scopes':[],'status':'historical_not_current_evidence'}
        self.history.append(history_item)
        first_call = self.loaded_calls
        first_bridge = len(list(lines(self.directory/'internal_bridge.jsonl')))
        write(self.directory/(turn_id+"_input.json"), {"text": text, "mode": self.mode,
              "require_rule_discovery": require_rule_discovery})
        self.driver.send({"op": "turn", "turn_id": turn_id, "text": text,
                          "require_rule_discovery": require_rule_discovery})
        from task13_runtime.progress import ProgressReader
        reader = ProgressReader(self.directory, turn_id, on_progress)
        result = self.driver.receive(timeout, on_poll=reader.drain)
        bridge_timeouts=[r for r in list(lines(self.directory/'internal_bridge.jsonl'))[first_bridge:]
            if r.get('response',{}).get('error',{}).get('code')=='tool_timeout']
        if bridge_timeouts:
            raise TimeoutError('Task13 real MCP tool deadline; controller must reclaim owned process tree')
        if result.get('turn_id')==turn_id and 'content_failure' in result:
            write(self.directory/(turn_id+'_raw_result.json'),result)
            self.collect_evidence()
            raise HostError(result['content_failure']['code'],result['content_failure']['message'])
        require(result.get("turn_id") == turn_id and "result" in result, "dsh_turn", "DSH did not finish the requested turn")
        write(self.directory/(turn_id+"_raw_result.json"), result)
        if on_progress is not None: on_progress({"code": "checking", "turn_id": turn_id})
        calls = self.collect_evidence()[first_call:]
        if validate:
            try:
                failure_path = Path(self.cfg["budget_file"]).with_name(Path(self.cfg["budget_file"]).name+".commit_failed.json")
                require(not failure_path.exists(), "budget_write", "预算文件提交失败，原账本及费用预留保留；详见 " + str(failure_path))
                validate_context(calls, turn_id)
                require_completed(result['result'])
                if require_rule_discovery:
                    require(any(c['turn_id']==turn_id and c['name']=='query_association_rules'
                                and c['arguments'].get('evaluation_id')=='discovery_V1_V3'
                                and c['result'].get('evidence_id') in self.rules.entries
                                and c['result']['error'] is None for c in calls),
                            'rule_discovery', 'current-turn successful development query required; previous turns cannot release this prerequisite')
                try:
                    answer = verify_answer(result["result"]["final_response"], self.evidence, self.knowledge, self.clusters, self.rules,turn_id)
                except HostError as first_error:
                    # One answer-only correction, within the SAME turn and ledger.
                    # Never repair network, integrity, scope-authority or budget failures.
                    if first_error.code not in ('selection','selection_scope'): raise
                    from task13_runtime.admission import Admission
                    quota=Admission(self.cfg['admission']).call('quota',turn_id=turn_id)
                    if min(quota['requests_remaining'],quota['task_requests_remaining'])<1: raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TimeoutError('Turn deadline reached before answer correction')
                    write(self.directory/(turn_id+'_repair.json'),{'reason':first_error.code,'limit':1,'same_turn':True,'tools_allowed':False})
                    self.driver.send({'op':'repair','turn_id':turn_id,'text':
                        '宿主拒绝了最终引用（'+first_error.code+'）。只纠正最终JSON，不能重新调用工具或改变用户范围。'
                        'compare_results 仅可引用 rate_difference、percentage_point_difference 或计数差异；没有 rate 字段。'
                        '原始 rate/numerator/denominator 必须引用对应 query_metric 证据和该版本scope。'
                        '仅用本轮已取得的真实证据，删去多余的非法引用及对应正文块，满足用户明确要求，保留五字段或合法partial结构。',
                        'require_rule_discovery':require_rule_discovery})
                    repaired=self.driver.receive(remaining,on_poll=reader.drain)
                    write(self.directory/(turn_id+'_repair_result.json'),repaired)
                    require(repaired.get('turn_id')==turn_id and 'result' in repaired,'answer_repair','Correction did not complete.')
                    require_completed(repaired['result'])
                    answer=verify_answer(repaired['result']['final_response'],self.evidence,self.knowledge,self.clusters,self.rules,turn_id)
                validate_selections(answer, bound_scope)
            except HostError as exc:
                write(self.directory/(turn_id+"_rejection.json"), {
                    "status": "failed", "displayed_as_verified": False,
                    "error": {"type": type(exc).__name__, "code": exc.code, "message": str(exc)},
                    "completion": completion_summary(result['result']),
                    "input_file": turn_id+"_input.json", "raw_result_file": turn_id+"_raw_result.json"})
                raise
            write(self.directory/(turn_id+"_answer.json"), answer)
            if answer.get('status')!='control_checked': self.request_scope = bound_scope
            history_item['verified_scopes']=[r['scope'] for r in answer['claims']]
            return answer
        return result

    def close(self):
        with self.lifecycle_lock:
            self.closing = True
            failures = []
            if self.driver is not None:
                try:
                    self.driver.close()
                    self.driver = None
                except Exception as exc:
                    failures.append(exc)
            if not self.admission_closed:
                try:
                    from task13_runtime.admission import Admission
                    Admission(self.cfg['admission']).call('close')
                    self.admission_closed = True
                except Exception as exc:
                    failures.append(exc)
            if failures:
                raise ExceptionGroup('host cleanup failed', failures)

    def __enter__(self):
        try: return self.open()
        except BaseException: self.close(); raise

    def __exit__(self, *args): self.close()
