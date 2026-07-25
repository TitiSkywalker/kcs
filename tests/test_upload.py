"""File upload tests — NFS direct and kubectl cp fallback."""

import time
from pathlib import Path

import pytest
import requests


_PVC = "kcs-test-upload-pvc"
_NOPVC = "kcs-test-upload-nopvc"


def _create(api, name, **extra):
    r = requests.get(f"{api}/containers/{name}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{name}?force=true")
        time.sleep(2)
    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": name, **extra,
    })
    assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:100]}"
    time.sleep(5)


def _delete(api, name):
    requests.delete(f"{api}/containers/{name}?force=true")
    time.sleep(2)


@pytest.fixture(scope="module")
def pvc_container(api):
    tmp = Path("/tmp/kcs-test-upload.txt")
    tmp.write_text("kcs-upload-test\nline2\n")
    _create(api, _PVC, volumes=["/data"])
    yield
    _delete(api, _PVC)
    tmp.unlink(missing_ok=True)


def test_nfs_upload_and_verify(api, pvc_container):
    """Upload via NFS and verify the file landed inside the container."""
    with open("/tmp/kcs-test-upload.txt", "rb") as fh:
        r = requests.post(
            f"{api}/containers/{_PVC}/upload?path=/data/hello.txt",
            files={"file": fh})
    assert r.status_code == 200
    assert r.json()["method"] == "nfs"

    r = requests.post(f"{api}/containers/{_PVC}/exec",
                       json={"command": ["cat", "/data/hello.txt"]})
    assert r.status_code == 200
    assert "kcs-upload-test" in r.json()["output"]


@pytest.fixture(scope="module")
def nopvc_container(api):
    tmp = Path("/tmp/kcs-test-upload-nopvc.txt")
    tmp.write_text("kcs-upload-test-no-pvc\n")
    _create(api, _NOPVC)
    yield
    _delete(api, _NOPVC)
    tmp.unlink(missing_ok=True)


def test_upload_kubectl_cp(api, nopvc_container):
    with open("/tmp/kcs-test-upload-nopvc.txt", "rb") as fh:
        r = requests.post(
            f"{api}/containers/{_NOPVC}/upload?path=/tmp/hello.txt",
            files={"file": fh})
    assert r.status_code == 200, f"upload: {r.status_code} {r.text[:100]}"
