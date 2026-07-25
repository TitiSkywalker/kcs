"""Pytest fixtures — session-scoped server lifecycle."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def api():
    """Start kcs server on a free port, yield the base URL, teardown."""
    port = _find_free_port()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable, "-m", "uvicorn", "kcs.server:app",
        "--host", "127.0.0.1", "--port", str(port),
    ]
    log_path = f"/tmp/kcs-test-{port}.log"
    proc = subprocess.Popen(
        cmd, stdout=open(log_path, "w"), stderr=subprocess.STDOUT, env=env,
        cwd=Path(__file__).resolve().parent.parent,
        preexec_fn=os.setsid if sys.platform != "win32" else None,
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        if proc.poll() is not None:
            pytest.fail(f"Server exited with code {proc.returncode}")
        time.sleep(0.3)
    else:
        pytest.fail("Server did not start within 30s")

    print(f"\n  [kcs server on port {port}]")
    yield f"http://127.0.0.1:{port}/api/v1"

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
