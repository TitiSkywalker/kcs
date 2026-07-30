"""FastAPI application factory for kcs."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from kcs import __version__
from kcs.server.routes import (
    clusters_router,
    containers_router,
    shell_proxy_router,
    system_router,
)

log = logging.getLogger("kcs")
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


def _get_api_key() -> str | None:
    """Read the configured API key from the cluster config (if any)."""
    from kcs.server.services import get_service

    svc = get_service()
    if svc.cluster_config and svc.cluster_config.api_key:
        return svc.cluster_config.api_key
    return None


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
            "name": "Shell Proxy",
            "description": "Start and stop shell proxies for CLAUDE_CODE_SHELL integration.",
        },
    ]

    app = FastAPI(
        title="kcs API",
        description="REST API for managing container workloads on a k3s cluster.",
        version=__version__,
        openapi_tags=tags_metadata,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

    @app.middleware("http")
    async def auth(request: Request, call_next):
        api_key = _get_api_key()
        # No auth configured — allow all
        if not api_key:
            return await call_next(request)

        # Allow static files and docs without auth
        path = request.url.path
        if path == "/" or path.startswith("/static") or path in ("/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Require Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {api_key}":
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized — use Authorization: Bearer <key>"},
        )

    # Register routers
    app.include_router(system_router)
    app.include_router(containers_router)
    app.include_router(clusters_router)
    app.include_router(shell_proxy_router)

    return app


app = create_app()
