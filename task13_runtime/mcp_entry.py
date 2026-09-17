"""Task13 binding over the unchanged lazy Task12 ten-tool surface."""
import argparse
import os
import time
import subprocess
from pathlib import Path
from task13_runtime.common import CONFIG, append, now, read, require, verify_task08, within_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    directory = within_run(args.directory)
    config = read(CONFIG)
    started = time.monotonic()
    require("DEEPSEEK_API_KEY" not in os.environ, "credential", "model credential reached MCP process")
    from analysis_tools.registry import load_registered
    from analysis_tools.host import Heartbeat
    from task13_runtime.quality import make_service,not_applicable
    from analysis_tools.contracts import ERRORS, canonical
    from mcp.server.mcpserver import MCPServer
    from mcp_types import Tool, CallToolResult, TextContent
    from task12_knowledge.corpus import Corpus
    from task12_runtime.surface import Surface
    # Product release binds the complete installed closure; historical reports are not read.
    host = load_registered(config["toolset_id"])
    require(host["role"] == "analysis_demo", "role", "registered role changed")
    append(directory/"lifecycle.jsonl", {"event": "spawned", "pid": os.getpid(), "parent_pid": os.getppid(),
           "at": now(), "credential_present": False})
    original_popen = subprocess.Popen
    launch_context = read(directory.parent.parent/"config.json")
    from task13_runtime.boundary import install
    install(directory)
    def observed_popen(*positional, **keywords):
        effective = keywords.get("env")
        if effective is None: effective = dict(os.environ)
        forbidden = [key for key in effective if any(word in key.upper() for word in ("API_KEY", "AUTHORIZATION", "ACCESS_TOKEN", "SECRET"))]
        require(not forbidden, "credential", "credential variable would reach a model inference child")
        process = original_popen(*positional, **keywords)
        from agent_runtime.processes import belongs_to_job
        try:
            member = belongs_to_job(process.pid, launch_context["owned_job_name"])
            require(member, "job", "inference child escaped this controller's owned Job")
        except BaseException:
            process.kill(); process.wait(); raise
        append(directory/"children.jsonl", {"parent_pid": os.getpid(), "pid": process.pid,
            "argv": positional[0] if positional else keywords.get("args"), "environment_keys": sorted(effective),
            "credential_present": False, "at": now(), "ownership": "actual exact named controller Windows job query",
            "owned_job_member": member})
        return process
    subprocess.Popen = observed_popen
    with Heartbeat(directory) as heartbeat:
        service = make_service(host, directory, heartbeat.progress,launch_context.get('quality_binding'))
        fixture = launch_context.get("offline_corpus")
        require(fixture is None or launch_context["mode"] == "offline", "mode", "fixture corpus forbidden in live")
        corpus = Corpus(within_run(fixture) if fixture is not None else None)
        require(corpus.identity == launch_context["knowledge_identity"], "knowledge_integrity", "MCP corpus differs from controller")
        from segmentation.assets import verify_trusted_asset
        verify_trusted_asset(launch_context['segmentation_asset'],launch_context['segmentation_trust'],
                             live=launch_context['mode']=='live')
        surface = Surface(service, corpus, directory, launch_context['segmentation_asset'],launch_context['segmentation_trust'],
                          launch_context['association_asset'],launch_context['association_trust'])
        from product_core.provenance import record
        record(directory)
        build_calls = []
        original_build = service.backend.build
        def observed_build(*positional, **keywords):
            if not service.backend.ready:
                build_calls.append(now())
                append(directory/"lifecycle.jsonl", {"event": "actual_backend_build", "at": build_calls[-1]})
            return original_build(*positional, **keywords)
        service.backend.build = observed_build
        class LazyServer(MCPServer):
            async def list_tools(self):
                append(directory/"lifecycle.jsonl", {"event": "tools_list", "seconds_since_start": time.monotonic()-started,
                    "pre_query_build": bool(build_calls), "at": now()})
                return [Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"],
                             output_schema=t["output_schema"]) for t in surface.catalog()]

            async def call_tool(self, name, arguments, context=None):
                # Original query() owns its lazy build; never build before MCP negotiation.
                began = time.monotonic()
                if launch_context.get('quality_binding') and name in ('predict_registered','read_model_card','assign_segments','query_association_rules'):
                    # The catalogue is unchanged, but foreign frozen identities cannot supply numbers.
                    result=not_applicable(service,name,arguments)
                else:
                    result = surface.dispatch(name, arguments, read(launch_context["turn_file"])["turn_id"])
                append(directory/"timings.jsonl", {"name": name, "seconds": time.monotonic()-began,
                       "request_id": result["request_id"], "pid": os.getpid()})
                return CallToolResult(content=[TextContent(type="text", text=canonical(result))],
                    structured_content=result, is_error=result["error"] is not None)
        try:
            append(directory/"lifecycle.jsonl", {"event": "protocol_start_without_build", "at": now()})
            LazyServer("Task13 lazy registered analysis", version="1", log_level="WARNING").run(transport="stdio")
        finally:
            subprocess.Popen = original_popen
            service.close()
            append(directory/"lifecycle.jsonl", {"event": "exited", "pid": os.getpid(), "at": now()})


if __name__ == "__main__":
    main()
