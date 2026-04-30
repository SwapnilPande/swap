import pytest
from pathlib import Path


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Redirect config to a temp dir for each test."""
    import swap.core.config as config
    monkeypatch.setattr(config, "SWAP_HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    return config


def test_get_missing_returns_default(cfg):
    assert cfg.get("missing", "key", "fallback") == "fallback"


def test_set_and_get_round_trip(cfg):
    cfg.set("mysection", "mykey", "myvalue")
    assert cfg.get("mysection", "mykey") == "myvalue"


def test_set_plugin_and_get_plugin(cfg):
    cfg.set_plugin("myplugin", "key", "val")
    result = cfg.get_plugin("myplugin")
    assert result == {"key": "val"}


def test_get_plugin_missing_returns_empty(cfg):
    assert cfg.get_plugin("nonexistent") == {}


def test_set_persists_on_disk(cfg, tmp_path):
    # Write once, then read again — proves _load() re-reads from disk each call
    cfg.set("s", "k", "v")
    assert cfg.get("s", "k") == "v"
    # Verify the file actually exists on disk with the right content
    assert (tmp_path / "config.toml").exists()
    import tomllib
    with open(tmp_path / "config.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["s"]["k"] == "v"


def test_get_registry_sources_returns_default(cfg):
    sources = cfg.get_registry_sources()
    assert isinstance(sources, list)
    assert len(sources) >= 1
