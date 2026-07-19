"""Cluster route — declarative configuration apply."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from kcs.config import load, save
from kcs.server.models import ClusterConfig
from kcs.server.services import (
    build_ssh_cmd,
    get_server_ip_from_kubeconfig,
    get_service,
    read_k3s_token,
    set_service_config,
)

log = logging.getLogger("kcs")
router = APIRouter(tags=["Cluster"])


@router.post(
    "/api/v1/cluster/apply",
    summary="Apply cluster configuration",
    description="Declaratively configure the cluster. Accepts a full `ClusterConfig`:\n\n"
    "- **backend**: currently only `k3s` is supported.\n"
    "- **nfs_path**: server-side NFS export path.\n"
    "- **workers**: list of `{host, user, password}` to join via SSH.\n\n"
    "Workers already joined are skipped; workers removed from the config "
    "are pruned from the cluster.",
    response_description="Backend type and per-node join results.",
    responses={400: {"description": "Unknown backend or missing k3s"}},
)
def apply_cluster_config(req: ClusterConfig):
    """Apply cluster config — ensure backend, join workers, prune stale nodes."""
    svc = get_service()
    set_service_config(req)

    results = []

    if req.backend != "k3s":
        raise HTTPException(status_code=400, detail=f"Unknown backend: {req.backend}")

    k3s_src = "/etc/rancher/k3s/k3s.yaml"
    if not os.path.exists(k3s_src):
        raise HTTPException(status_code=400, detail="Host k3s not installed")
    k3s_dst = str(Path.home() / ".kcs" / "k3s.yaml")
    if not os.path.exists(k3s_dst) and os.path.exists(k3s_src):
        shutil.copy(k3s_src, k3s_dst)
    cfg = load()
    cfg["current_cluster"] = None
    save(cfg)
    results.append("Switched to host k3s")

    if not req.workers:
        svc._prune_stale_workers(req, set())
        return {"backend": req.backend, "results": results}

    for w in req.workers:
        target = f"{w.user}@{w.host}"

        server_ip = None
        try:
            result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
            for ip in result.stdout.strip().split():
                if not ip.startswith(("127.", "10.", "172.")):
                    server_ip = ip
                    break
        except Exception:
            pass
        if not server_ip:
            server_ip = get_server_ip_from_kubeconfig()
        if not server_ip:
            results.append({"node": target, "error": "Cannot detect server IP"})
            continue

        k3s_token = read_k3s_token()
        if not k3s_token:
            results.append({"node": target, "error": "Cannot read k3s token"})
            continue

        sshpass_bin = shutil.which("sshpass")
        env = os.environ.copy()
        if sshpass_bin:
            env["SSHPASS"] = w.password

        skip = False
        try:
            client = get_service().get_client()
            hn = subprocess.run(
                build_ssh_cmd(target, "hostname", sshpass_bin is not None, False),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            remote_hostname = hn.stdout.strip() if hn.returncode == 0 else w.host
            existing = client.core_v1.list_node(
                field_selector=f"metadata.name={remote_hostname}"
            )
            if existing.items:
                results.append(
                    {
                        "node": target,
                        "hostname": remote_hostname,
                        "status": "already_joined",
                    }
                )
                skip = True
        except Exception:
            remote_hostname = w.host

        if skip:
            continue

        k3s_url = f"https://{server_ip}:6443"
        install_cmd = (
            f"curl -sfL https://get.k3s.io | "
            f"K3S_URL={k3s_url} K3S_TOKEN={k3s_token} sh -"
        )
        cleanup = (
            "sudo systemctl stop k3s-agent 2>/dev/null; "
            "sudo systemctl disable k3s-agent 2>/dev/null; "
            "sudo /usr/local/bin/k3s-killall.sh 2>/dev/null; "
            "sudo /usr/local/bin/k3s-agent-uninstall.sh 2>/dev/null; "
            "sudo rm -rf /var/lib/rancher/k3s"
        )
        install_cmd = f"{cleanup}; {install_cmd}"

        need_sudo = w.user != "root"
        if need_sudo:
            install_cmd = (
                f"sudo -S -p '' sh -c '{install_cmd}'"
                if sshpass_bin
                else f"sudo sh -c '{install_cmd}'"
            )

        ssh_cmd = build_ssh_cmd(
            target, install_cmd, sshpass_bin is not None, need_sudo and not sshpass_bin
        )
        stdin_input = (w.password + "\n") if need_sudo else None

        try:
            result = subprocess.run(
                ssh_cmd,
                env=env,
                input=stdin_input,
                text=True,
                timeout=120,
                capture_output=True,
            )
        except subprocess.TimeoutExpired:
            results.append({"node": target, "error": "SSH timeout"})
            continue

        if result.returncode == 0:
            results.append(
                {"node": target, "hostname": remote_hostname, "status": "joined"}
            )
        else:
            results.append({"node": target, "error": f"exit {result.returncode}"})

    return {"backend": req.backend, "results": results}
