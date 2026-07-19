"""kcs configuration management — read/write ~/.kcs/config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".kcs"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


def _default() -> dict:
    return {"built_images": {}}


def load() -> dict:
    if DEFAULT_CONFIG_FILE.exists():
        with open(DEFAULT_CONFIG_FILE) as f:
            return yaml.safe_load(f) or _default()
    return _default()


def save(config: dict) -> None:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_registry() -> dict | None:
    cfg = load()
    return cfg.get("cluster_registry")


def set_cluster_registry(host: str, internal_port: str, external_port: str) -> None:
    cfg = load()
    cfg["cluster_registry"] = {
        "host": host,
        "internal_port": internal_port,
        "external_port": external_port,
    }
    save(cfg)


def add_built_image(tag: str) -> None:
    cfg = load()
    if "built_images" not in cfg:
        cfg["built_images"] = {}
    cfg["built_images"][tag] = True
    save(cfg)


def remove_built_image(tag: str) -> bool:
    cfg = load()
    if tag not in cfg.get("built_images", {}):
        return False
    del cfg["built_images"][tag]
    save(cfg)
    return True


def is_built_image(tag: str) -> bool:
    cfg = load()
    return tag in cfg.get("built_images", {})
