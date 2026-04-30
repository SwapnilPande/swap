from __future__ import annotations

import tomllib
import tomli_w
from pathlib import Path
from typing import Any

SWAP_HOME = Path.home() / ".swap"
CONFIG_PATH = SWAP_HOME / "config.toml"

_DEFAULT_REGISTRY = "https://raw.githubusercontent.com/SwapnilPande/swap/main/registry.json"


def _load() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _save(data: dict) -> None:
    SWAP_HOME.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(data, f)


def get(section: str, key: str, default: Any = None) -> Any:
    return _load().get(section, {}).get(key, default)


def set(section: str, key: str, value: Any) -> None:
    data = _load()
    data.setdefault(section, {})[key] = value
    _save(data)


def get_plugin(plugin_name: str) -> dict:
    return _load().get("plugins", {}).get(plugin_name, {})


def set_plugin(plugin_name: str, key: str, value: Any) -> None:
    data = _load()
    data.setdefault("plugins", {}).setdefault(plugin_name, {})[key] = value
    _save(data)


def get_registry_sources() -> list[str]:
    return get("registries", "sources", [_DEFAULT_REGISTRY])
