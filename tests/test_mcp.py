"""MCP server tests — tool schemas, HTTP SSE, API management."""

import asyncio
import importlib
import json
import os
import queue
import socket
import subprocess
import sys
import time

import httpx
import pytest
import requests


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ══════════════════════════════════════════════════════════════════════════════
# Tool schema tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_kcs_container_env():
    """Ensure KCS_CONTAINER is unset before and after each tool-schema test."""
    old = os.environ.pop("KCS_CONTAINER", None)
    importlib.reload(__import__("kcs.mcp", fromlist=["_tool_schemas"]))
    yield
    if old is not None:
        os.environ["KCS_CONTAINER"] = old
    else:
        os.environ.pop("KCS_CONTAINER", None)
    importlib.reload(__import__("kcs.mcp", fromlist=["_tool_schemas"]))


class TestToolSchemas:

    @staticmethod
    def _tools():
        import kcs.mcp as mcp
        return mcp._tool_schemas()

    def test_unpinned_requires_container(self):
        tools = self._tools()
        exec_tool = next(t for t in tools if t.name == "container_exec")
        assert "container" in exec_tool.inputSchema["required"]
        assert "container" in exec_tool.inputSchema["properties"]

    def test_unpinned_read_requires_container(self):
        tools = self._tools()
        read_tool = next(t for t in tools if t.name == "container_read")
        assert "container" in read_tool.inputSchema["required"]

    def test_pinned_hides_container_param(self):
        os.environ["KCS_CONTAINER"] = "web"
        importlib.reload(__import__("kcs.mcp", fromlist=["_tool_schemas"]))
        exec_tool = next(t for t in self._tools()
                         if t.name == "container_exec")
        assert "container" not in exec_tool.inputSchema["required"]
        assert "container" not in exec_tool.inputSchema["properties"]

    def test_pinned_description_mentions_container(self):
        os.environ["KCS_CONTAINER"] = "web"
        importlib.reload(__import__("kcs.mcp", fromlist=["_tool_schemas"]))
        exec_tool = next(t for t in self._tools()
                         if t.name == "container_exec")
        assert "web" in exec_tool.description

    def test_pinned_write_only_needs_path_and_content(self):
        os.environ["KCS_CONTAINER"] = "web"
        importlib.reload(__import__("kcs.mcp", fromlist=["_tool_schemas"]))
        write_tool = next(t for t in self._tools()
                          if t.name == "container_write")
        assert write_tool.inputSchema["required"] == ["path", "content"]


# ══════════════════════════════════════════════════════════════════════════════
# SSE integration tests
# ══════════════════════════════════════════════════════════════════════════════


async def _sse_flow(port: int) -> dict:
    """Run a full MCP session: initialize → tools/list → exec → write → read."""
    events: queue.Queue[dict] = queue.Queue()
    sid = None

    async with httpx.AsyncClient(timeout=15) as client:
        async with client.stream("GET",
                                 f"http://127.0.0.1:{port}/sse") as sse:
            async def _reader():
                nonlocal sid
                async for line in sse.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    d = line[6:]
                    if sid is None and "session_id=" in d:
                        sid = d.split("session_id=")[1]
                        events.put({"__sid": sid})
                        continue
                    try:
                        events.put(json.loads(d))
                    except (json.JSONDecodeError, ValueError):
                        pass

            task = asyncio.create_task(_reader())

            # Wait for session ID
            for _ in range(100):
                try:
                    ev = events.get(timeout=0.1)
                    if "__sid" in ev:
                        sid = ev["__sid"]
                        break
                except queue.Empty:
                    pass
                await asyncio.sleep(0.05)
            assert sid, "no session_id received"

            url = f"http://127.0.0.1:{port}/messages/?session_id={sid}"

            async def rpc(method, params=None):
                payload = {"jsonrpc": "2.0", "id": 1, "method": method}
                if params:
                    payload["params"] = params
                await client.post(url, json=payload)
                for _ in range(200):
                    try:
                        ev = events.get(timeout=0.1)
                        if "result" in ev or "error" in ev:
                            return ev
                    except queue.Empty:
                        pass
                    await asyncio.sleep(0.05)
                return None

            # Initialize
            r = await rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            })
            assert r and "result" in r, f"init failed: {r}"

            await client.post(url, json={
                "jsonrpc": "2.0", "method": "notifications/initialized"})

            # Tools
            tools_r = await rpc("tools/list")
            assert tools_r and "result" in tools_r, f"tools/list failed: {tools_r}"

            # Exec
            exec_r = await rpc("tools/call", {
                "name": "container_exec",
                "arguments": {"command": "echo mcp-test-ok"},
            })
            assert exec_r and "result" in exec_r, f"exec failed: {exec_r}"

            # Write
            await rpc("tools/call", {
                "name": "container_write",
                "arguments": {"path": "/tmp/mcp-test.txt",
                              "content": "mcp data\n"},
            })

            # Read
            read_r = await rpc("tools/call", {
                "name": "container_read",
                "arguments": {"path": "/tmp/mcp-test.txt"},
            })

            task.cancel()
            return {
                "tools": [t["name"] for t in tools_r["result"]["tools"]],
                "exec": exec_r["result"]["content"][0]["text"],
                "read": read_r["result"]["content"][0]["text"]
                if read_r else "",
            }


@pytest.fixture(scope="module")
def mcp_sse(api):
    """Start an MCP server subprocess for SSE tests, clean up after module."""
    name = "kcs-test-mcp-sse"
    port = _free_port()

    # Clean up stale container
    r = requests.get(f"{api}/containers/{name}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{name}?force=true")
        time.sleep(2)

    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": name, "ports": [8080],
    })
    assert r.status_code in (200, 201)
    time.sleep(5)

    r = requests.get(f"{api}/containers/{name}")
    if r.status_code != 200 or r.json().get("status") not in (
            "running", "pending"):
        requests.delete(f"{api}/containers/{name}?force=true")
        pytest.skip("container not ready")

    env = os.environ.copy()
    env["KCS_API"] = api
    env["KCS_CONTAINER"] = name
    proc = subprocess.Popen(
        [sys.executable, "-m", "kcs", "mcp", "--container", name,
         "--mcp-port", str(port), "--host", "127.0.0.1"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    assert proc.poll() is None, "MCP process exited"

    yield port

    proc.terminate()
    proc.wait(timeout=5)
    requests.delete(f"{api}/containers/{name}?force=true")


@pytest.mark.asyncio
async def test_sse_full_flow(mcp_sse):
    """One SSE session exercises tools/list, exec, write, and read."""
    result = await _sse_flow(mcp_sse)

    assert "container_exec" in result["tools"], \
        f"tools: {result['tools']}"
    assert "mcp-test-ok" in result["exec"], \
        f"exec output: {result['exec'][:80]}"
    assert "mcp data" in result["read"], \
        f"read output: {result['read'][:80]}"


# ══════════════════════════════════════════════════════════════════════════════
# API management tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def mcp_api(api):
    """Clean slate: stop any leftover MCP servers before testing."""
    r = requests.get(f"{api}/mcp")
    for s in r.json().get("servers", []):
        requests.post(f"{api}/mcp/stop?port={s['port']}")
    return api


def test_mcp_list_empty(mcp_api):
    r = requests.get(f"{mcp_api}/mcp")
    assert r.status_code == 200
    assert r.json()["servers"] == []


def test_mcp_start_and_verify(mcp_api):
    """Start an MCP server via API, verify port is live, then stop."""
    port = _free_port()
    r = requests.post(f"{mcp_api}/mcp/start", json={"port": port})
    assert r.status_code == 201, r.text

    r = requests.get(f"{mcp_api}/mcp")
    assert any(s["port"] == port for s in r.json()["servers"])

    # Check port connected to a listener
    deadline = time.time() + 5
    alive = False
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            alive = True
            break
        except OSError:
            time.sleep(0.2)
    assert alive, "MCP server port not listening"

    r = requests.post(f"{mcp_api}/mcp/stop?port={port}")
    assert r.status_code == 200


def test_mcp_stop_nonexistent(mcp_api):
    r = requests.post(f"{mcp_api}/mcp/stop?port=19998")
    assert r.status_code == 404
