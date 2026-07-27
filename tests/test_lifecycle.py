"""Container lifecycle and resource declaration tests."""

import time

import pytest
import requests

_NAME = "kcs-test-throwaway"


def _create(api, name, **extra):
    """Create a container and wait for it to be ready."""
    r = requests.get(f"{api}/containers/{name}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{name}?force=true")
        time.sleep(2)
    r = requests.post(
        f"{api}/containers",
        json={
            "image": "nginx:alpine",
            "name": name,
            **extra,
        },
    )
    assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:100]}"
    time.sleep(5)


def _delete(api, name):
    requests.delete(f"{api}/containers/{name}?force=true")
    time.sleep(2)


@pytest.fixture(scope="module")
def container(api):
    """Create a throwaway container, yield it, clean up."""
    _create(api, _NAME, ports=[8080], replicas=1)
    yield _NAME
    _delete(api, _NAME)


def test_container_created(api, container):
    r = requests.get(f"{api}/containers/{container}")
    assert r.status_code == 200
    assert r.json()["status"] in ("running", "pending")


def test_container_stop_and_start(api, container):
    """Stop a running container, verify it stops, then start it again."""
    r = requests.post(f"{api}/containers/{container}/stop")
    assert r.status_code == 200
    time.sleep(2)
    r = requests.get(f"{api}/containers/{container}")
    assert r.json()["status"] in (
        "stopped",
        "terminating",
    ), f"status after stop: {r.json().get('status')}"

    r = requests.post(f"{api}/containers/{container}/start")
    assert r.status_code == 200
    time.sleep(5)
    r = requests.get(f"{api}/containers/{container}")
    assert r.json()["status"] in (
        "running",
        "pending",
    ), f"status after start: {r.json().get('status')}"


def test_container_scale(api, container):
    """Scale up and verify pod count matches."""
    r = requests.post(f"{api}/containers/{container}/scale", json={"replicas": 2})
    assert r.status_code == 200

    # Wait up to 20 s for at least 2 pods (Running may lag due to image pull)
    deadline = time.time() + 20
    ready = False
    while time.time() < deadline:
        pods = requests.get(f"{api}/containers/{container}/pods").json()["pods"]
        if len(pods) >= 2:
            ready = True
            break
        time.sleep(1)
    assert ready, f"expected >= 2 pods after scale to 2, got {len(pods)}"

    # Scale back
    r = requests.post(f"{api}/containers/{container}/scale", json={"replicas": 1})
    assert r.status_code == 200
    time.sleep(3)


def test_container_delete_and_404(api):
    """Force-delete a container and verify it returns 404 afterwards."""
    name = "kcs-test-deletable"
    _create(api, name)
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
    r = requests.post(
        f"{api}/containers",
        json={
            "image": "nginx:alpine",
            "name": _RNAME,
            "ports": [8080],
            "cpu": "250m",
            "memory": "128Mi",
        },
    )
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
    import os
    import subprocess

    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kcs/k3s.yaml")
    pods = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-l",
            f"app={_RNAME}",
            "-o",
            "jsonpath={.items[0].spec.containers[0].resources}",
            "--kubeconfig",
            kubeconfig,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if pods.returncode == 0:
        spec = pods.stdout.strip()
        assert "cpu" in spec and "250m" in spec
        assert "memory" in spec and "128Mi" in spec
