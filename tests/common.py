"""Shared test helpers."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class State:
    def __init__(self, port: int):
        self.port = port
        self.base = f"http://127.0.0.1:{port}/api/v1"
        self.passed = 0
        self.failed = 0
        self.server_proc = None

    def start_server(self):
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [
            sys.executable, "-m", "uvicorn", "kcs.server:app",
            "--host", "127.0.0.1", "--port", str(self.port),
        ]
        self.server_proc = subprocess.Popen(
            cmd, stdout=open(f"/tmp/kcs-test-{self.port}.log", "w"),
            stderr=subprocess.STDOUT, env=env,
            cwd=Path(__file__).resolve().parent.parent,
            preexec_fn=os.setsid if sys.platform != "win32" else None,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                r = requests.get(
                    f"http://127.0.0.1:{self.port}/api/v1/health", timeout=2)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            if self.server_proc.poll() is not None:
                return False
            time.sleep(0.3)
        return False

    def stop_server(self):
        if self.server_proc is None:
            return
        try:
            os.killpg(os.getpgid(self.server_proc.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            self.server_proc.wait(timeout=5)
        except Exception:
            self.server_proc.kill()
        self.server_proc = None

    def test(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  ✓ {name}")
        else:
            self.failed += 1
            print(f"  ✗ {name}  — {detail}")

    def req(self, method, path, **kwargs):
        try:
            r = requests.request(method, f"{self.base}{path}", timeout=10, **kwargs)
            body = (r.json() if r.headers.get("content-type", "").startswith(
                "application/json") else r.text)
            return r.status_code, body
        except Exception as e:
            return None, str(e)

    def ok(self, path, msg=""):
        code, body = self.req("GET", path)
        self.test(f"GET {path}", code == 200, f"status={code} {body} {msg}")

    def ok_json(self, path, checks=None, msg=""):
        code, body = self.req("GET", path)
        if code != 200:
            self.test(f"GET {path} (200)", False, f"status={code}")
            return body
        if checks:
            for key, expected in checks.items():
                actual = body.get(key)
                self.test(f"GET {path} -> {key}={expected}", actual == expected,
                          f"got {actual} {msg}")
        else:
            self.test(f"GET {path} (200 OK)", True)
        return body

    def post_json(self, path, data, expected_status=201, msg=""):
        code, body = self.req("POST", path, json=data)
        self.test(f"POST {path}", code == expected_status,
                  f"status={code} body={body} {msg}")
        return body

    def summary(self):
        total = self.passed + self.failed
        print(flush=True)
        print(f"{'=' * 60}", flush=True)
        print(f"Results: {self.passed}/{total} passed", end="", flush=True)
        if self.failed:
            print(f", {self.failed} FAILED", flush=True)
        else:
            print("  ✓ all pass", flush=True)
        print(f"{'=' * 60}", flush=True)
        return self.failed == 0
