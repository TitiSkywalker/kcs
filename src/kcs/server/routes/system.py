"""System routes — health, status, nodes, info, and images."""

from __future__ import annotations

import logging
import subprocess

from fastapi import APIRouter, HTTPException

from kcs import __version__
from kcs.config import add_built_image, get_registry, load, remove_built_image
from kcs.server.models import BuildRequest
from kcs.server.services import get_service

log = logging.getLogger("kcs")
router = APIRouter()


@router.get("/api/v1/health", tags=["System"], summary="Health check")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/api/v1/status", tags=["System"], summary="Aggregated cluster status")
def cluster_status():
    """Single endpoint for the dashboard — server, workers, containers, images, NFS."""
    svc = get_service()
    client = svc.get_client()

    nodes = client.list_nodes()
    containers = client.list()

    server_node = None
    workers = []
    for n in nodes:
        if "control-plane" in n["roles"] or "master" in n["roles"]:
            server_node = n
        else:
            workers.append(n)

    server_ip = server_node["ip"] if server_node else None

    nfs_ok = False
    try:
        r = subprocess.run(
            ["kubectl", "get", "storageclass", "nfs-client",
             "--kubeconfig", svc.get_kubeconfig_path()],
            capture_output=True, timeout=5,
        )
        nfs_ok = r.returncode == 0
    except Exception:
        pass

    cfg = load()
    built = list(cfg.get("built_images", {}).keys())

    container_list = []
    seen = set()
    for c in containers:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        pods = client.list_pods(c["name"])
        pod_node = pods[0]["node"] if pods else "—"
        container_list.append({
            "name": c["name"], "image": c["image"], "status": c["status"],
            "replicas": c["replicas"], "age": c["age"], "node": pod_node,
            "resources": c.get("resources", {}), "ports": c.get("ports", []),
        })

    return {
        "server": {
            "name": server_node["name"] if server_node else "?",
            "ip": server_ip or "?",
            "status": server_node["status"] if server_node else "?",
            "capacity": server_node.get("capacity", {}) if server_node else None,
            "allocatable": server_node.get("allocatable", {}) if server_node else None,
            "used": server_node.get("used", {}) if server_node else None,
            "disk_pressure": server_node.get("disk_pressure", False) if server_node else False,
            "memory_pressure": server_node.get("memory_pressure", False) if server_node else False,
            "pid_pressure": server_node.get("pid_pressure", False) if server_node else False,
            "taints": server_node.get("taints", []) if server_node else [],
        },
        "workers": [{
            "name": w["name"], "ip": w["ip"], "status": w["status"],
            "capacity": w.get("capacity", {}), "allocatable": w.get("allocatable", {}),
            "used": w.get("used", {}),
            "disk_pressure": w.get("disk_pressure", False),
            "memory_pressure": w.get("memory_pressure", False),
            "pid_pressure": w.get("pid_pressure", False),
            "taints": w.get("taints", []),
        } for w in workers],
        "nfs": nfs_ok,
        "images": built,
        "containers": container_list,
    }


@router.get("/api/v1/nodes", tags=["System"], summary="List cluster nodes")
def list_nodes():
    client = get_service().get_client()
    try:
        nodes = client.list_nodes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"nodes": nodes}


@router.get("/api/v1/info", tags=["System"], summary="Cluster info")
def cluster_info():
    client = get_service().get_client()
    try:
        info = client.cluster_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return info


@router.post("/api/v1/build", tags=["Images"], summary="Build and push an image")
def build_image(req: BuildRequest):
    """Run `docker build`, optionally push to cluster registry."""
    svc = get_service()
    result = subprocess.run(
        ["docker", "build", "-t", req.tag, req.path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Build failed: {result.stderr[-500:]}")

    if req.no_push:
        return {"message": f"Image '{req.tag}' built (not pushed)"}

    reg = get_registry() or svc._ensure_registry()
    if not reg:
        raise HTTPException(status_code=500, detail="Cannot deploy registry")

    svc._push_to_registry(req.tag, reg)
    full_tag = f"{reg['host']}:{reg['internal_port']}/{req.tag}"
    add_built_image(req.tag)
    return {"message": f"Image '{req.tag}' pushed to {full_tag}"}


@router.delete("/api/v1/images/{tag:path}", tags=["Images"], summary="Forget a built image")
def delete_image(tag: str):
    """Remove image from kcs tracking (does not delete from registry)."""
    if not remove_built_image(tag):
        raise HTTPException(status_code=404, detail=f"Image '{tag}' not found")
    return {"message": f"Image '{tag}' removed"}
