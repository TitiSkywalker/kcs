"""Health, status, nodes, info, container read-only tests."""

import pytest
import requests


def test_health(api):
    r = requests.get(f"{api}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status(api):
    r = requests.get(f"{api}/status")
    assert r.status_code == 200
    data = r.json()
    for key in ("server", "workers", "containers", "images", "nfs"):
        assert key in data, f"missing key: {key}"


def test_nodes(api):
    r = requests.get(f"{api}/nodes")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    assert isinstance(nodes, list)
    for n in nodes:
        assert "name" in n
        assert "status" in n


def test_info(api):
    r = requests.get(f"{api}/info")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "version" in data


def test_containers_readonly(api):
    """Read-only operations on a container (creates throwaway if needed)."""
    import time

    r = requests.get(f"{api}/containers")
    assert r.status_code == 200
    containers = r.json().get("containers", [])

    if containers:
        name = containers[0]["name"]
    else:
        name = "kcs-test-readonly"
        r = requests.post(
            f"{api}/containers",
            json={"image": "nginx:alpine", "name": name, "ports": [8080]},
        )
        assert r.status_code in (200, 201), f"create failed: {r.status_code}"
        time.sleep(5)

    try:
        assert requests.get(f"{api}/containers/{name}").status_code == 200
        assert requests.get(f"{api}/containers/{name}/pods").status_code == 200
        assert requests.get(f"{api}/containers/{name}/logs").status_code == 200
        r = requests.post(
            f"{api}/containers/{name}/exec",
            json={"command": ["echo", "hello"]})
        assert r.status_code == 200
    finally:
        if not containers:
            requests.delete(f"{api}/containers/{name}?force=true")
