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


def test_set_and_get_correct(cfg):
    cfg.set("mysection", "mykey", "myvalue")
    assert cfg.get("mysection", "mykey") == "myvalue"


def test_set_plugin_and_get_plugin(cfg):
    cfg.set_plugin("myplugin", "key", "val")
    result = cfg.get_plugin("myplugin")
    assert result == {"key": "val"}


def test_get_plugin_missing_returns_empty(cfg):
    assert cfg.get_plugin("nonexistent") == {}


def test_set_persists_across_reload(cfg, tmp_path):
    cfg.set("s", "k", "v")
    # Re-import forces a fresh read from disk
    import importlib
    import swap.core.config as config
    importlib.reload(config)
    import swap.core.config as config2
    config2.SWAP_HOME = tmp_path
    config2.CONFIG_PATH = tmp_path / "config.toml"
    assert config2.get("s", "k") == "v"


def test_get_registry_sources_returns_default(cfg):
    sources = cfg.get_registry_sources()
    assert isinstance(sources, list)
    assert len(sources) >= 1
