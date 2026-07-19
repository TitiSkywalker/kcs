"""FastAPI application factory for kcs."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from kcs import __version__
from kcs.server.routes import (
    clusters_router,
    containers_router,
    mcp_router,
    system_router,
)

log = logging.getLogger("kcs")


def create_app() -> FastAPI:
    tags_metadata = [
        {
            "name": "Containers",
            "description": "Create, inspect, start, stop, scale, and remove containers. "
            "Also includes logs, exec, and interactive shell sessions.",
        },
        {
            "name": "System",
            "description": "Cluster health, aggregated dashboard status, node listing, and info.",
        },
        {
            "name": "Images",
            "description": "Build Docker images and push to the cluster registry.",
        },
        {
            "name": "Cluster",
            "description": "Apply declarative cluster configuration — join workers, prune stale nodes.",
        },
        {
            "name": "MCP",
            "description": "Start and stop in-process MCP servers for coding-agent integration.",
        },
    ]

    app = FastAPI(
        title="kcs API",
        description="REST API for managing container workloads on a k3s cluster.",
        version=__version__,
        openapi_tags=tags_metadata,
    )

    # Static files
    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(static_dir / "index.html"))

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = (time.time() - start) * 1000
        log.info(
            "%s %s → %s (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

    # Register routers
    app.include_router(system_router)
    app.include_router(containers_router)
    app.include_router(clusters_router)
    app.include_router(mcp_router)

    return app


app = create_app()
