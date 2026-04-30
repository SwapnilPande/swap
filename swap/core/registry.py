from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

import requests

from swap.core import config

CACHE_DIR = Path.home() / ".swap" / "registry-cache"
CACHE_TTL = 3600  # seconds


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _fetch_source(url: str) -> Optional[dict]:
    """Fetch a registry JSON from a file path or HTTP(S) URL."""
    # Expand ~ paths using Path.home() so tests can monkeypatch it
    if url.startswith("~"):
        url = str(Path.home() / url[2:])

    # Local file
    if url.startswith("/") or (len(url) > 1 and url[1] == ":"):
        path = Path(url)
        if path.exists():
            return json.loads(path.read_text())
        return None

    # HTTP(S)
    cache = _cache_path(url)
    if cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_TTL:
        return json.loads(cache.read_text())

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
        return data
    except requests.RequestException:
        if cache.exists():
            try:
                return json.loads(cache.read_text())
            except json.JSONDecodeError:
                return None
        return None


def get_plugins() -> dict[str, dict]:
    """Return merged plugin registry from all configured sources.

    Later sources override earlier ones for the same plugin name.
    """
    return get_plugins_with_status()[0]


def get_plugins_with_status() -> tuple[dict[str, dict], list[tuple[str, bool]]]:
    """Return (merged plugins, [(source_url, reachable), ...]).

    'reachable' distinguishes a registry that returned valid JSON (even if
    its plugin list was empty) from one that 404'd or failed to parse.
    """
    sources = config.get_registry_sources()
    merged: dict[str, dict] = {}
    statuses: list[tuple[str, bool]] = []
    for source in sources:
        data = _fetch_source(source)
        reachable = data is not None and "plugins" in data
        statuses.append((source, reachable))
        if reachable:
            merged.update(data["plugins"])
    return merged, statuses


def get_plugin(name: str) -> Optional[dict]:
    return get_plugins().get(name)
