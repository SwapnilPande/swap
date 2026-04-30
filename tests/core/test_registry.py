import json
import os
import time
import pytest
import requests
from pathlib import Path
from unittest.mock import patch, MagicMock

SAMPLE_REG_A = {
    "version": 1,
    "plugins": {
        "ssh": {"description": "SSH tools", "package": "swap-ssh", "install": "swap-ssh"},
    },
}
SAMPLE_REG_B = {
    "version": 1,
    "plugins": {
        "k8s": {"description": "K8s tools", "package": "swap-k8s", "install": "swap-k8s"},
        "ssh": {"description": "SSH tools (override)", "package": "swap-ssh", "install": "swap-ssh"},
    },
}


def test_fetch_local_file(tmp_path):
    from swap.core import registry
    reg_file = tmp_path / "registry.json"
    reg_file.write_text(json.dumps(SAMPLE_REG_A))
    result = registry._fetch_source(str(reg_file))
    assert result["plugins"]["ssh"]["description"] == "SSH tools"


def test_fetch_missing_local_returns_none(tmp_path):
    from swap.core import registry
    result = registry._fetch_source(str(tmp_path / "nonexistent.json"))
    assert result is None


def test_fetch_tilde_path(tmp_path, monkeypatch):
    from swap.core import registry
    reg_file = tmp_path / "registry.json"
    reg_file.write_text(json.dumps(SAMPLE_REG_A))
    # Patch Path.home to return tmp_path
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    result = registry._fetch_source("~/registry.json")
    assert result is not None


def test_fetch_http_uses_cache_when_fresh(tmp_path, monkeypatch):
    from swap.core import registry
    monkeypatch.setattr(registry, "CACHE_DIR", tmp_path)
    url = "https://example.com/registry.json"
    cache_path = registry._cache_path(url)
    cache_path.write_text(json.dumps(SAMPLE_REG_A))
    # Make the cache appear fresh (mtime = now)
    result = registry._fetch_source(url)
    assert result["plugins"]["ssh"]["description"] == "SSH tools"


def test_fetch_http_fetches_when_cache_stale(tmp_path, monkeypatch):
    from swap.core import registry
    monkeypatch.setattr(registry, "CACHE_DIR", tmp_path)
    url = "https://example.com/registry.json"
    cache_path = registry._cache_path(url)
    cache_path.write_text(json.dumps(SAMPLE_REG_A))
    # Make the cache appear stale
    old_time = time.time() - registry.CACHE_TTL - 1
    os.utime(cache_path, (old_time, old_time))

    mock_resp = MagicMock()
    mock_resp.json.return_value = SAMPLE_REG_B
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp):
        result = registry._fetch_source(url)

    assert result["plugins"]["k8s"]["description"] == "K8s tools"


def test_get_plugins_merges_sources(tmp_path, monkeypatch):
    from swap.core import registry
    reg_a = tmp_path / "a.json"
    reg_b = tmp_path / "b.json"
    reg_a.write_text(json.dumps(SAMPLE_REG_A))
    reg_b.write_text(json.dumps(SAMPLE_REG_B))

    with patch("swap.core.config.get_registry_sources", return_value=[str(reg_a), str(reg_b)]):
        result = registry.get_plugins()

    # Both plugins present; B's ssh overrides A's ssh
    assert "ssh" in result
    assert "k8s" in result
    assert result["ssh"]["description"] == "SSH tools (override)"


def test_get_plugin_returns_none_for_unknown(tmp_path):
    from swap.core import registry
    with patch("swap.core.registry.get_plugins", return_value={}):
        assert registry.get_plugin("unknown") is None


def test_get_plugins_with_status_marks_unreachable_sources(tmp_path):
    from swap.core import registry
    reg_a = tmp_path / "a.json"
    reg_a.write_text(json.dumps(SAMPLE_REG_A))
    missing = tmp_path / "missing.json"

    with patch("swap.core.config.get_registry_sources", return_value=[str(reg_a), str(missing)]):
        plugins, statuses = registry.get_plugins_with_status()

    assert "ssh" in plugins
    assert (str(reg_a), True) in statuses
    assert (str(missing), False) in statuses


def test_get_plugins_with_status_distinguishes_empty_from_unreachable(tmp_path):
    from swap.core import registry
    reg_empty = tmp_path / "empty.json"
    reg_empty.write_text(json.dumps({"version": 1, "plugins": {}}))

    with patch("swap.core.config.get_registry_sources", return_value=[str(reg_empty)]):
        plugins, statuses = registry.get_plugins_with_status()

    # Reachable but empty — both status True AND empty plugin dict
    assert plugins == {}
    assert statuses == [(str(reg_empty), True)]


def test_fetch_http_falls_back_to_stale_cache_on_error(tmp_path, monkeypatch):
    from swap.core import registry
    monkeypatch.setattr(registry, "CACHE_DIR", tmp_path)
    url = "https://example.com/registry.json"
    cache_path = registry._cache_path(url)
    # Write stale cache (TTL expired)
    cache_path.write_text(json.dumps(SAMPLE_REG_A))
    old_time = time.time() - registry.CACHE_TTL - 1
    os.utime(cache_path, (old_time, old_time))

    with patch("requests.get", side_effect=requests.RequestException("network error")):
        result = registry._fetch_source(url)

    assert result is not None
    assert result["plugins"]["ssh"]["description"] == "SSH tools"
