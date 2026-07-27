"""Shell proxy tests — wrapper generation, TCP server, API management."""

import json
import os
import socket
import subprocess
import sys
import time

import pytest
import requests

from kcs.shell_proxy import _ensure_wrapper, _wrapper_path

_NAME = "kcs-test-shell-proxy"
_PORT_API = 19876
_PORT_FWD = 19877


# ══════════════════════════════════════════════════════════════════════════════
# Shared fixture
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def proxy_target(api):
    """Create a throwaway container for proxy tests; clean up after."""
    r = requests.get(f"{api}/containers/{_NAME}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{_NAME}?force=true")
        time.sleep(2)

    r = requests.post(
        f"{api}/containers",
        json={
            "image": "nginx:alpine",
            "name": _NAME,
            "ports": [8080],
        },
    )
    assert r.status_code in (200, 201)
    time.sleep(5)

    r = requests.get(f"{api}/containers/{_NAME}")
    if r.status_code != 200 or r.json().get("status") not in ("running", "pending"):
        requests.delete(f"{api}/containers/{_NAME}?force=true")
        pytest.skip("container not ready")

    yield _NAME

    # Clean up
    requests.post(f"{api}/shell-proxy/stop?port={_PORT_API}")
    requests.post(f"{api}/shell-proxy/stop?port={_PORT_FWD}")
    requests.delete(f"{api}/containers/{_NAME}?force=true")


# ══════════════════════════════════════════════════════════════════════════════
# Unit — wrapper path and content
# ══════════════════════════════════════════════════════════════════════════════


def test_wrapper_path_contains_bash():
    """Claude Code only calls CLAUDE_CODE_SHELL if the path contains 'bash'."""
    path = _wrapper_path("test-container")
    assert "bash" in path, f"path must contain 'bash': {path}"


def test_wrapper_is_valid_bash():
    """The wrapper must pass bash -n (syntax check)."""
    path = _ensure_wrapper("test-container", 19999)
    result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    assert result.returncode == 0, f"bash syntax error: {result.stderr}"


def test_wrapper_executable():
    """The wrapper must be +x."""
    path = _ensure_wrapper("test-container", 19999)
    assert os.access(path, os.X_OK), f"not executable: {path}"


def test_wrapper_shebang_is_bash():
    """CLAUDE_CODE_SHELL requires a bash shebang."""
    path = _ensure_wrapper("test-container", 19999)
    with open(path) as f:
        line = f.readline()
    assert line.startswith("#!/bin/bash"), f"bad shebang: {line.strip()}"


def test_wrapper_idempotent():
    """Calling _ensure_wrapper twice returns the same path."""
    a = _ensure_wrapper("test-container", 19999)
    b = _ensure_wrapper("test-container", 19999)
    assert a == b


def test_wrapper_fallback_local():
    """Commands without 'eval' run locally via /bin/bash."""
    wrapper = _ensure_wrapper("test-container", 19999)
    proc = subprocess.run(
        [wrapper, "-c", "echo LOCAL_ONLY"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "LOCAL_ONLY" in proc.stdout


# ══════════════════════════════════════════════════════════════════════════════
# Integration — API management
# ══════════════════════════════════════════════════════════════════════════════


class TestShellProxyAPI:
    """Start / list / stop shell proxies via the HTTP API."""

    def test_start_and_list(self, api, proxy_target):
        r = requests.post(
            f"{api}/shell-proxy/start",
            json={"container": proxy_target, "port": _PORT_API},
        )
        assert r.status_code == 201, r.text
        result = r.json()
        assert result["port"] == _PORT_API
        assert result["container"] == proxy_target
        assert "wrapper" in result

        r = requests.get(f"{api}/shell-proxy")
        assert any(p["port"] == _PORT_API for p in r.json()["proxies"])

    def test_port_already_in_use(self, api, proxy_target):
        r = requests.post(
            f"{api}/shell-proxy/start",
            json={"container": proxy_target, "port": _PORT_API},
        )
        assert r.status_code == 409, r.text

    def test_stop_and_list(self, api, proxy_target):
        r = requests.post(f"{api}/shell-proxy/stop?port={_PORT_API}")
        assert r.status_code == 200

        r = requests.get(f"{api}/shell-proxy")
        assert not any(p["port"] == _PORT_API for p in r.json()["proxies"])

    def test_stop_nonexistent(self, api):
        r = requests.post(f"{api}/shell-proxy/stop?port=19998")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Integration — TCP + wrapper forwarding
# ══════════════════════════════════════════════════════════════════════════════


def _invoke_wrapper(command, cwd_file=None):
    """Run the wrapper with a simulated Claude Code command."""
    wrapper = _ensure_wrapper("test-container", _PORT_FWD)
    cmd = command
    if cwd_file:
        cmd = f"source /tmp/fake 2>/dev/null || true && eval '{command}' < /dev/null && pwd -P >| {cwd_file}"
    return subprocess.run(
        [wrapper, "-c", cmd],
        capture_output=True,
        text=True,
        timeout=15,
    )


class TestWrapperForwarding:
    """Wrapper → TCP proxy → container round-trip."""

    def test_forward_eval(self, api, proxy_target):
        """eval'd command is forwarded via the proxy."""
        r = requests.post(
            f"{api}/shell-proxy/start",
            json={"container": proxy_target, "port": _PORT_FWD},
        )
        assert r.status_code == 201, r.text
        time.sleep(1)

        proc = _invoke_wrapper("echo hello-from-wrapper")
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert "hello-from-wrapper" in proc.stdout

    def test_cwd_file_written(self, api, proxy_target):
        """cwd tracking file gets the container's pwd."""
        cwd_file = f"/tmp/kcs-test-cwd-{os.getpid()}"
        proc = _invoke_wrapper("echo ok", cwd_file=cwd_file)
        assert proc.returncode == 0, proc.stderr
        assert os.path.exists(cwd_file)
        assert open(cwd_file).read().strip().startswith("/")
        os.unlink(cwd_file)

    def test_exit_code_propagated(self, api, proxy_target):
        """Non-zero exit codes propagate through the wrapper."""
        proc = _invoke_wrapper("exit 42")
        assert proc.returncode == 42

    def test_direct_tcp(self, api, proxy_target):
        """Raw TCP connection to the proxy works."""
        try:
            sock = socket.create_connection(("127.0.0.1", _PORT_FWD), timeout=10)
            sock.sendall(b"echo tcp-direct\n")
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.close()
            result = json.loads(data.decode())
            assert "tcp-direct" in result["stdout"]
            assert result["exit_code"] == 0
        finally:
            requests.post(f"{api}/shell-proxy/stop?port={_PORT_FWD}")
