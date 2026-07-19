"""Pydantic request/response models for kcs API."""

from __future__ import annotations

from pydantic import BaseModel


class ContainerCreate(BaseModel):
    image: str
    name: str | None = None
    ports: list[int] | None = None
    env: dict[str, str] | None = None
    volumes: list[str] | None = None  # ["/data"] or ["./host:/container"]
    replicas: int = 1
    node: str | None = None  # pin to specific node (hostname)
    gpus: int | None = None  # number of GPUs (nvidia.com/gpu), exclusive
    cpu: str | None = None  # e.g. "1", "500m", "2"
    memory: str | None = None  # e.g. "512Mi", "1Gi"


class ScaleRequest(BaseModel):
    replicas: int


class ExecRequest(BaseModel):
    command: list[str]


class BuildRequest(BaseModel):
    tag: str
    path: str = "."
    no_push: bool = False


class ClusterJoin(BaseModel):
    node: str | None = None  # user@host or just host
    server: str | None = None
    token: str | None = None
    password: str | None = None


class WorkerNode(BaseModel):
    host: str
    user: str = "root"
    password: str


class ClusterConfig(BaseModel):
    backend: str = "k3s"  # k3s (host) or k3d
    sudo_password: str | None = None  # local sudo password (for reading token, etc.)
    nfs_path: str = (
        "/srv/nfs/k3s"  # NFS export path, use data disk if system disk is small
    )
    workers: list[WorkerNode] = []
