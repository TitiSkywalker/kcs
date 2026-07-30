"""Shell proxy management routes — start / stop / list shell proxies in-process."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from kcs import shell_proxy

router = APIRouter(tags=["Shell Proxy"])


class ShellProxyStartRequest(BaseModel):
    container: str
    session: str = ""


@router.get(
    "/api/v1/shell-proxy",
    summary="List running shell proxies",
    response_description="Active shell proxy sockets and containers.",
)
def list_proxies():
    return {"proxies": shell_proxy.list_running()}


@router.post(
    "/api/v1/shell-proxy/start",
    status_code=201,
    summary="Start a shell proxy",
    description="Launch a shell proxy on a Unix domain socket, forwarding commands into the target container.",
    responses={
        201: {"description": "Shell proxy started"},
        409: {"description": "Proxy already running for this container/session"},
        500: {"description": "No running pod or other startup error"},
    },
)
def start_proxy(req: ShellProxyStartRequest):
    try:
        result = shell_proxy.start(
            container=req.container,
            session=req.session,
        )
    except RuntimeError as e:
        msg = str(e)
        if "already running" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=500, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


@router.post(
    "/api/v1/shell-proxy/stop",
    summary="Stop a shell proxy",
    description="Shut down the shell proxy for the given container and session.",
    responses={
        200: {"description": "Shell proxy stopped"},
        404: {"description": "No shell proxy for that container/session"},
    },
)
def stop_proxy(
    container: str = Query(..., description="Container name"),
    session: str = Query(default="", description="Session label"),
):
    try:
        shell_proxy.stop(container, session)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    label = f"{container}/{session}" if session else container
    return {"message": f"Shell proxy for {label} stopped"}
