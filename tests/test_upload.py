"""File upload tests — NFS direct and kubectl cp fallback."""

import time
from pathlib import Path

import pytest
import requests


_PVC = "kcs-test-upload-pvc"
_NOPVC = "kcs-test-upload-nopvc"


@pytest.fixture(scope="module")
def pvc_container(api):
    tmp = Path("/tmp/kcs-test-upload.txt")
    tmp.write_text("kcs-upload-test\nline2\n")
    r = requests.get(f"{api}/containers/{_PVC}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{_PVC}?force=true")
        time.sleep(2)
    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": _PVC, "volumes": ["/data"],
    })
    assert r.status_code in (200, 201)
    time.sleep(5)
    yield
    requests.delete(f"{api}/containers/{_PVC}?force=true")
    time.sleep(2)
    tmp.unlink(missing_ok=True)


def test_upload_method_is_nfs(api, pvc_container):
    with open("/tmp/kcs-test-upload.txt", "rb") as fh:
        r = requests.post(
            f"{api}/containers/{_PVC}/upload?path=/data/hello.txt",
            files={"file": fh})
    assert r.status_code == 200
    assert r.json()["method"] == "nfs"


def test_verify_content(api, pvc_container):
    r = requests.post(f"{api}/containers/{_PVC}/exec",
                       json={"command": ["cat", "/data/hello.txt"]})
    assert r.status_code == 200
    assert "kcs-upload-test" in r.json()["output"]


@pytest.fixture(scope="module")
def nopvc_container(api):
    tmp = Path("/tmp/kcs-test-upload-nopvc.txt")
    tmp.write_text("kcs-upload-test-no-pvc\n")
    r = requests.get(f"{api}/containers/{_NOPVC}")
    if r.status_code == 200:
        requests.delete(f"{api}/containers/{_NOPVC}?force=true")
        time.sleep(2)
    r = requests.post(f"{api}/containers", json={
        "image": "nginx:alpine", "name": _NOPVC,
    })
    assert r.status_code in (200, 201)
    time.sleep(5)
    yield
    requests.delete(f"{api}/containers/{_NOPVC}?force=true")
    time.sleep(2)
    tmp.unlink(missing_ok=True)


def test_upload_kubectl_cp(api, nopvc_container):
    with open("/tmp/kcs-test-upload-nopvc.txt", "rb") as fh:
        r = requests.post(
            f"{api}/containers/{_NOPVC}/upload?path=/tmp/hello.txt",
            files={"file": fh})
    assert r.status_code == 200, f"upload: {r.status_code} {r.text[:100]}"
