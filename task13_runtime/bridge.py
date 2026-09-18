"""Internal JSON-line bridge -> REAL MCP 2.2.0; this internal channel is not MCP."""
import argparse
import json
import os
import sys
import time
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from task13_runtime.common import CONFIG, ROOT, TOOLS, HostError, append, canonical, clean_environment, now, read, require, write
from task13_runtime.admission import Admission
from task13_runtime.progress import signal


class ReplyTracker:
    def __init__(self):
        self.pending, self.done = {}, set()

    def begin(self, identifier, name):
        require(type(identifier) is str and identifier and identifier not in self.pending and identifier not in self.done,
                "call_id", "duplicate or empty request ID")
        self.pending[identifier] = name

    def finish(self, identifier, name):
        require(self.pending.get(identifier) == name, "call_id", "unknown, duplicate or cross-request response")
        self.pending.pop(identifier); self.done.add(identifier)


class Wire:
    def __init__(self, stream, path, direction):
        self.stream, self.path, self.direction = stream, path, direction

    def __getattr__(self, name): return getattr(self.stream, name)
    def __aiter__(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.stream.aclose()
    async def __anext__(self):
        import anyio
        try: return await self.receive()
        except anyio.EndOfStream: raise StopAsyncIteration

    def record(self, value):
        append(self.path, {"at": now(), "direction": self.direction,
            "message": {"parse_error": str(value)} if isinstance(value, Exception) else value.message.model_dump(mode="json", by_alias=True, exclude_unset=True)})

    async def receive(self):
        value = await self.stream.receive(); self.record(value); return value

    async def send(self, value):
        self.record(value); await self.stream.send(value)


class Connection:
    def __init__(self, directory, original_python):
        self.directory, self.original_python = Path(directory), original_python
        self.client = None

    async def __aenter__(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        from cloud_api.core_bootstrap import core_command
        from cloud_api.mcp_transport import owned_stdio_client
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stderr = (self.directory/"stderr.log").open("x", encoding="utf-8")
        command = core_command('task13_runtime.launch_mcp', '--directory', str(self.directory/'server'), executable=self.original_python)
        parameters = StdioServerParameters(command=command[0], args=command[1:],
            env=clean_environment(), cwd=str(ROOT))
        job_name = read(self.directory.parent/'config.json')['owned_job_name']
        @asynccontextmanager
        async def transport():
            async with owned_stdio_client(parameters, errlog=self.stderr, job_name=job_name) as (incoming, outgoing):
                yield Wire(incoming, self.directory/"mcp_wire.jsonl", "server_to_client"), Wire(outgoing, self.directory/"mcp_wire.jsonl", "client_to_server")
        self.client = Client(transport(), read_timeout_seconds=60, cache=None)
        began = time.monotonic()
        try:
            await self.client.__aenter__()
        except BaseException:
            self.stderr.close(); raise
        result = await self.client.list_tools()
        self.catalog = [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
                         "output_schema": t.output_schema} for t in result.tools]
        require(sorted(t["name"] for t in self.catalog) == sorted(TOOLS), "catalog", "MCP did not discover exactly ten tools")
        write(self.directory/"catalog.json", self.catalog)
        write(self.directory/"handshake.json", {"protocol": self.client.protocol_version, "seconds": time.monotonic()-began,
              "original_python": self.original_python, "bridge_pid": os.getpid(), "credential_present": "DEEPSEEK_API_KEY" in os.environ,
              "server_info": None if self.client.server_info is None else self.client.server_info.model_dump(mode="json", by_alias=True)})
        return self

    async def call(self, name, arguments, tool_call_id):
        import anyio
        began = time.monotonic()
        with anyio.fail_after(600):
            result = await self.client.call_tool(name, arguments, read_timeout_seconds=600)
        envelope = result.structured_content
        texts = [block.text for block in result.content if block.type == "text"]
        require(type(envelope) is dict and len(texts) == 1 and json.loads(texts[0]) == envelope,
                "wire", "MCP text and structured result disagree")
        require(result.is_error == (envelope["error"] is not None), "wire", "MCP error flag differs from envelope")
        turn = read(read(self.directory.parent/"config.json")["turn_file"])
        append(self.directory/"tool_calls.jsonl", {"tool_call_id": tool_call_id, "turn_id": turn["turn_id"], "name": name, "arguments": arguments,
            "result": envelope, "seconds": time.monotonic()-began, "at": now()})
        return envelope  # Only one complete copy enters model context.

    async def __aexit__(self, *args):
        try:
            await self.client.__aexit__(None, None, None)
        finally:
            self.stderr.close()
            append(self.directory/"lifecycle.jsonl", {"event": "MCP_closed", "at": now()})


def reserve_frozen_request(config,budget,args,turn):
    """No reservation/HTTP admission before the external asset anchor is checked."""
    from segmentation.assets import verify_trusted_asset
    from association.assets import verify_trusted
    require(not turn.get('stopped'),'stopped','user turn stopped')
    verify_trusted_asset(config['segmentation_asset'],config['segmentation_trust'],live=config['mode']=='live')
    verify_trusted(config['association_asset'],config['association_trust'],live=config['mode']=='live')
    return budget.reserve(args['request_bytes'],turn['turn_id'],args['max_tokens'],args['request_body_sha256'])


async def serve(config):
    import anyio
    from segmentation.assets import verify_trusted_asset,evidence_identity
    from task11_runtime.segments import ClusterEvidence
    from task12_runtime.rules import RuleEvidence
    directory = Path(config["directory"])
    def validate_asset():
        return verify_trusted_asset(config['segmentation_asset'],config['segmentation_trust'],live=config['mode']=='live')
    manifest=validate_asset()
    clusters=ClusterEvidence(evidence_identity(config['segmentation_asset'],manifest),validate_asset)
    rules=RuleEvidence(config['association_asset'],config['association_trust'])
    context_sessions={};asset_failure=None
    budget = Admission(config['admission'])
    tracker = ReplyTracker()
    seen_tools = set()
    async with Connection(directory/"mcp", config["original_python"]) as connection:
        while True:
            line = await anyio.to_thread.run_sync(sys.stdin.readline)
            if not line: break
            request = json.loads(line)
            identifier, operation = request.get("id"), request.get("op")
            progress_tool_started = False
            try:
                tracker.begin(identifier, operation)
                args = request.get("args", {})
                if operation == "catalog":
                    result = connection.catalog
                elif operation == "tool":
                    require(args["name"] in TOOLS, "unauthorized", "tool not on capability allowlist")
                    call_id = args["tool_call_id"]
                    require(type(call_id) is str and call_id and call_id not in seen_tools, "call_id", "duplicate DSH tool call ID")
                    seen_tools.add(call_id)
                    progress_turn = read(config['turn_file'])['turn_id']
                    signal(directory, progress_turn, 'tool_started', call_id, args['name'])
                    progress_tool_started = True
                    result = await connection.call(args["name"], args["arguments"], call_id)
                    current_turn=read(config['turn_file'])['turn_id']
                    if args['name']=='inspect_context' and result.get('error') is None:
                        context_sessions[current_turn]=result['session_id']
                    if args['name']=='assign_segments' and result.get('status')!='not_applicable':
                        require(current_turn in context_sessions,'cluster_session','missing current MCP context')
                        clusters.add(result,context_sessions[current_turn],current_turn,args['arguments'])
                    if args['name']=='query_association_rules' and result.get('status')!='not_applicable':
                        require(current_turn in context_sessions,'rule_session','missing current MCP context')
                        rules.add(result,context_sessions[current_turn],current_turn,args['arguments'])
                    signal(directory, progress_turn, 'tool_failed' if result.get('error') or result.get('status')=='not_applicable' else 'tool_finished', call_id, args['name'])
                elif operation == "reserve":
                    require(asset_failure is None,'asset_integrity','frozen identity failure stopped this host: '+str(asset_failure))
                    turn = read(config["turn_file"])
                    result = reserve_frozen_request(config,budget,args,turn)
                    signal(directory, turn['turn_id'], 'model_started', result['attempt_id'])
                elif operation == "settle":
                    result = budget.settle(args["attempt_id"], args.get("usage"), args.get("error"))
                    signal(directory, read(config["turn_file"])["turn_id"], "model_finished", args["attempt_id"])
                elif operation == 'tool_attempt':
                    result=budget.call('tool',turn_id=read(config['turn_file'])['turn_id'],call_id=args['call_id'])
                elif operation == 'summary':
                    from task13_runtime.state import summarize
                    public=read(directory/'public_state.json')
                    turn_id=read(config['turn_file'])['turn_id']
                    from task13_runtime.common import lines
                    public['calls']=[c for c in lines(directory/'mcp/tool_calls.jsonl') if c['turn_id']==turn_id]
                    result=summarize(public,budget.call('quota',turn_id=turn_id))
                    append(directory/'summaries.jsonl',{'turn_id':turn_id,**result})
                else:
                    raise HostError("unauthorized", "unknown internal bridge operation")
                tracker.finish(identifier, operation)
                response = {"id": identifier, "op": operation, "result": result}
            except Exception as exc:
                if progress_tool_started:
                    signal(directory, read(config['turn_file'])['turn_id'], 'tool_failed', call_id, args['name'])
                code='tool_timeout' if isinstance(exc,TimeoutError) and operation=='tool' else getattr(exc,'code','bridge')
                if code=='asset_integrity' or code.startswith(('cluster_','rule_')):
                    asset_failure=str(exc)
                    budget.stop('frozen asset/evidence identity failure; no further model requests')
                response = {"id": identifier, "op": operation, "error": {"type": type(exc).__name__, "code": code, "message": str(exc)}}
            append(directory/"internal_bridge.jsonl", {"request": request, "response": response, "protocol": "internal_jsonl_not_MCP"})
            probe = config.get("reply_probe") if config["mode"] == "offline" and operation == "catalog" else None
            if probe in ("unknown", "crossed"):
                fault = dict(response)
                if probe == "unknown": fault["id"] = "offline-unmatched-reply"
                else: fault["op"] = "wrong-operation"
                append(directory/"internal_bridge.jsonl", {"offline_reply_probe": probe, "actual_emitted_reply": fault})
                print(canonical(fault), flush=True)
            print(canonical(response), flush=True)
            if probe == "duplicate":
                append(directory/"internal_bridge.jsonl", {"offline_reply_probe": probe, "actual_emitted_reply": response})
                print(canonical(response), flush=True)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True)
    args = parser.parse_args()
    require("DEEPSEEK_API_KEY" not in os.environ, "credential", "model credential reached bridge")
    import anyio
    config = read(args.config)
    from task13_runtime.boundary import install
    install(config['directory'])
    with ExitStack() as stack:
        anyio.run(serve, config)


if __name__ == "__main__": main()
