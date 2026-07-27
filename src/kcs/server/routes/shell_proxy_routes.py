"""Shell proxy management routes — start / stop / list shell proxies in-process."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from kcs import shell_proxy

router = APIRouter(tags=["Shell Proxy"])


class ShellProxyStartRequest(BaseModel):
    container: str
    port: int = 9876
    host: str = "127.0.0.1"


@router.get(
    "/api/v1/shell-proxy",
    summary="List running shell proxies",
    response_description="Active shell proxy ports and containers.",
)
def list_proxies():
    return {"proxies": shell_proxy.list_running()}


@router.post(
    "/api/v1/shell-proxy/start",
    status_code=201,
    summary="Start a shell proxy",
    description="Launch a shell proxy on the given port, forwarding commands into the target container.",
    responses={
        201: {"description": "Shell proxy started"},
        409: {"description": "Port already in use"},
        500: {"description": "No running pod or other startup error"},
    },
)
def start_proxy(req: ShellProxyStartRequest):
    try:
        result = shell_proxy.start(
            container=req.container,
            host=req.host,
            port=req.port,
        )
    except RuntimeError as e:
        msg = str(e)
        status = 409 if "already running" in msg.lower() else 500
        raise HTTPException(status_code=status, detail=msg)
    except OSError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


@router.post(
    "/api/v1/shell-proxy/stop",
    summary="Stop a shell proxy",
    description="Shut down the shell proxy on the given port.",
    responses={
        200: {"description": "Shell proxy stopped"},
        404: {"description": "No shell proxy on that port"},
    },
)
def stop_proxy(port: int = Query(..., description="Port of the proxy to stop")):
    try:
        shell_proxy.stop(port)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"message": f"Shell proxy on port {port} stopped"}
