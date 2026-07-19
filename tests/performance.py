#!/usr/bin/env python3
"""Performance tests for kcs API server.

Usage:  python tests/performance.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests


def _find_free_port():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _find_free_port()
BASE = f"http://127.0.0.1:{PORT}/api/v1"
server_proc = None


def start_server():
    global server_proc
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Ensure kubeconfig is accessible (test_api.py inherits from shell, but
    # this script may be run directly without KUBECONFIG set)
    if "KUBECONFIG" not in env:
        for p in [os.path.expanduser("~/.kcs/k3s.yaml"), "/etc/rancher/k3s/k3s.yaml"]:
            if os.path.exists(p):
                env["KUBECONFIG"] = p
                break
    log_path = f"/tmp/kcs-perf-{PORT}.log"
    cmd = [
        sys.executable, "-m", "uvicorn", "kcs.server:app",
        "--host", "127.0.0.1", "--port", str(PORT),
    ]
    server_proc = subprocess.Popen(
        cmd, stdout=open(log_path, "w"), stderr=subprocess.STDOUT, env=env,
        cwd=Path(__file__).resolve().parent.parent,
        preexec_fn=os.setsid if sys.platform != "win32" else None,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if server_proc.poll() is not None:
            return False
        time.sleep(0.3)
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


def perf(name: str, fn, runs: int = 100) -> dict:
    """Run fn() *runs* times and return stats."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    times.sort()
    avg = sum(times) / len(times)
    p50 = times[len(times) // 2]
    p99 = times[int(len(times) * 0.99)]
    rps = runs / sum(times)
    print(
        f"  {name:40s}  avg={avg*1000:6.1f}ms  "
        f"p50={p50*1000:6.1f}ms  p99={p99*1000:6.1f}ms  "
        f"{rps:6.0f} req/s"
    )


def perf_lifecycle(label: str, session, runs: int = 10,
                   volumes: list[str] | None = None):
    """Create + delete containers × N and measure create→ready time."""
    # Clean up leftovers from previous interrupted runs
    for i in range(runs):
        session.delete(f"{BASE}/containers/perf-{label}-{i}?force=true")
    session.delete(f"{BASE}/containers/perf-{label}-ready?force=true")

    create_times = []
    delete_times = []

    for i in range(runs):
        name = f"perf-{label}-{i}"
        body: dict = {"image": "nginx:alpine", "name": name, "ports": [8080]}
        if volumes:
            body["volumes"] = volumes

        t0 = time.perf_counter()
        r = session.post(f"{BASE}/containers", json=body)
        if r.status_code < 200 or r.status_code > 299:
            detail = r.text[:200] if r.text else "no body"
            raise RuntimeError(f"create failed: {r.status_code} — {detail}")
        create_times.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        session.delete(f"{BASE}/containers/{name}?force=true")
        delete_times.append(time.perf_counter() - t0)

    create_times.sort()
    delete_times.sort()
    avg_c = sum(create_times) / len(create_times)
    avg_d = sum(delete_times) / len(delete_times)

    print(
        f"  {'create ' + label:40s}  avg={avg_c*1000:6.1f}ms  "
        f"p50={create_times[len(create_times)//2]*1000:6.1f}ms"
    )
    print(
        f"  {'delete ' + label:40s}  avg={avg_d*1000:6.1f}ms  "
        f"p50={delete_times[len(delete_times)//2]*1000:6.1f}ms"
    )

    # Single-shot ready time
    ready_name = f"perf-{label}-ready"
    body = {"image": "nginx:alpine", "name": ready_name, "ports": [8080]}
    if volumes:
        body["volumes"] = volumes

    t0 = time.perf_counter()
    session.post(f"{BASE}/containers", json=body)
    deadline = time.time() + 30
    while time.time() < deadline:
        r = session.get(f"{BASE}/containers/{ready_name}")
        if r.status_code == 200 and r.json().get("status") == "running":
            break
        time.sleep(0.5)
    ready_s = time.perf_counter() - t0
    print(
        f"  {'create → ready ' + label:40s}  {ready_s:5.1f}s  "
        f"(image pull + pod start)"
    )

    session.delete(f"{BASE}/containers/{ready_name}?force=true")


def main():
    global server_proc

    print(f"{'=' * 60}")
    print(f"kcs performance  ·  port={PORT}")
    print(f"{'=' * 60}\n")

    if not start_server():
        print("FAILED to start server")
        sys.exit(1)

    session = requests.Session()

    try:
        print("── health check ──")
        perf("GET /health", lambda: session.get(f"{BASE}/health").raise_for_status())

        print("\n── dashboard status ──")
        perf("GET /status",
             lambda: session.get(f"{BASE}/status").raise_for_status(), runs=30)

        print("\n── nodes ──")
        perf("GET /nodes",
             lambda: session.get(f"{BASE}/nodes").raise_for_status(), runs=30)

        print("\n── container list ──")
        perf("GET /containers",
             lambda: session.get(f"{BASE}/containers").raise_for_status(), runs=50)

        print("\n── container lifecycle ──")
        perf_lifecycle("deploy", session)
        print()
        perf_lifecycle("statefulset-pvc", session, volumes=["/data"])

        print(f"\n{'=' * 60}")
        print("  times include k8s API + cluster network latency")
        print(f"{'=' * 60}")

    finally:
        stop_server()
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
