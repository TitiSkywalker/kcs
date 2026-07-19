"""MCP management routes — start / stop / list MCP servers in-process."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from kcs import mcp

log = logging.getLogger("kcs")
router = APIRouter(tags=["MCP"])


class MCPStartRequest(BaseModel):
    container: str | None = None
    port: int = 9999


@router.get(
    "/api/v1/mcp",
    summary="List running MCP servers",
    response_description="Active MCP server ports.",
)
def list_mcp():
    return {"servers": [{"port": p} for p in mcp.list_running()]}


@router.post(
    "/api/v1/mcp/start",
    status_code=201,
    summary="Start an MCP server",
    description="Launch an MCP SSE server on the given port, "
    "optionally pinning it to a container.",
    response_description="Port and container the server is bound to.",
    responses={
        201: {"description": "MCP server started"},
        409: {"description": "Port already in use"},
    },
)
def start_mcp(req: MCPStartRequest):
    import os

    if req.container:
        os.environ["KCS_CONTAINER"] = req.container
    try:
        mcp.start(port=req.port)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"port": req.port, "container": req.container}


@router.post(
    "/api/v1/mcp/stop",
    summary="Stop an MCP server",
    description="Shut down the MCP server on the given port.",
    response_description="Stop confirmation.",
    responses={
        200: {"description": "MCP server stopped"},
        404: {"description": "No MCP server on that port"},
    },
)
def stop_mcp(port: int = Query(..., description="Port of the MCP server to stop")):
    try:
        mcp.stop(port)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"message": f"MCP server on port {port} stopped"}
