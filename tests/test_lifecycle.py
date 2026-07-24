"""Container lifecycle and resource declaration tests."""

import time


def run(s):
    _test_lifecycle(s)
    _test_resources(s)


def _test_lifecycle(s):
    print("\n── containers (lifecycle) ──")
    name = "kcs-test-throwaway"

    code, body = s.req("GET", f"/containers/{name}")
    if code == 200:
        s.req("DELETE", f"/containers/{name}?force=true")
        time.sleep(2)

    code, body = s.req("POST", "/containers", json={
        "image": "nginx:alpine", "name": name, "ports": [8080], "replicas": 1,
    })
    s.test(f"POST /containers (create {name})", code in (200, 201),
           f"status={code} body={body}")
    time.sleep(5)

    code, body = s.req("GET", f"/containers/{name}")
    ok = code == 200 and body.get("status") in ("running", "pending")
    s.test(f"  container created (status={body.get('status') if body else '?'})",
           ok, f"status={code}")

    code, body = s.req("POST", f"/containers/{name}/stop")
    s.test("POST .../stop", code == 200, f"status={code}")
    time.sleep(3)

    code, body = s.req("POST", f"/containers/{name}/start")
    s.test("POST .../start", code == 200, f"status={code}")
    time.sleep(3)

    code, body = s.req("POST", f"/containers/{name}/scale", json={"replicas": 1})
    s.test("POST .../scale", code == 200, f"status={code}")
    time.sleep(2)

    code, body = s.req("DELETE", f"/containers/{name}?force=true")
    s.test(f"DELETE .../{name}", code == 200, f"status={code}")
    time.sleep(2)

    code, _ = s.req("GET", f"/containers/{name}")
    s.test("  container gone after delete", code == 404, f"status={code}")


def _test_resources(s):
    print("\n── containers (resources) ──")
    name = "kcs-test-resources"

    code, body = s.req("GET", f"/containers/{name}")
    if code == 200:
        s.req("DELETE", f"/containers/{name}?force=true")
        time.sleep(2)

    code, body = s.req("POST", "/containers", json={
        "image": "nginx:alpine", "name": name, "ports": [8080],
        "cpu": "250m", "memory": "128Mi",
    })
    s.test(f"POST /containers (create {name})", code in (200, 201),
           f"status={code} body={body}")
    time.sleep(5)

    code, body = s.req("GET", f"/containers/{name}")
    ok = code == 200
    s.test(f"GET .../{name}", ok, f"status={code}")

    if ok and body:
        res = body.get("resources", {})
        s.test("  has resources field", bool(res), f"got {res}")
        if res:
            reqs = res.get("requests", {})
            limits = res.get("limits", {})
            s.test("  requests.cpu = 250m", reqs.get("cpu") == "250m",
                    f"got {reqs.get('cpu')}")
            s.test("  requests.memory = 128Mi", reqs.get("memory") == "128Mi",
                    f"got {reqs.get('memory')}")
            s.test("  limits.cpu = 250m", limits.get("cpu") == "250m",
                    f"got {limits.get('cpu')}")
            s.test("  limits.memory = 128Mi", limits.get("memory") == "128Mi",
                    f"got {limits.get('memory')}")

    # Verify pod spec via kubectl
    import subprocess, os
    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser(
        "~/.kcs/k3s.yaml")
    pods = subprocess.run(
        ["kubectl", "get", "pods", "-l", f"app={name}", "-o",
         "jsonpath={.items[0].spec.containers[0].resources}",
         "--kubeconfig", kubeconfig],
        capture_output=True, text=True, timeout=10,
    )
    if pods.returncode == 0 and pods.stdout.strip():
        spec = pods.stdout.strip()
        s.test("  pod spec has cpu=250m", '"cpu":"250m"' in spec or "cpu:250m" in spec)
        s.test("  pod spec has memory=128Mi",
               '"memory":"128Mi"' in spec or "memory:128Mi" in spec)

    s.req("DELETE", f"/containers/{name}?force=true")
    time.sleep(2)
    code, _ = s.req("GET", f"/containers/{name}")
    s.test("  container gone after delete", code == 404, f"status={code}")
