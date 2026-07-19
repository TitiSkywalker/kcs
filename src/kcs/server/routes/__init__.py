"""Route modules for kcs API."""

from kcs.server.routes.clusters import router as clusters_router
from kcs.server.routes.containers import router as containers_router
from kcs.server.routes.mcp_routes import router as mcp_router
from kcs.server.routes.system import router as system_router

__all__ = ["containers_router", "clusters_router", "system_router", "mcp_router"]
