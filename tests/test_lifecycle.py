"""Container lifecycle and resource declaration tests."""

import time

import pytest
import requests


_NAME = "kcs-test-throwaway"


@pytest.fixture(scope="module")
def container(api):
    """Create a throwaway container, yield it, clean up."""
    r = requests.get(f"{api}/containers/{_NAME}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{_NAME}?force=true")
        time.sleep(2)
    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": _NAME, "ports": [8080], "replicas": 1,
    })
    assert r.status_code in (200, 201)
    time.sleep(5)
    yield _NAME
    requests.delete(f"{api}/containers/{_NAME}?force=true")
    time.sleep(2)


def test_container_created(api, container):
    r = requests.get(f"{api}/containers/{container}")
    assert r.status_code == 200
    assert r.json()["status"] in ("running", "pending")


def test_container_stop(api, container):
    r = requests.post(f"{api}/containers/{container}/stop")
    assert r.status_code == 200
    time.sleep(2)
    r = requests.get(f"{api}/containers/{container}")
    assert r.json()["status"] in ("stopped", "terminating")


def test_container_start(api, container):
    r = requests.post(f"{api}/containers/{container}/start")
    assert r.status_code == 200
    time.sleep(5)
    r = requests.get(f"{api}/containers/{container}")
    assert r.json()["status"] in ("running", "pending"), f"status={r.json().get("status")}"


def test_container_scale(api, container):
    r = requests.post(f"{api}/containers/{container}/scale", json={"replicas": 1})
    assert r.status_code == 200


def test_container_delete(api):
    name = "kcs-test-deletable"
    r = requests.get(f"{api}/containers/{name}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{name}?force=true")
        time.sleep(2)
    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": name,
    })
    assert r.status_code in (200, 201)
    time.sleep(5)
    r = requests.delete(f"{api}/containers/{name}?force=true")
    assert r.status_code == 200
    time.sleep(2)
    r = requests.get(f"{api}/containers/{name}")
    assert r.status_code == 404


_RNAME = "kcs-test-resources"


@pytest.fixture(scope="module")
def res_container(api):
    r = requests.get(f"{api}/containers/{_RNAME}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{_RNAME}?force=true")
        time.sleep(2)
    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": _RNAME, "ports": [8080],
        "cpu": "250m", "memory": "128Mi",
    })
    assert r.status_code in (200, 201)
    time.sleep(5)
    yield
    requests.delete(f"{api}/containers/{_RNAME}?force=true")
    time.sleep(2)


def test_resource_field(api, res_container):
    r = requests.get(f"{api}/containers/{_RNAME}")
    res = r.json().get("resources", {})
    assert res, f"no resources: {r.json()}"


def test_cpu_declared(api, res_container):
    r = requests.get(f"{api}/containers/{_RNAME}")
    res = r.json()["resources"]
    assert res["requests"]["cpu"] == "250m"
    assert res["limits"]["cpu"] == "250m"


def test_memory_declared(api, res_container):
    r = requests.get(f"{api}/containers/{_RNAME}")
    res = r.json()["resources"]
    assert res["requests"]["memory"] == "128Mi"
    assert res["limits"]["memory"] == "128Mi"


def test_pod_spec_matches(res_container):
    import subprocess, os
    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser(
        "~/.kcs/k3s.yaml")
    pods = subprocess.run(
        ["kubectl", "get", "pods", "-l", f"app={_RNAME}",
         "-o", "jsonpath={.items[0].spec.containers[0].resources}",
         "--kubeconfig", kubeconfig],
        capture_output=True, text=True, timeout=10,
    )
    if pods.returncode == 0:
        spec = pods.stdout.strip()
        assert "cpu" in spec and "250m" in spec
        assert "memory" in spec and "128Mi" in spec
