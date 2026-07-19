"""kcs controller — watch-and-reconcile loop.

Optional advanced feature: when controller mode is enabled, kcs watches Kubernetes resource changes and automatically performs reconciliation (e.g. restart crashed Pods, auto-scale, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from kcs.k8s import KCSClient

logger = logging.getLogger(__name__)


class Controller:
    """kcs controller reconciliation loop.

    Watches kcs-managed resources, ensuring actual state converges to desired state.

    Usage:
        ctrl = Controller(client)
        ctrl.register_handler("pod-crashed", handle_crash)
        await ctrl.run()
    """

    def __init__(self, client: KCSClient, interval: float = 10.0):
        self.client = client
        self.interval = interval  # reconciliation interval (seconds)
        self._handlers: dict[str, Callable] = {}
        self._running = False

    def register_handler(self, event: str, handler: Callable) -> None:
        """Register an event handler."""
        self._handlers[event] = handler
        logger.info("Registered event handler: %s → %s", event, handler.__name__)

    async def run(self) -> None:
        """Start the reconciliation loop."""
        self._running = True
        logger.info("Controller started, reconciliation interval: %.1fs", self.interval)

        while self._running:
            try:
                await self._reconcile()
            except Exception:
                logger.exception(
                    "Reconciliation loop error, retrying in %.1fs", self.interval
                )
            await asyncio.sleep(self.interval)

    async def _reconcile(self) -> None:
        """Run one reconciliation: check all resources, ensure desired state."""
        containers = self.client.list()

        for c in containers:
            # If container is in ERROR state, trigger restart
            if c.status.value == "error" and "pod-error" in self._handlers:
                await self._handlers["pod-error"](c)

            # If container has been PENDING too long, log it
            if c.status.value == "pending" and "long-pending" in self._handlers:
                await self._handlers["long-pending"](c)

    def stop(self) -> None:
        """Stop the controller."""
        self._running = False
        logger.info("Controller stopped")
