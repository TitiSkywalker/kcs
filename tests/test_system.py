"""Health, status, nodes, info, container read-only tests."""


def run(s):
    print("\n── health ──")
    s.ok("/health")

    print("\n── status ──")
    body = s.ok_json("/status")
    if body:
        s.test("  has server", "server" in body)
        s.test("  has workers", "workers" in body)
        s.test("  has containers", "containers" in body)
        s.test("  has images", "images" in body)
        s.test("  has nfs", "nfs" in body)

    print("\n── nodes ──")
    body = s.ok_json("/nodes")
    if body and "nodes" in body:
        s.test("  nodes is list", isinstance(body["nodes"], list))
        for n in body["nodes"]:
            s.test(f"  node {n.get('name', '?')}", "name" in n and "status" in n)

    print("\n── info ──")
    body = s.ok_json("/info")
    if body:
        s.test("  has nodes", "nodes" in body)
        s.test("  has version", "version" in body)

    print("\n── containers (read-only) ──")
    body = s.ok_json("/containers")
    containers = body.get("containers", []) if body else []

    if containers:
        s.test("  has containers", len(containers) > 0)
        name = containers[0]["name"]
        code, _ = s.req("GET", f"/containers/{name}")
        s.test(f"GET /containers/{name}", code == 200, f"status={code}")
        code, _ = s.req("GET", f"/containers/{name}/pods")
        s.test(f"GET /containers/{name}/pods", code == 200, f"status={code}")
        code, _ = s.req("GET", f"/containers/{name}/logs")
        s.test(f"GET /containers/{name}/logs", code == 200, f"status={code}")
        s.post_json(f"/containers/{name}/exec", {"command": ["echo", "hello"]}, 200)
    else:
        s.test("  no existing containers (skip)", True)
