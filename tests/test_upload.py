"""File upload tests — NFS direct and kubectl cp fallback."""

import time
from pathlib import Path


def run(s):
    print("\n── upload ──")
    tmp = Path("/tmp/kcs-test-upload.txt")
    tmp.write_text("kcs-upload-test\nline2\n")

    # PVC: NFS direct
    name = "kcs-test-upload-pvc"
    code, body = s.req("GET", f"/containers/{name}")
    if code == 200:
        s.req("DELETE", f"/containers/{name}?force=true")
        time.sleep(2)

    code, body = s.req("POST", "/containers", json={
        "image": "nginx:alpine", "name": name, "volumes": ["/data"],
    })
    s.test("  create (PVC)", code in (200, 201), f"status={code}")
    time.sleep(5)

    with open(tmp, "rb") as fh:
        code, body = s.req(
            "POST", f"/containers/{name}/upload?path=/data/hello.txt",
            files={"file": fh},
        )
    s.test("  upload (NFS)", code == 200 and body.get("method") == "nfs",
           f"status={code} body={body}")

    code, body = s.req("POST", f"/containers/{name}/exec",
                        json={"command": ["cat", "/data/hello.txt"]})
    s.test("  verify content", code == 200 and "kcs-upload-test" in str(body),
           f"body={str(body)[:80]}")

    s.req("DELETE", f"/containers/{name}?force=true")
    time.sleep(2)

    # Non-PVC: kubectl cp
    name = "kcs-test-upload-nopvc"
    code, body = s.req("GET", f"/containers/{name}")
    if code == 200:
        s.req("DELETE", f"/containers/{name}?force=true")
        time.sleep(2)

    code, body = s.req("POST", "/containers", json={
        "image": "nginx:alpine", "name": name,
    })
    s.test("  create (no PVC)", code in (200, 201), f"status={code}")
    time.sleep(5)

    with open(tmp, "rb") as fh:
        code, body = s.req(
            "POST", f"/containers/{name}/upload?path=/tmp/hello.txt",
            files={"file": fh},
        )
    s.test("  upload (kubectl cp)", code == 200, f"status={code} body={body}")

    s.req("DELETE", f"/containers/{name}?force=true")
    time.sleep(2)
    tmp.unlink()
