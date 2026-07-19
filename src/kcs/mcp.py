"""MCP (Model Context Protocol) server for kcs — coding-agent integration.

Start with:  kcs mcp --container <name>
Or directly: python -m kcs.mcp

Connect Claude Code by adding to ~/.claude/claude.json:

    "mcpServers": { "kcs": { "url": "http://127.0.0.1:9999/sse" } }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import requests
from mcp.server import Server
from mcp.types import TextContent, Tool

log = logging.getLogger("kcs.mcp")
KCS_API = os.environ.get("KCS_API", "http://localhost:8000/api/v1")
DEFAULT_CONTAINER = os.environ.get("KCS_CONTAINER", "")

# Persistent shell sessions keyed by container name
_sessions: dict[str, str] = {}

server = Server("kcs")


def _get_container(args: dict) -> str:
    """Resolve container name from args or default."""
    c = args.get("container", "").strip()
    return c or DEFAULT_CONTAINER


def _api(path: str, method: str = "GET", json_data=None, params=None):
    """Call the kcs API server."""
    url = f"{KCS_API}{path}"
    r = requests.request(method, url, json=json_data, params=params, timeout=30)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text[:200])
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"kcs API error {r.status_code}: {detail}")
    return r.json()


def _get_or_create_session(container: str) -> str:
    """Return (or create) a persistent shell session for the container."""
    if container not in _sessions:
        result = _api(f"/containers/{container}/shell/sessions", method="POST")
        _sessions[container] = result["session_id"]
    try:
        # Validate session is still alive with a no-op
        _api(
            f"/containers/{container}/shell/sessions/{_sessions[container]}/exec",
            method="POST",
            json_data={"command": ["true"]},
        )
    except Exception:
        # Session expired — recreate
        result = _api(f"/containers/{container}/shell/sessions", method="POST")
        _sessions[container] = result["session_id"]
    return _sessions[container]


def _exec_in_container(container: str, command: str) -> dict:
    """Run a command in a persistent shell session. Returns {stdout, exit_code}."""
    sid = _get_or_create_session(container)
    return _api(
        f"/containers/{container}/shell/sessions/{sid}/exec",
        method="POST",
        json_data={"command": command.split()},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════════════════════


def _tool_schemas() -> list[Tool]:
    """Build tool list.  When DEFAULT_CONTAINER is set the container param is
    omitted so the LLM sees a cleaner interface with no irrelevant fields."""
    pinned = bool(DEFAULT_CONTAINER)
    ctx = f" (target: {DEFAULT_CONTAINER})" if pinned else ""

    container_prop = (
        {}
        if pinned
        else {
            "container": {
                "type": "string",
                "description": "Container name to operate on.",
            },
        }
    )

    def _props(**extra):
        return {**container_prop, **extra}

    return [
        Tool(
            name="container_list",
            description="List all containers in the kcs cluster.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="container_exec",
            description=f"Execute a shell command inside a container{ctx}. "
            "Uses a persistent session — working directory and "
            "environment variables are preserved between calls.",
            inputSchema={
                "type": "object",
                "properties": _props(
                    command={
                        "type": "string",
                        "description": "Shell command to run. Pipelines and compound commands are fine.",
                    }
                ),
                "required": ([] if pinned else ["container"]) + ["command"],
            },
        ),
        Tool(
            name="container_read",
            description=f"Read the contents of a file inside a container{ctx}.",
            inputSchema={
                "type": "object",
                "properties": _props(
                    path={
                        "type": "string",
                        "description": "Absolute path to the file inside the container.",
                    }
                ),
                "required": ([] if pinned else ["container"]) + ["path"],
            },
        ),
        Tool(
            name="container_write",
            description=f"Write content to a file inside a container{ctx}. "
            "Creates parent directories as needed.",
            inputSchema={
                "type": "object",
                "properties": _props(
                    path={
                        "type": "string",
                        "description": "Absolute path to the file inside the container.",
                    },
                    content={
                        "type": "string",
                        "description": "Content to write to the file.",
                    },
                ),
                "required": ([] if pinned else ["container"]) + ["path", "content"],
            },
        ),
    ]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _tool_schemas()


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "container_list":
            data = _api("/containers")
            containers = data.get("containers", [])
            if not containers:
                return [TextContent(type="text", text="No containers found.")]
            # Return structured JSON so the LLM can easily parse and act on it
            summary = [
                {
                    "name": c["name"],
                    "status": c["status"],
                    "image": c["image"],
                    "replicas": c["replicas"],
                    "age": c["age"],
                }
                for c in containers
            ]
            return [TextContent(type="text", text=json.dumps(summary, indent=2))]

        elif name == "container_exec":
            container = _get_container(arguments)
            if not container:
                return [
                    TextContent(
                        type="text",
                        text="Error: no container specified and no default set. Start with: kcs mcp --container <name>",
                    )
                ]
            command = arguments["command"]
            result = _exec_in_container(container, command)
            text = result.get("stdout", "")
            if result.get("exit_code", 0) != 0:
                text += f"\n[exit code: {result['exit_code']}]"
            return [TextContent(type="text", text=text or "(no output)")]

        elif name == "container_read":
            container = _get_container(arguments)
            if not container:
                return [
                    TextContent(
                        type="text",
                        text="Error: no container specified. Start with: kcs mcp --container <name>",
                    )
                ]
            path = arguments["path"]
            result = _exec_in_container(container, f"cat {path}; echo EXIT:$?")
            out = result.get("stdout", "")
            if "EXIT:0" not in out:
                return [
                    TextContent(
                        type="text",
                        text=f"Error reading {path}: {out.replace('EXIT:1', '').strip() or 'file not found'}",
                    )
                ]
            # Remove the EXIT marker line
            out = out.rsplit("EXIT:0", 1)[0].rstrip("\n")
            return [TextContent(type="text", text=out)]

        elif name == "container_write":
            import base64

            container = _get_container(arguments)
            if not container:
                return [
                    TextContent(
                        type="text",
                        text="Error: no container specified. Start with: kcs mcp --container <name>",
                    )
                ]
            path = arguments["path"]
            content = arguments["content"]
            encoded = base64.b64encode(content.encode()).decode()
            result = _exec_in_container(
                container,
                f"mkdir -p $(dirname {path}) && echo {encoded} | base64 -d > {path} && echo OK",
            )
            if "OK" not in result.get("stdout", ""):
                return [
                    TextContent(
                        type="text",
                        text=f"Error writing {path}: {result.get('stdout', '')}",
                    )
                ]
            return [
                TextContent(type="text", text=f"Wrote {len(content)} bytes to {path}")
            ]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


def create_app():
    """Build a Starlette ASGI app for the MCP server."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


# ── In-process server management ──────────────────────────────────────────

_running: dict[int, asyncio.Task[None]] = {}


def start(host: str = "127.0.0.1", port: int = 9999) -> None:
    """Start the MCP server in a background thread."""
    import uvicorn

    if port in _running:
        raise RuntimeError(f"MCP server already running on port {port}")

    app = create_app()
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    srv = uvicorn.Server(cfg)

    loop = asyncio.new_event_loop()
    task = loop.create_task(srv.serve())

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    t = __import__("threading").Thread(target=_run, daemon=True)
    t.start()
    _running[port] = task


def stop(port: int) -> None:
    """Stop a background MCP server."""
    task = _running.pop(port, None)
    if task is None:
        raise RuntimeError(f"No MCP server on port {port}")
    task.cancel()


def list_running() -> list[int]:
    """Return ports of all running MCP servers."""
    return sorted(_running.keys())


def main(host: str = "127.0.0.1", port: int = 9999):
    """Run the MCP server over HTTP (SSE transport) — standalone, blocking."""
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
