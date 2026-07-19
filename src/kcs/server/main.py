"""CLI entry point for kcs-server."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from kcs.server.services import get_service, set_service_config

log = logging.getLogger("kcs")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="kcs HTTP API server")
    parser.add_argument(
        "--host",
        default=os.environ.get("KCS_HOST", "0.0.0.0"),
        help="Listen address (env: KCS_HOST, default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KCS_PORT", 8000)),
        help="Listen port (env: KCS_PORT, default: 8000)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Cluster config file (.toml/.yaml), applied on startup",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("KCS_LOG_FILE"),
        help="Log file path (env: KCS_LOG_FILE)",
    )
    args = parser.parse_args()

    if args.log_file:
        fh = logging.FileHandler(args.log_file)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
            )
        )
        logging.getLogger().addHandler(fh)
        log.info("Logging to %s", args.log_file)

    if args.config:
        log.info("Loading config: %s", args.config)
        try:
            svc = get_service()
            config = svc.load_config_file(args.config)

            if not config.sudo_password:
                print()
                print("  sudo access is needed on this machine to:")
                print(
                    "    • read the k3s server token (/var/lib/rancher/k3s/server/token)"
                )
                print(
                    "    • configure the container registry (/etc/rancher/k3s/registries.yaml)"
                )
                print("    • manage NFS (if enabled)")
                print()
                import getpass

                pw = getpass.getpass("  local sudo password: ")
                if pw:
                    config.sudo_password = pw
                print()

            set_service_config(config)
            results = svc.apply_config()
            for r in results:
                log.info("  %s", r)
        except Exception as e:
            log.error("  %s", e)
            sys.exit(1)

        log.info("Checking cluster health...")
        get_service().repair()

    uvicorn.run("kcs.server:app", host=args.host, port=args.port, reload=False)
