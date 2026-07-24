"""MCP server tests — tool schemas, HTTP SSE, API management."""

import asyncio
import importlib
import json
import os
import queue
import subprocess
import sys
import time


def _find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(s):
    _test_tool_schemas(s)
    _test_http_sse(s)
    _test_api_management(s)


def _test_tool_schemas(s):
    print("\n── mcp (tool schemas) ──")
    import kcs.mcp as mcp

    if "KCS_CONTAINER" in os.environ:
        del os.environ["KCS_CONTAINER"]
    importlib.reload(mcp)
    tools = mcp._tool_schemas()
    exec_tool = next(t for t in tools if t.name == "container_exec")
    s.test("  unpinned: container in required",
           "container" in exec_tool.inputSchema["required"])
    s.test("  unpinned: container in properties",
           "container" in exec_tool.inputSchema["properties"])
    read_tool = next(t for t in tools if t.name == "container_read")
    s.test("  unpinned: read requires container",
           "container" in read_tool.inputSchema["required"])

    os.environ["KCS_CONTAINER"] = "web"
    importlib.reload(mcp)
    tools = mcp._tool_schemas()
    exec_tool = next(t for t in tools if t.name == "container_exec")
    s.test("  pinned: container NOT in required",
           "container" not in exec_tool.inputSchema["required"])
    s.test("  pinned: container NOT in properties",
           "container" not in exec_tool.inputSchema["properties"])
    s.test("  pinned: description mentions container",
           "web" in exec_tool.description)
    write_tool = next(t for t in tools if t.name == "container_write")
    s.test("  pinned: write requires only path+content",
           write_tool.inputSchema["required"] == ["path", "content"])

    del os.environ["KCS_CONTAINER"]


def _test_http_sse(s):
    print("\n── mcp (HTTP SSE) ──")
    name = "kcs-test-mcp"
    mcp_port = _find_free_port()

    code, body = s.req("GET", f"/containers/{name}")
    if code == 200:
        s.req("DELETE", f"/containers/{name}?force=true")
        time.sleep(2)

    code, body = s.req("POST", "/containers", json={
        "image": "nginx:alpine", "name": name, "ports": [8080],
    })
    s.test("  create container", code in (200, 201), f"status={code}")
    time.sleep(5)

    code, body = s.req("GET", f"/containers/{name}")
    if code != 200 or body.get("status") not in ("running", "pending"):
        s.test("  container ready", False, f"status={code}")
        return

    env = os.environ.copy()
    env["KCS_API"] = f"http://localhost:{s.port}/api/v1"
    env["KCS_CONTAINER"] = name
    mcp_proc = subprocess.Popen(
        [sys.executable, "-m", "kcs", "mcp", "--container", name,
         "--mcp-port", str(mcp_port), "--host", "127.0.0.1"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    if mcp_proc.poll() is not None:
        s.test("  MCP server start", False, f"exited with {mcp_proc.returncode}")
        s.req("DELETE", f"/containers/{name}?force=true")
        return
    s.test("  MCP server started", True)

    async def _run():
        import httpx
        events = queue.Queue()
        sid = None

        async with httpx.AsyncClient(timeout=15) as client:
            async with client.stream("GET",
                                     f"http://127.0.0.1:{mcp_port}/sse") as sse:
                async def reader():
                    nonlocal sid
                    async for line in sse.aiter_lines():
                        if line.startswith("data: "):
                            d = line[6:]
                            if sid is None and "session_id=" in d:
                                sid = d.split("session_id=")[1]
                                events.put({"__s": sid})
                            else:
                                try:
                                    events.put(json.loads(d))
                                except Exception:
                                    pass

                task = asyncio.create_task(reader())

                for _ in range(100):
                    try:
                        ev = events.get(timeout=0.1)
                        if "__s" in ev:
                            sid = ev["__s"]
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)

                if not sid:
                    task.cancel()
                    return "no_session"

                url = f"http://127.0.0.1:{mcp_port}/messages/?session_id={sid}"

                async def rpc(method, params=None):
                    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
                    if params: payload["params"] = params
                    await client.post(url, json=payload)
                    for _ in range(200):
                        try:
                            ev = events.get(timeout=0.1)
                            if "result" in ev or "error" in ev:
                                return ev
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                    return None

                r = await rpc("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"}
                })
                if not r or "result" not in r:
                    task.cancel()
                    return f"init: {r}"

                await client.post(url, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized"})

                r = await rpc("tools/list")
                if not r or "result" not in r:
                    task.cancel()
                    return f"tools/list: {r}"
                tools = [t["name"] for t in r["result"]["tools"]]

                r = await rpc("tools/call", {
                    "name": "container_exec",
                    "arguments": {"command": "echo mcp-test-ok"}})
                if not r or "result" not in r:
                    task.cancel()
                    return f"exec: {r}"
                exec_out = r["result"]["content"][0]["text"]

                await rpc("tools/call", {
                    "name": "container_write",
                    "arguments": {"path": "/tmp/mcp-test.txt",
                                  "content": "mcp data\n"}})
                r = await rpc("tools/call", {
                    "name": "container_read",
                    "arguments": {"path": "/tmp/mcp-test.txt"}})
                read_out = r["result"]["content"][0]["text"] if r else ""

                task.cancel()
                return {"tools": tools, "exec": exec_out, "read": read_out}

    try:
        result = asyncio.run(_run())
    except Exception as e:
        result = f"exception: {e}"

    if isinstance(result, dict):
        s.test("  tools listed", "container_exec" in result["tools"])
        s.test("  exec works", "mcp-test-ok" in result["exec"],
               f"got: {result['exec'][:50]}")
        s.test("  read works", "mcp data" in result["read"],
               f"got: {result['read'][:50]}")
    else:
        s.test("  SSE flow", False, f"error: {str(result)[:100]}")

    mcp_proc.terminate()
    mcp_proc.wait(timeout=5)
    s.req("DELETE", f"/containers/{name}?force=true")
    time.sleep(2)


def _test_api_management(s):
    print("\n── mcp (API management) ──")
    import asyncio

    mcp_port = _find_free_port()

    code, body = s.req("GET", "/mcp")
    s.test("  list empty", code == 200 and body.get("servers") == [],
           f"status={code} body={body}")

    code, body = s.req("POST", "/mcp/start", json={"port": mcp_port})
    s.test("  start", code == 201, f"status={code} body={body}")

    code, body = s.req("GET", "/mcp")
    servers = body.get("servers", []) if body else []
    s.test("  list shows running", any(sv["port"] == mcp_port for sv in servers),
           f"servers={servers}")

    async def _check():
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream("GET",
                                     f"http://127.0.0.1:{mcp_port}/sse") as sse:
                async for line in sse.aiter_lines():
                    if "session_id=" in line:
                        return True
        return False

    try:
        ok = asyncio.run(_check())
    except Exception:
        ok = False
    s.test("  SSE endpoint alive", ok)

    code, body = s.req("POST", f"/mcp/stop?port={mcp_port}")
    s.test("  stop", code == 200, f"status={code} body={body}")

    code, body = s.req("POST", f"/mcp/stop?port={mcp_port}")
    s.test("  stop again -> 404", code == 404, f"status={code} body={body}")
