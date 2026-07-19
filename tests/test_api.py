#!/usr/bin/env python3
"""Integration tests for kcs HTTP API.

Usage:
  python tests/test_api.py                    # auto-start server on port 19999
  python tests/test_api.py --port 8888        # test an already-running server
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:{port}/api/v1"
PORT = 19999  # default port for tests

passed = 0
failed = 0
server_proc = None


def test(name: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  — {detail}")


def req(method: str, path: str, **kwargs):
    """Make a request and return (status_code, body)."""
    url = f"{BASE}{path}"
    try:
        r = requests.request(method, url, timeout=10, **kwargs)
        return r.status_code, (
            r.json()
            if r.headers.get("content-type", "").startswith("application/json")
            else r.text
        )
    except Exception as e:
        return None, str(e)


def ok(path: str, msg: str = ""):
    """Assert GET returns 200."""
    code, body = req("GET", path)
    test(f"GET {path}", code == 200, f"status={code} body={body} {msg}")


def ok_json(path: str, checks: dict | None = None, msg: str = ""):
    """Assert GET returns 200 and JSON body passes checks."""
    code, body = req("GET", path)
    ok_code = code == 200
    if not ok_code:
        test(f"GET {path} (200)", False, f"status={code}")
        return body
    if checks:
        for key, expected in checks.items():
            actual = body.get(key)
            cond = actual == expected
            test(f"GET {path} → {key}={expected}", cond, f"got {actual} {msg}")
    else:
        test(f"GET {path} (200 OK)", True)
    return body


def post_json(path: str, data: dict, expected_status: int = 201, msg: str = ""):
    """Assert POST returns expected_status."""
    code, body = req("POST", path, json=data)
    test(f"POST {path}", code == expected_status, f"status={code} body={body} {msg}")
    return body


# ── Test suites ─────────────────────────────────────────────────────────────────


def test_health():
    print("\n── health ──")
    ok("/health")


def test_status():
    print("\n── status ──")
    body = ok_json("/status")
    if body:
        test("  has server", "server" in body)
        test("  has workers", "workers" in body)
        test("  has containers", "containers" in body)
        test("  has images", "images" in body)
        test("  has nfs", "nfs" in body)


def test_nodes():
    print("\n── nodes ──")
    body = ok_json("/nodes")
    if body and "nodes" in body:
        test("  nodes is list", isinstance(body["nodes"], list))
        for n in body["nodes"]:
            test(f"  node {n.get('name','?')}", "name" in n and "status" in n)


def test_info():
    print("\n── info ──")
    body = ok_json("/info")
    if body:
        test("  has nodes", "nodes" in body)
        test("  has version", "version" in body)


def test_containers():
    print("\n── containers (read-only) ──")
    body = ok_json("/containers")
    containers = body.get("containers", []) if body else []

    if containers:
        test("  has containers", len(containers) > 0)

        name = containers[0]["name"]

        # GET single container
        code, _ = req("GET", f"/containers/{name}")
        test(f"GET /containers/{name}", code == 200, f"status={code}")

        # GET pods (depends on container name)
        code, _ = req("GET", f"/containers/{name}/pods")
        test(f"GET /containers/{name}/pods", code == 200, f"status={code}")

        # GET logs
        code, _ = req("GET", f"/containers/{name}/logs")
        test(f"GET /containers/{name}/logs", code == 200, f"status={code}")

        # POST exec
        post_json(f"/containers/{name}/exec", {"command": ["echo", "hello_test"]}, 200)
    else:
        test("  no existing containers (skip)", True)


def test_containers_lifecycle():
    """Create / stop / start / scale / delete a throwaway container."""
    print("\n── containers (lifecycle) ──")
    test_name = "kcs-test-throwaway"

    # Clean up if exists
    code, body = req("GET", f"/containers/{test_name}")
    if code == 200:
        req("DELETE", f"/containers/{test_name}?force=true")
        time.sleep(2)

    # Create
    code, body = req(
        "POST",
        "/containers",
        json={
            "image": "nginx:alpine",
            "name": test_name,
            "ports": [8080],
            "replicas": 1,
        },
    )
    test(
        f"POST /containers (create {test_name})",
        code in (200, 201),
        f"status={code} body={body}",
    )
    time.sleep(5)  # allow image pull

    # Verify running or pending
    code, body = req("GET", f"/containers/{test_name}")
    ok_create = code == 200 and body.get("status") in ("running", "pending")
    test(
        f"  container created (status={body.get('status') if body else '?'})",
        ok_create,
        f"status={code}",
    )

    # Stop
    code, body = req("POST", f"/containers/{test_name}/stop")
    test(f"POST .../stop", code == 200, f"status={code}")
    time.sleep(3)

    # Start
    code, body = req("POST", f"/containers/{test_name}/start")
    test(f"POST .../start", code == 200, f"status={code}")
    time.sleep(3)

    # Scale
    code, body = req("POST", f"/containers/{test_name}/scale", json={"replicas": 1})
    test(f"POST .../scale", code == 200, f"status={code}")
    time.sleep(2)

    # Delete
    code, body = req("DELETE", f"/containers/{test_name}?force=true")
    test(f"DELETE .../{test_name}", code == 200, f"status={code}")
    time.sleep(2)

    # Verify gone
    code, _ = req("GET", f"/containers/{test_name}")
    test(f"  container gone after delete", code == 404, f"status={code}")


def test_mcp_tools():
    """Verify MCP tool schemas in pinned and unpinned mode."""
    print("\n── mcp (tool schemas) ──")

    import importlib

    import kcs.mcp as mcp

    # Mode 1: no default container → container param required
    if "KCS_CONTAINER" in os.environ:
        del os.environ["KCS_CONTAINER"]
    importlib.reload(mcp)
    tools = mcp._tool_schemas()
    exec_tool = next(t for t in tools if t.name == "container_exec")
    test(
        "  unpinned: container in required",
        "container" in exec_tool.inputSchema["required"],
    )
    test(
        "  unpinned: container in properties",
        "container" in exec_tool.inputSchema["properties"],
    )

    read_tool = next(t for t in tools if t.name == "container_read")
    test(
        "  unpinned: read requires container",
        "container" in read_tool.inputSchema["required"],
    )

    # Mode 2: pinned to a container → container param hidden
    os.environ["KCS_CONTAINER"] = "web"
    importlib.reload(mcp)
    tools = mcp._tool_schemas()
    exec_tool = next(t for t in tools if t.name == "container_exec")
    test(
        "  pinned: container NOT in required",
        "container" not in exec_tool.inputSchema["required"],
    )
    test(
        "  pinned: container NOT in properties",
        "container" not in exec_tool.inputSchema["properties"],
    )
    test("  pinned: description mentions container", "web" in exec_tool.description)

    write_tool = next(t for t in tools if t.name == "container_write")
    test(
        "  pinned: write requires only path+content",
        write_tool.inputSchema["required"] == ["path", "content"],
    )

    del os.environ["KCS_CONTAINER"]


def test_mcp_http():
    """End-to-end MCP over HTTP SSE."""
    print("\n── mcp (HTTP SSE) ──")

    import asyncio
    import json as _json
    import queue

    test_name = "kcs-test-mcp"
    MCP_PORT = _find_free_port()

    # Clean up leftover container
    code, body = req("GET", f"/containers/{test_name}")
    if code == 200:
        req("DELETE", f"/containers/{test_name}?force=true")
        time.sleep(2)

    # Create test container
    code, body = req(
        "POST",
        "/containers",
        json={
            "image": "nginx:alpine",
            "name": test_name,
            "ports": [8080],
        },
    )
    test(f"  create container", code in (200, 201), f"status={code}")
    time.sleep(5)

    # Verify container running
    code, body = req("GET", f"/containers/{test_name}")
    if code != 200 or body.get("status") not in ("running", "pending"):
        test("  container ready", False, f"status={code} body={body}")
        return

    # Start MCP server subprocess
    env = os.environ.copy()
    env["KCS_API"] = f"http://localhost:{PORT}/api/v1"
    env["KCS_CONTAINER"] = test_name
    mcp_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kcs",
            "mcp",
            "--container",
            test_name,
            "--mcp-port",
            str(MCP_PORT),
            "--host",
            "127.0.0.1",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    if mcp_proc.poll() is not None:
        test("  MCP server start", False, f"exited with {mcp_proc.returncode}")
        req("DELETE", f"/containers/{test_name}?force=true")
        return
    test("  MCP server started", True)

    # Run async SSE test
    async def _run_sse():
        import httpx

        events = queue.Queue()
        sid = None

        async with httpx.AsyncClient(timeout=15) as client:
            async with client.stream("GET", f"http://127.0.0.1:{MCP_PORT}/sse") as sse:

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
                                    events.put(_json.loads(d))
                                except Exception:
                                    pass

                task = asyncio.create_task(reader())

                # Wait for session
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

                msg_url = f"http://127.0.0.1:{MCP_PORT}/messages/?session_id={sid}"

                async def rpc(method, params=None):
                    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
                    if params:
                        payload["params"] = params
                    await client.post(msg_url, json=payload)
                    for _ in range(200):
                        try:
                            ev = events.get(timeout=0.1)
                            if "result" in ev or "error" in ev:
                                return ev
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                    return None

                # Initialize
                r = await rpc(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                if not r or "result" not in r:
                    task.cancel()
                    return f"init: {r}"

                await client.post(
                    msg_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                # Tools list
                r = await rpc("tools/list")
                if not r or "result" not in r:
                    task.cancel()
                    return f"tools/list: {r}"
                tools = [t["name"] for t in r["result"]["tools"]]

                # Exec
                r = await rpc(
                    "tools/call",
                    {
                        "name": "container_exec",
                        "arguments": {"command": "echo mcp-test-ok"},
                    },
                )
                if not r or "result" not in r:
                    task.cancel()
                    return f"exec: {r}"
                exec_out = r["result"]["content"][0]["text"]

                # Write + Read
                await rpc(
                    "tools/call",
                    {
                        "name": "container_write",
                        "arguments": {
                            "path": "/tmp/mcp-test.txt",
                            "content": "mcp data\n",
                        },
                    },
                )
                r = await rpc(
                    "tools/call",
                    {
                        "name": "container_read",
                        "arguments": {"path": "/tmp/mcp-test.txt"},
                    },
                )
                read_out = r["result"]["content"][0]["text"] if r else ""

                task.cancel()
                return {
                    "tools": tools,
                    "exec": exec_out,
                    "read": read_out,
                }

    try:
        result = asyncio.run(_run_sse())
    except Exception as e:
        result = f"exception: {e}"

    # Verify results
    if isinstance(result, dict):
        test("  tools listed", "container_exec" in result["tools"])
        test(
            "  exec works",
            "mcp-test-ok" in result["exec"],
            f"got: {result['exec'][:50]}",
        )
        test(
            "  read works", "mcp data" in result["read"], f"got: {result['read'][:50]}"
        )
    else:
        test("  SSE flow", False, f"error: {str(result)[:100]}")

    # Cleanup
    mcp_proc.terminate()
    mcp_proc.wait(timeout=5)
    req("DELETE", f"/containers/{test_name}?force=true")
    time.sleep(2)


def test_mcp_api():
    """Start / stop MCP server through the HTTP API."""
    print("\n── mcp (API management) ──")

    import asyncio

    mcp_port = _find_free_port()

    # List — should be empty to start
    code, body = req("GET", "/mcp")
    test(
        "  list empty",
        code == 200 and body.get("servers") == [],
        f"status={code} body={body}",
    )

    # Start
    code, body = req("POST", "/mcp/start", json={"port": mcp_port})
    test("  start", code == 201, f"status={code} body={body}")

    # List — should show running
    code, body = req("GET", "/mcp")
    servers = body.get("servers", []) if body else []
    test(
        "  list shows running",
        any(s["port"] == mcp_port for s in servers),
        f"servers={servers}",
    )

    # Verify SSE endpoint responds
    async def _check_sse():
        import httpx

        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream("GET", f"http://127.0.0.1:{mcp_port}/sse") as sse:
                async for line in sse.aiter_lines():
                    if "session_id=" in line:
                        return True
        return False

    try:
        ok = asyncio.run(_check_sse())
    except Exception:
        ok = False
    test("  SSE endpoint alive", ok)

    # Stop
    code, body = req("POST", f"/mcp/stop?port={mcp_port}")
    test("  stop", code == 200, f"status={code} body={body}")

    # Stop again — should 404
    code, body = req("POST", f"/mcp/stop?port={mcp_port}")
    test("  stop again → 404", code == 404, f"status={code} body={body}")


def _find_free_port():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_containers_resources():
    """Create container with cpu/memory resource declarations, verify spec."""
    print("\n── containers (resources) ──")
    test_name = "kcs-test-resources"

    # Clean up if exists
    code, body = req("GET", f"/containers/{test_name}")
    if code == 200:
        req("DELETE", f"/containers/{test_name}?force=true")
        time.sleep(2)

    # Create with resource declarations
    code, body = req(
        "POST",
        "/containers",
        json={
            "image": "nginx:alpine",
            "name": test_name,
            "ports": [8080],
            "replicas": 1,
            "cpu": "250m",
            "memory": "128Mi",
        },
    )
    test(
        f"POST /containers (create {test_name} with resources)",
        code in (200, 201),
        f"status={code} body={body}",
    )
    time.sleep(5)

    # Verify container detail includes resources
    code, body = req("GET", f"/containers/{test_name}")
    ok_detail = code == 200
    test(f"GET .../{test_name} (with resources)", ok_detail, f"status={code}")

    if ok_detail and body:
        res = body.get("resources", {})
        test("  has resources field", bool(res), f"got {res}")
        if res:
            reqs = res.get("requests", {})
            limits = res.get("limits", {})
            test(
                "  requests.cpu = 250m",
                reqs.get("cpu") == "250m",
                f"got {reqs.get('cpu')}",
            )
            test(
                "  requests.memory = 128Mi",
                reqs.get("memory") == "128Mi",
                f"got {reqs.get('memory')}",
            )
            test(
                "  limits.cpu = 250m",
                limits.get("cpu") == "250m",
                f"got {limits.get('cpu')}",
            )
            test(
                "  limits.memory = 128Mi",
                limits.get("memory") == "128Mi",
                f"got {limits.get('memory')}",
            )

    # Verify via kubectl the pod spec has correct resources
    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kcs/k3s.yaml")
    r = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-l",
            f"app={test_name}",
            "-o",
            "jsonpath={.items[0].spec.containers[0].resources}",
            "--kubeconfig",
            kubeconfig,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    pod_has_cpu = "250m" in r.stdout
    pod_has_mem = "128Mi" in r.stdout
    test("  pod spec has cpu=250m", pod_has_cpu, f"got {r.stdout[:200]}")
    test("  pod spec has memory=128Mi", pod_has_mem, f"got {r.stdout[:200]}")

    # Delete
    code, body = req("DELETE", f"/containers/{test_name}?force=true")
    test(f"DELETE .../{test_name}", code == 200, f"status={code}")
    time.sleep(2)

    # Verify gone
    code, _ = req("GET", f"/containers/{test_name}")
    test(f"  container gone after delete", code == 404, f"status={code}")


# ── Main ────────────────────────────────────────────────────────────────────────


def start_server(port: int):
    """Start kcs-server as a subprocess."""
    global server_proc

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "kcs.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    log_path = f"/tmp/kcs-test-{port}.log"
    log_fp = open(log_path, "w")

    server_proc = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=Path(__file__).resolve().parent.parent,
        preexec_fn=os.setsid if sys.platform != "win32" else None,
    )
    print(f"Server PID: {server_proc.pid}  (log: {log_path})")

    # Wait for ready
    timeout = 30
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=2)
            if r.status_code == 200:
                print(f"Server ready after {time.time() - start:.1f}s\n")
                return True
        except Exception:
            pass
        if server_proc.poll() is not None:
            print(f"Server exited with code {server_proc.returncode}")
            return False
        time.sleep(0.5)
    print(f"Server did not start within {timeout}s")
    return False


def stop_server():
    global server_proc
    if server_proc is None:
        return
    try:
        os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
    except Exception:
        pass
    try:
        server_proc.wait(timeout=5)
    except Exception:
        server_proc.kill()
    server_proc = None


def main():
    global BASE, PORT, passed, failed

    PORT = _find_free_port()
    BASE = BASE.format(port=PORT)

    print(f"{'='*60}")
    print(f"kcs API test  ·  port={PORT}")
    print(f"{'='*60}")

    if not start_server(PORT):
        sys.exit(1)

    try:
        test_health()
        test_status()
        test_nodes()
        test_info()
        test_containers()
        test_containers_lifecycle()
        test_containers_resources()
        test_mcp_tools()
        test_mcp_http()
        test_mcp_api()
    finally:
        stop_server()
        print("\nServer stopped.")

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} FAILED")
    else:
        print(" ✓ all pass")
    print(f"{'='*60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
