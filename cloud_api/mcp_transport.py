"""Keep the pinned MCP transport inside the controller's Linux kill scope."""
import os
from contextlib import asynccontextmanager


async def stop_server(process):
    """Stop this server; Host.close owns the final cleanup of every descendant."""
    import anyio
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    with anyio.move_on_after(2):
        await process.wait()
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


@asynccontextmanager
async def owned_stdio_client(parameters, *, errlog, job_name):
    import mcp.client.stdio as stdio
    if os.name == 'nt':
        async with stdio.stdio_client(parameters, errlog=errlog) as streams:
            yield streams
        return
    import anyio
    from importlib.metadata import version
    from agent_runtime.common import require
    from agent_runtime.processes import belongs_to_job
    require(version('mcp') == '2.2.0', 'transport', 'MCP process adapter requires the pinned transport')

    async def spawn(command, args, env=None, errlog=None, cwd=None):
        process = await anyio.open_process([command, *args], env=env, stderr=errlog,
                                          cwd=cwd, start_new_session=False)
        try:
            require(belongs_to_job(process.pid, job_name), 'job', 'MCP escaped controller process group')
        except BaseException:
            await stop_server(process)
            await process.aclose()
            raise
        return process

    # This bridge process has exactly one MCP connection. Retain the SDK's wire
    # protocol, framing, backpressure and bounded shutdown. Only adapt its spawn
    # and signal targets: a new SDK session would escape the outer controller.
    original_spawn = stdio._create_platform_compatible_process
    original_stop = stdio._terminate_process_tree
    stdio._create_platform_compatible_process = spawn
    stdio._terminate_process_tree = stop_server
    try:
        async with stdio.stdio_client(parameters, errlog=errlog) as streams:
            yield streams
    finally:
        stdio._create_platform_compatible_process = original_spawn
        stdio._terminate_process_tree = original_stop
