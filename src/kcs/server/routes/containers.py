"""Container routes — CRUD, lifecycle, logs, exec, and shell sessions."""

from __future__ import annotations

import logging
import os
import subprocess
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

from kcs.server.models import ContainerCreate, ExecRequest, ScaleRequest
from kcs.server.services import get_service, resolve_image

log = logging.getLogger("kcs")
router = APIRouter(tags=["Containers"])


@router.get(
    "/api/v1/containers",
    summary="List containers",
    description="Return every container managed by kcs across the cluster. "
    "Set `all_namespaces=true` to include containers outside the default namespace.",
    response_description="Container list with name, image, status, replicas, and resource requests.",
    responses={500: {"description": "Kubernetes API unreachable"}},
)
def list_containers(all: bool = Query(default=False, alias="all_namespaces")):
    """List all kcs-managed containers."""
    client = get_service().get_client()
    try:
        containers = client.list(all_namespaces=all)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"containers": containers}


@router.post(
    "/api/v1/containers",
    status_code=201,
    summary="Create and run a container",
    description="Launch a new container from an image. "
    "Optionally set CPU, memory, GPU reservations (requests=limits for exclusive allocation). "
    "Pin to a specific node, attach volumes, and expose ports.",
    response_description="Created container summary.",
    responses={
        201: {"description": "Container created"},
        409: {"description": "A container with this name already exists"},
        500: {"description": "Kubernetes API error"},
    },
)
def create_container(req: ContainerCreate):
    """Create and run a container."""
    client = get_service().get_client()
    image = resolve_image(req.image)

    name = req.name
    if not name:
        name = image.rsplit("/", 1)[-1].split(":")[0].replace("_", "-")

    env_dict = req.env or {}
    volumes = []
    for v in req.volumes or []:
        if ":" in v:
            parts = v.split(":", 1)
            volumes.append({"host": parts[0], "container": parts[1]})
        else:
            volumes.append({"path": v})

    try:
        result = client.create(
            name=name,
            image=image,
            ports=req.ports,
            env=env_dict,
            volumes=volumes,
            replicas=req.replicas,
            node=req.node,
            gpus=req.gpus,
            cpu=req.cpu,
            memory=req.memory,
        )
        return result
    except Exception as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=500, detail=msg)


@router.get(
    "/api/v1/containers/{name}",
    summary="Inspect a container",
    description="Return full details: image, status, replicas, ports, environment variables, "
    "volume mounts, and hardware resource requests/limits.",
    response_description="Container detail object.",
    responses={
        200: {"description": "Container found"},
        404: {"description": "Container not found"},
    },
)
def inspect_container(name: str):
    """Get full container details."""
    client = get_service().get_client()
    detail = client.get(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found")
    return detail


@router.delete(
    "/api/v1/containers/{name}",
    summary="Remove a container",
    description="Delete the container and all associated resources (Deployment/StatefulSet, Services). "
    "Use `force=true` to skip confirmation.",
    response_description="Deletion confirmation.",
    responses={
        200: {"description": "Container removed"},
        404: {"description": "Container not found"},
    },
)
def remove_container(name: str, force: bool = Query(default=False)):
    """Delete a container and its resources."""
    client = get_service().get_client()
    if client.remove(name, force=force):
        return {"message": f"Container '{name}' removed"}
    raise HTTPException(status_code=404, detail=f"Container '{name}' not found")


@router.post(
    "/api/v1/containers/{name}/stop",
    summary="Stop a container",
    description="Scale the underlying workload to zero replicas. "
    "The container enters 'terminating' state while pods shut down (up to 30 s grace period), "
    "then transitions to 'stopped'. Hardware resources are released immediately.",
    response_description="Stop confirmation.",
    responses={
        200: {"description": "Container stopped (or terminating)"},
        404: {"description": "Container not found"},
    },
)
def stop_container(name: str):
    """Stop a container by scaling it to zero."""
    client = get_service().get_client()
    if client.stop(name):
        return {"message": f"Container '{name}' stopped"}
    raise HTTPException(status_code=404, detail=f"Container '{name}' not found")


@router.post(
    "/api/v1/containers/{name}/start",
    summary="Start a container",
    description="Restore a stopped container to one replica. "
    "The container enters 'pending' while the pod is scheduled and the image is pulled, "
    "then becomes 'running' once ready.",
    response_description="Start confirmation.",
    responses={
        200: {"description": "Container started (or pending)"},
        404: {"description": "Container not found"},
    },
)
def start_container(name: str):
    """Start a stopped container by scaling it to one."""
    client = get_service().get_client()
    if client.start(name):
        return {"message": f"Container '{name}' started"}
    raise HTTPException(status_code=404, detail=f"Container '{name}' not found")


@router.post(
    "/api/v1/containers/{name}/scale",
    summary="Scale replicas",
    description="Set the desired replica count for a container deployment.",
    response_description="Scale confirmation.",
    responses={
        200: {"description": "Replicas updated"},
        400: {"description": "Replicas must be >= 0"},
        404: {"description": "Container not found"},
    },
)
def scale_container(name: str, req: ScaleRequest):
    """Set the replica count."""
    if req.replicas < 0:
        raise HTTPException(status_code=400, detail="Replicas must be >= 0")
    client = get_service().get_client()
    if client.scale(name, req.replicas):
        return {"message": f"Container '{name}' scaled to {req.replicas}"}
    raise HTTPException(status_code=404, detail=f"Container '{name}' not found")


@router.get(
    "/api/v1/containers/{name}/logs",
    summary="Fetch container logs",
    description="Retrieve stdout/stderr from a container. "
    "Stream with `follow=true`, limit lines with `tail`, "
    "and target a specific pod by ordinal with `pod`.",
    response_description="Log output (text/plain).",
    responses={
        200: {"description": "Log lines"},
        500: {"description": "Log retrieval error"},
    },
)
def container_logs(
    name: str,
    follow: bool = Query(default=False),
    tail: int = Query(default=100),
    pod: int | None = Query(default=None),
):
    """Retrieve stdout/stderr logs."""
    client = get_service().get_client()
    try:
        if follow:
            resp = client.logs(name, follow=True, tail=tail, pod=pod)

            def stream():
                for line in resp:
                    yield line.decode("utf-8", errors="replace")

            return StreamingResponse(stream(), media_type="text/plain")
        else:
            output = client.logs(name, follow=False, tail=tail, pod=pod)
            return PlainTextResponse(output)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/v1/containers/{name}/exec",
    summary="Execute a command (non-interactive)",
    description="Run a one-shot command inside a container and return stdout and stderr. "
    "Not suitable for interactive TTY sessions.",
    response_description="Command output.",
    responses={
        200: {"description": "Command executed"},
        500: {"description": "Execution error or timeout"},
    },
)
def exec_container(name: str, req: ExecRequest, pod: int | None = Query(default=None)):
    """Run a one-shot command inside a container."""
    client = get_service().get_client()
    result = client.exec(name, req.command, pod=pod, tty=False, stdin=False)
    if isinstance(result, str) and result.startswith("Error"):
        raise HTTPException(status_code=500, detail=result)
    return {"output": result}


# ── Shell sessions ──────────────────────────────────────────────────────────

import pty
import select
import threading
import uuid

_sessions: dict[str, "ShellSession"] = {}
_sessions_lock = threading.Lock()


class ShellSession:
    """A persistent /bin/sh process inside a container, accessed via HTTP."""

    def __init__(self, pod_name: str, namespace: str, kubeconfig: str | None):
        self.pod_name = pod_name
        self.master_fd, slave_fd = pty.openpty()
        cmd = ["kubectl", "exec", "-it", pod_name, "-n", namespace, "--", "/bin/sh"]
        env = {**os.environ}
        if kubeconfig:
            env["KUBECONFIG"] = kubeconfig
        self.proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        self._lock = threading.Lock()
        self._drain_output()  # eat initial prompt
        # suppress prompt and echo for clean agent output
        self._setup_clean_env()

    def _setup_clean_env(self) -> None:
        """Suppress shell prompt and echo for clean agent output."""
        with self._lock:
            os.write(self.master_fd, b"export PS1=''\n")
            time.sleep(0.1)
            os.write(
                self.master_fd,
                b"stty -echo 2>/dev/null; set +o histexpand 2>/dev/null\n",
            )
            time.sleep(0.1)
            self._drain_output()

    def exec(self, command: str, timeout: float = 10) -> dict:
        """Run a command and return stdout, exit_code."""
        with self._lock:
            if self.proc.poll() is not None:
                return {"stdout": "", "exit_code": -1}

            marker = f"__KCS_EXIT_{uuid.uuid4().hex[:8]}__"
            full_cmd = f"{command}\necho {marker}$?\n"

            os.write(self.master_fd, full_cmd.encode("utf-8"))
            output = self._read_until(marker, timeout)

            # Parse exit code and clean output
            exit_code = 0
            if marker in output:
                idx = output.index(marker) + len(marker)
                try:
                    exit_code = int(output[idx : idx + 4].strip())
                except ValueError:
                    pass
                output = output[: output.index(marker)]

            # Strip ANSI escape codes and the echoed command line
            output = self._clean_output(output, command)

            return {"stdout": output, "exit_code": exit_code}

    def _clean_output(self, raw: str, command: str) -> str:
        """Strip ANSI codes and remove echoed command line from output."""
        import re

        # strip ANSI escape sequences
        cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", raw)
        cleaned = re.sub(r"\x1b\][0-9;]*[^\x07]*\x07", "", cleaned)
        # remove \r and normalize
        cleaned = cleaned.replace("\r", "")
        # remove the echoed command line (first line if it matches)
        lines = cleaned.split("\n")
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        # trim trailing blank lines
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines)

    def _read_until(self, marker: str, timeout: float) -> str:
        result = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([self.master_fd], [], [], 0.1)
            if ready:
                try:
                    buf = os.read(self.master_fd, 4096)
                except OSError:
                    break
                if not buf:
                    break
                result += buf
                if marker.encode("utf-8") in result:
                    break
            if self.proc.poll() is not None:
                # read any remaining output
                break
        return result.decode("utf-8", errors="replace")

    def _drain_output(self) -> None:
        """Read and discard initial shell prompt."""
        try:
            ready, _, _ = select.select([self.master_fd], [], [], 0.5)
            if ready:
                os.read(self.master_fd, 4096)
        except Exception:
            pass

    def close(self) -> None:
        try:
            os.write(self.master_fd, b"exit\n")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        try:
            os.close(self.master_fd)
        except Exception:
            pass


@router.post(
    "/api/v1/containers/{name}/shell/sessions",
    summary="Create a shell session",
    description="Open a persistent `/bin/sh` process inside a container. "
    "Returns a `session_id` that stays alive across commands, "
    "preserving working directory and environment variables.",
    response_description="Session ID and target pod name.",
    responses={
        200: {"description": "Session created"},
        404: {"description": "No pod found"},
    },
)
def shell_session_create(name: str, pod: int | None = Query(default=None)):
    """Open a persistent /bin/sh process inside a container."""
    client = get_service().get_client()
    pod_name = client._get_target_pod(name, pod)
    if not pod_name:
        raise HTTPException(status_code=404, detail="No pod found")

    session = ShellSession(pod_name, client.namespace, client._kubeconfig)
    sid = uuid.uuid4().hex[:12]

    with _sessions_lock:
        _sessions[sid] = session

    return {"session_id": sid, "pod": pod_name}


@router.post(
    "/api/v1/containers/{name}/shell/sessions/{sid}/exec",
    summary="Run a command in a shell session",
    description="Execute a command inside an existing shell session. "
    "Working directory, environment variables, and shell state "
    "are preserved between calls.",
    response_description="stdout and exit code.",
    responses={
        200: {"description": "Command executed"},
        404: {"description": "Session not found"},
    },
)
def shell_session_exec(name: str, sid: str, req: ExecRequest):
    """Execute a command inside an existing shell session."""
    with _sessions_lock:
        session = _sessions.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        result = session.exec(" ".join(req.command))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result


@router.delete(
    "/api/v1/containers/{name}/shell/sessions/{sid}",
    summary="Close a shell session",
    description="Terminate the shell process and release the session.",
    response_description="Closure confirmation.",
)
def shell_session_close(name: str, sid: str):
    """Close a shell session."""
    with _sessions_lock:
        session = _sessions.pop(sid, None)
    if session:
        session.close()
    return {"message": "Session closed"}


@router.get(
    "/api/v1/containers/{name}/shell/sessions",
    summary="List shell sessions",
    description="Return all active shell session IDs for a container.",
    response_description="List of session IDs.",
)
def shell_session_list(name: str):
    """List active shell sessions."""
    with _sessions_lock:
        return {"sessions": list(_sessions.keys())}


@router.get(
    "/api/v1/containers/{name}/pods",
    summary="List pods for a container",
    description="Return every pod (replica) belonging to a container, "
    "including its status, node, IP, age, and restart count.",
    response_description="Pod list with status and location.",
)
def list_container_pods(name: str):
    """List pods belonging to a container."""
    client = get_service().get_client()
    pods = client.list_pods(name)
    return {"name": name, "pods": pods}
