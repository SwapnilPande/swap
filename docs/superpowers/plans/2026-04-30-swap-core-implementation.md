# swap Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core infrastructure for swap: plugin system, config, registry, SSH built-in plugin, and one-command installer — replacing the current flat `main.py`/`ssh_tool.py` sketch.

**Architecture:** Click-based CLI with plugin discovery via Python entry points (`swap.plugins` group). Business logic lives in `core.py` modules with no CLI imports; thin `cli.py` wrappers handle prompting and output. Config stored as TOML at `~/.swap/config.toml`.

**Tech Stack:** Python 3.12+, click, questionary, requests, tomli-w (writes), tomllib (stdlib reads), paramiko, uv tool (install/upgrade), pytest

---

## File Map

**Create:**
- `swap/__init__.py` — package marker
- `swap/cli.py` — root CLI group, plugin auto-discovery, `upgrade` command
- `swap/core/__init__.py` — package marker
- `swap/core/config.py` — TOML config read/write for global + per-plugin namespaces
- `swap/core/registry.py` — fetch + merge plugin registry from multiple sources with cache
- `swap/core/plugin_manager.py` — install, uninstall, scaffold, list plugin operations
- `swap/core/upgrade.py` — `uv tool upgrade swap`
- `swap/builtin/__init__.py` — package marker
- `swap/builtin/plugins/__init__.py` — package marker
- `swap/builtin/plugins/cli.py` — `swap plugins` command group
- `swap/builtin/ssh/__init__.py` — package marker
- `swap/builtin/ssh/core.py` — SSH business logic (keygen, push key, write config)
- `swap/builtin/ssh/cli.py` — `swap ssh` command group (questionary prompts)
- `install.sh` — one-command installer via uv tool
- `registry.json` — official plugin registry (empty plugins object for now)
- `tests/__init__.py`
- `tests/core/__init__.py`
- `tests/core/test_config.py`
- `tests/core/test_registry.py`
- `tests/core/test_plugin_manager.py`
- `tests/builtin/__init__.py`
- `tests/builtin/ssh/__init__.py`
- `tests/builtin/ssh/test_core.py`

**Modify:**
- `pyproject.toml` — new deps, new entry point, build system, register built-in plugins

**Delete:**
- `main.py` — replaced by `swap/cli.py`
- `ssh_tool.py` — replaced by `swap/builtin/ssh/`

---

## Task 1: Restructure project layout and pyproject.toml

**Files:**
- Modify: `pyproject.toml`
- Delete: `main.py`, `ssh_tool.py`
- Create: all package `__init__.py` files and directory skeletons

- [ ] **Step 1: Create directory structure**

```bash
cd /path/to/swap
mkdir -p swap/core swap/builtin/plugins swap/builtin/ssh
mkdir -p tests/core tests/builtin/ssh
touch swap/__init__.py swap/core/__init__.py
touch swap/builtin/__init__.py swap/builtin/plugins/__init__.py swap/builtin/ssh/__init__.py
touch tests/__init__.py tests/core/__init__.py
touch tests/builtin/__init__.py tests/builtin/ssh/__init__.py
```

- [ ] **Step 2: Update pyproject.toml**

Replace the entire file with:

```toml
[project]
name = "swap"
version = "0.1.0"
description = "Personal utilities CLI, extensible via plugins"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "click>=8.0",
    "questionary>=2.0",
    "requests>=2.28",
    "tomli-w>=1.0",
    "paramiko>=4.0",
]

[project.scripts]
swap = "swap.cli:cli"

[project.entry-points."swap.plugins"]
ssh = "swap.builtin.ssh.cli:cli"
plugins = "swap.builtin.plugins.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 3: Sync dependencies**

```bash
uv sync
```

Expected: uv resolves and installs questionary, requests, tomli-w. No errors.

- [ ] **Step 4: Delete old flat files**

```bash
rm main.py ssh_tool.py
```

- [ ] **Step 5: Create registry.json**

```json
{
  "version": 1,
  "plugins": {}
}
```

Save to `registry.json` at the project root.

- [ ] **Step 6: Commit skeleton**

```bash
git add -A
git commit -m "chore: restructure project layout for swap architecture"
```

---

## Task 2: core/config.py — configuration read/write

**Files:**
- Create: `swap/core/config.py`
- Create: `tests/core/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/core/test_config.py`:

```python
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
    assert cfg.get("mysection", "mykey") == "hello"  # intentionally wrong


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_config.py -v
```

Expected: ImportError or similar — `swap.core.config` doesn't exist yet.

- [ ] **Step 3: Implement swap/core/config.py**

```python
from __future__ import annotations

import tomllib
import tomli_w
from pathlib import Path
from typing import Any

SWAP_HOME = Path.home() / ".swap"
CONFIG_PATH = SWAP_HOME / "config.toml"

_DEFAULT_REGISTRY = "https://raw.githubusercontent.com/swapnil/swap/main/registry.json"


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
```

- [ ] **Step 4: Fix the intentionally-wrong assertion in the test**

In `test_set_and_get_round_trip`, change `"hello"` to `"myvalue"`.

```python
def test_set_and_get_round_trip(cfg):
    cfg.set("mysection", "mykey", "myvalue")
    assert cfg.get("mysection", "mykey") == "myvalue"
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/core/test_config.py -v
```

Expected: 7 tests pass. The `test_set_persists_across_reload` test may be tricky due to module-level constants — if it fails, verify that `monkeypatch` is correctly setting `CONFIG_PATH` on the already-imported module object.

- [ ] **Step 6: Commit**

```bash
git add swap/core/config.py tests/core/test_config.py
git commit -m "feat: add core config module with TOML read/write"
```

---

## Task 3: core/registry.py — fetch and merge plugin registries

**Files:**
- Create: `swap/core/registry.py`
- Create: `tests/core/test_registry.py`

- [ ] **Step 1: Write failing tests**

`tests/core/test_registry.py`:

```python
import json
import time
import pytest
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
    import os
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_registry.py -v
```

Expected: ImportError — `swap.core.registry` doesn't exist.

- [ ] **Step 3: Implement swap/core/registry.py**

```python
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
    # Expand ~ paths
    if url.startswith("~"):
        url = str(Path(url).expanduser())

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
    except Exception:
        if cache.exists():
            return json.loads(cache.read_text())
        return None


def get_plugins() -> dict[str, dict]:
    """Return merged plugin registry from all configured sources.
    
    Later sources override earlier ones for the same plugin name.
    """
    sources = config.get_registry_sources()
    merged: dict[str, dict] = {}
    for source in sources:
        data = _fetch_source(source)
        if data and "plugins" in data:
            merged.update(data["plugins"])
    return merged


def get_plugin(name: str) -> Optional[dict]:
    return get_plugins().get(name)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/core/test_registry.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add swap/core/registry.py tests/core/test_registry.py
git commit -m "feat: add registry module with multi-source aggregation and cache"
```

---

## Task 4: core/plugin_manager.py — install, uninstall, scaffold

**Files:**
- Create: `swap/core/plugin_manager.py`
- Create: `tests/core/test_plugin_manager.py`

- [ ] **Step 1: Write failing tests**

`tests/core/test_plugin_manager.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_scaffold_creates_expected_structure(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    assert (plugin_dir / "pyproject.toml").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "myplug" / "__init__.py").exists()
    assert (plugin_dir / "myplug" / "cli.py").exists()
    assert (plugin_dir / "myplug" / "core.py").exists()


def test_scaffold_pyproject_has_entry_point(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    content = (plugin_dir / "pyproject.toml").read_text()
    assert '[project.entry-points."swap.plugins"]' in content
    assert 'myplug = "myplug.cli:cli"' in content


def test_scaffold_pyproject_has_correct_package_name(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    content = (plugin_dir / "pyproject.toml").read_text()
    assert 'name = "swap-myplug"' in content


def test_scaffold_raises_if_dir_exists(tmp_path):
    from swap.core import plugin_manager
    plugin_manager.scaffold("myplug", tmp_path, "First")
    with pytest.raises(FileExistsError):
        plugin_manager.scaffold("myplug", tmp_path, "Second")


def test_scaffold_cli_template_has_group(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    cli_content = (plugin_dir / "myplug" / "cli.py").read_text()
    assert '@click.group(name="myplug")' in cli_content
    assert "def cli():" in cli_content


def test_scaffold_core_has_no_cli_imports(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    core_content = (plugin_dir / "myplug" / "core.py").read_text()
    assert "click" not in core_content
    assert "questionary" not in core_content


def test_is_installed_false_for_unknown():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={}):
        assert plugin_manager.is_installed("ghost") is False


def test_is_installed_true_for_known():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={"ssh": "swap-ssh"}):
        assert plugin_manager.is_installed("ssh") is True


def test_install_runs_uv_pip_install(tmp_path):
    from swap.core import plugin_manager
    registry_data = {"install": "swap-myplug", "package": "swap-myplug"}
    with patch("swap.core.registry.get_plugin", return_value=registry_data):
        with patch("subprocess.run") as mock_run:
            plugin_manager.install("myplug")
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "uv" in cmd
    assert "swap-myplug" in cmd


def test_install_raises_if_not_in_registry():
    from swap.core import plugin_manager
    with patch("swap.core.registry.get_plugin", return_value=None):
        with pytest.raises(ValueError, match="not found in registry"):
            plugin_manager.install("ghost")


def test_uninstall_raises_if_not_installed():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={}):
        with pytest.raises(ValueError, match="not installed"):
            plugin_manager.uninstall("ghost")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_plugin_manager.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement swap/core/plugin_manager.py**

```python
from __future__ import annotations

import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

from swap.core import registry


def get_installed_plugins() -> dict[str, str]:
    """Return {command_name: package_name} for all installed swap plugins."""
    result = {}
    for ep in entry_points(group="swap.plugins"):
        pkg_name = ep.dist.metadata["Name"] if ep.dist else "unknown"
        result[ep.name] = pkg_name
    return result


def is_installed(plugin_name: str) -> bool:
    return plugin_name in get_installed_plugins()


def install(plugin_name: str, upgrade: bool = False) -> None:
    info = registry.get_plugin(plugin_name)
    if not info:
        raise ValueError(f"Plugin '{plugin_name}' not found in registry.")
    install_arg = info.get("install", info.get("package", f"swap-{plugin_name}"))
    cmd = ["uv", "pip", "install", "--python", sys.executable]
    if upgrade:
        cmd.append("--upgrade")
    cmd.append(install_arg)
    subprocess.run(cmd, check=True)


def uninstall(plugin_name: str) -> None:
    installed = get_installed_plugins()
    if plugin_name not in installed:
        raise ValueError(f"Plugin '{plugin_name}' is not installed.")
    package = installed[plugin_name]
    subprocess.run(
        ["uv", "pip", "uninstall", "--python", sys.executable, package],
        check=True,
    )


def scaffold(name: str, path: Path, description: str) -> Path:
    """Create a new swap-<name> plugin project at path/swap-<name>/."""
    plugin_dir = path / f"swap-{name}"
    if plugin_dir.exists():
        raise FileExistsError(f"'{plugin_dir}' already exists.")
    pkg_dir = plugin_dir / name
    pkg_dir.mkdir(parents=True)
    (plugin_dir / "pyproject.toml").write_text(_pyproject(name, description))
    (plugin_dir / "README.md").write_text(f"# swap-{name}\n\n{description}\n")
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "cli.py").write_text(_cli_template(name, description))
    (pkg_dir / "core.py").write_text(_core_template(name))
    return plugin_dir


def _pyproject(name: str, description: str) -> str:
    return f'''\
[project]
name = "swap-{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.12"
dependencies = ["click>=8.0"]

[project.entry-points."swap.plugins"]
{name} = "{name}.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
'''


def _cli_template(name: str, description: str) -> str:
    return f'''\
import click


@click.group(name="{name}")
def cli():
    """{description}"""


@cli.command()
def example():
    """Example command."""
    click.echo("Hello from {name}!")
'''


def _core_template(name: str) -> str:
    return f'''\
"""Business logic for the {name} plugin.

No CLI imports here. Functions can be called directly by agents or other tools.
"""
'''
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/core/test_plugin_manager.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add swap/core/plugin_manager.py tests/core/test_plugin_manager.py
git commit -m "feat: add plugin_manager with install, uninstall, scaffold"
```

---

## Task 5: core/upgrade.py — self-upgrade

**Files:**
- Create: `swap/core/upgrade.py`

No dedicated tests — it's a one-liner wrapper around `uv tool upgrade`. Covered by integration.

- [ ] **Step 1: Implement swap/core/upgrade.py**

```python
from __future__ import annotations

import subprocess


def upgrade_swap() -> None:
    """Upgrade swap using uv tool upgrade."""
    subprocess.run(["uv", "tool", "upgrade", "swap"], check=True)
```

- [ ] **Step 2: Commit**

```bash
git add swap/core/upgrade.py
git commit -m "feat: add upgrade module"
```

---

## Task 6: builtin/ssh/core.py — SSH business logic

**Files:**
- Create: `swap/builtin/ssh/core.py`
- Create: `tests/builtin/ssh/test_core.py`

- [ ] **Step 1: Write failing tests**

`tests/builtin/ssh/test_core.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


def test_generate_keypair_runs_ssh_keygen(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = core.generate_keypair(key_path)
    assert result is True
    args = mock_run.call_args[0][0]
    assert "ssh-keygen" in args
    assert str(key_path) in args


def test_generate_keypair_skips_existing(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    key_path.touch()
    with patch("subprocess.run") as mock_run:
        result = core.generate_keypair(key_path)
    assert result is False
    mock_run.assert_not_called()


def test_add_config_entry_creates_new_file(tmp_path):
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("myserver", "192.168.1.1", "ubuntu", key_path, config_path)
    assert result is True
    content = config_path.read_text()
    assert "Host myserver" in content
    assert "HostName 192.168.1.1" in content
    assert "User ubuntu" in content
    assert str(key_path) in content


def test_add_config_entry_appends_to_existing(tmp_path):
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    config_path.write_text("Host existing\n    HostName 10.0.0.1\n")
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("newhost", "10.0.0.2", "root", key_path, config_path)
    assert result is True
    content = config_path.read_text()
    assert "Host existing" in content
    assert "Host newhost" in content


def test_add_config_entry_skips_duplicate_alias(tmp_path):
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    config_path.write_text("Host myserver\n    HostName 10.0.0.1\n")
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("myserver", "10.0.0.2", "root", key_path, config_path)
    assert result is False
    # File should not be changed
    assert "10.0.0.2" not in config_path.read_text()


def test_push_public_key_calls_exec_command(tmp_path):
    from swap.builtin.ssh import core
    mock_channel = MagicMock()
    mock_channel.recv_exit_status.return_value = 0
    mock_stdout = MagicMock()
    mock_stdout.channel = mock_channel
    mock_client = MagicMock()
    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    with patch("paramiko.SSHClient", return_value=mock_client):
        core.push_public_key("host", "user", "pass", "ssh-ed25519 AAAA...")

    mock_client.connect.assert_called_once_with("host", username="user", password="pass", timeout=10)
    mock_client.exec_command.assert_called_once()
    cmd_arg = mock_client.exec_command.call_args[0][0]
    assert "authorized_keys" in cmd_arg
    mock_client.close.assert_called_once()


def test_push_public_key_raises_on_nonzero_exit():
    from swap.builtin.ssh import core
    mock_channel = MagicMock()
    mock_channel.recv_exit_status.return_value = 1
    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b"permission denied"
    mock_stdout = MagicMock()
    mock_stdout.channel = mock_channel
    mock_client = MagicMock()
    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

    with patch("paramiko.SSHClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Failed to push key"):
            core.push_public_key("host", "user", "pass", "ssh-ed25519 AAAA...")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/builtin/ssh/test_core.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement swap/builtin/ssh/core.py**

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paramiko


@dataclass
class SSHSetupResult:
    alias: str
    hostname: str
    username: str
    key_path: Path
    key_generated: bool
    key_pushed: bool
    config_updated: bool


def generate_keypair(key_path: Path, key_type: str = "ed25519") -> bool:
    """Generate an SSH keypair at key_path. Returns True if generated, False if already existed."""
    if key_path.exists():
        return False
    key_path.parent.mkdir(mode=0o700, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-t", key_type, "-f", str(key_path), "-N", ""],
        check=True,
        capture_output=True,
    )
    return True


def push_public_key(hostname: str, username: str, password: str, pub_key: str) -> None:
    """Append pub_key to authorized_keys on the remote host via SSH."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password, timeout=10)
    try:
        cmd = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"echo '{pub_key}' >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys"
        )
        _, stdout, stderr = client.exec_command(cmd)
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError(f"Failed to push key: {stderr.read().decode()}")
    finally:
        client.close()


def add_config_entry(
    alias: str,
    hostname: str,
    username: str,
    key_path: Path,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a Host block to the SSH config file.

    Returns True if written, False if the alias already existed.
    config_path defaults to ~/.ssh/config (override for testing).
    """
    if config_path is None:
        config_path = Path.home() / ".ssh" / "config"

    entry = f"\nHost {alias}\n    HostName {hostname}\n    User {username}\n    IdentityFile {key_path}\n"

    if config_path.exists():
        content = config_path.read_text()
        if f"Host {alias}" in content:
            return False
        config_path.write_text(content + entry)
    else:
        config_path.parent.mkdir(mode=0o700, exist_ok=True)
        config_path.write_text(entry.lstrip())
    return True


def setup(
    alias: str,
    hostname: str,
    username: str,
    key_name: str,
    password: str,
    key_type: str = "ed25519",
) -> SSHSetupResult:
    """Full SSH setup: generate keypair, push to remote, update local config."""
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    key_path = ssh_dir / key_name

    key_generated = generate_keypair(key_path, key_type)
    pub_key = key_path.with_suffix(".pub").read_text().strip()
    push_public_key(hostname, username, password, pub_key)
    config_updated = add_config_entry(alias, hostname, username, key_path)

    return SSHSetupResult(
        alias=alias,
        hostname=hostname,
        username=username,
        key_path=key_path,
        key_generated=key_generated,
        key_pushed=True,
        config_updated=config_updated,
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/builtin/ssh/test_core.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add swap/builtin/ssh/core.py tests/builtin/ssh/test_core.py
git commit -m "feat: add ssh/core with keygen, push key, config entry"
```

---

## Task 7: builtin/ssh/cli.py — SSH commands with questionary prompts

**Files:**
- Create: `swap/builtin/ssh/cli.py`

No unit tests for CLI wrappers — covered by integration smoke test in Task 9.

- [ ] **Step 1: Implement swap/builtin/ssh/cli.py**

```python
from __future__ import annotations

from pathlib import Path

import click
import questionary

from swap.builtin.ssh import core


@click.group(name="ssh")
def cli():
    """SSH key management and host configuration."""


@cli.command()
@click.option("--alias", help="Host alias (used in ssh <alias>)")
@click.option("--host", "hostname", help="IP address or hostname")
@click.option("--user", "username", help="SSH username")
@click.option("--key", "key_name", help="Key filename, e.g. id_ed25519_myserver")
@click.option("--password", help="Remote password (for initial key push)")
@click.option("--key-type", default="ed25519", show_default=True, help="Key type")
def setup(alias, hostname, username, key_name, password, key_type):
    """Set up SSH key authentication for a new host.

    Run without flags to be prompted interactively.
    """
    if not alias:
        alias = questionary.text("Host alias:").ask()
    if not hostname:
        hostname = questionary.text("IP/Hostname:").ask()
    if not username:
        username = questionary.text("Username:").ask()
    if not key_name:
        key_name = questionary.text(
            "Key name:", default=f"id_{key_type}_{alias}"
        ).ask()
    if not password:
        password = questionary.password("Password:").ask()

    if not all([alias, hostname, username, key_name, password]):
        raise click.ClickException("All fields are required.")

    click.echo()
    try:
        _step("Generating key pair...  ")
        ssh_dir = Path.home() / ".ssh"
        key_path = ssh_dir / key_name
        generated = core.generate_keypair(key_path, key_type)
        if generated:
            _ok()
        else:
            _skip(f"key {key_name} already exists")

        _step("Pushing public key...   ")
        pub_key = key_path.with_suffix(".pub").read_text().strip()
        core.push_public_key(hostname, username, password, pub_key)
        _ok()

        _step("Updating ~/.ssh/config  ")
        updated = core.add_config_entry(alias, hostname, username, key_path)
        if updated:
            _ok()
        else:
            _skip(f"alias '{alias}' already in config")

    except Exception as e:
        click.echo()
        raise click.ClickException(str(e))

    click.echo()
    click.echo("Done. Connect with: ", nl=False)
    click.secho(f"ssh {alias}", fg="cyan")


def _step(msg: str) -> None:
    click.echo(f"  {msg}", nl=False)


def _ok() -> None:
    click.secho("✓", fg="green")


def _skip(reason: str) -> None:
    click.secho(f"skipped ({reason})", fg="yellow")
```

- [ ] **Step 2: Commit**

```bash
git add swap/builtin/ssh/cli.py
git commit -m "feat: add ssh cli with questionary interactive prompts"
```

---

## Task 8: builtin/plugins/cli.py — plugin management commands

**Files:**
- Create: `swap/builtin/plugins/cli.py`

- [ ] **Step 1: Implement swap/builtin/plugins/cli.py**

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from swap.core import plugin_manager, registry


@click.group(name="plugins")
def cli():
    """Browse, install, and manage swap plugins."""


@cli.command(name="list")
def list_plugins():
    """List available plugins and installation status."""
    available = registry.get_plugins()
    installed = plugin_manager.get_installed_plugins()

    if not available:
        click.secho("Registry unavailable. Installed plugins:", fg="yellow")
        for name in sorted(installed):
            click.secho(f"  ✓ {name}", fg="green")
        return

    for name, info in sorted(available.items()):
        desc = info.get("description", "")
        marker = click.style("✓", fg="green") if name in installed else " "
        click.echo(f"  {marker} {name}  —  {desc}")


@cli.command()
@click.argument("name")
@click.option("--upgrade", is_flag=True, help="Re-install even if already installed.")
def install(name: str, upgrade: bool):
    """Install a plugin by name."""
    if plugin_manager.is_installed(name) and not upgrade:
        click.secho(f"'{name}' is already installed. Use --upgrade to re-install.", fg="yellow")
        return
    click.echo(f"Installing {name}...")
    try:
        plugin_manager.install(name, upgrade=upgrade)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.secho(f"✓ {name} installed.", fg="green")


@cli.command()
@click.argument("name")
def uninstall(name: str):
    """Uninstall a plugin."""
    try:
        plugin_manager.uninstall(name)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.secho(f"✓ {name} uninstalled.", fg="green")


@cli.command()
@click.argument("name")
def upgrade(name: str):
    """Upgrade an installed plugin."""
    if not plugin_manager.is_installed(name):
        raise click.ClickException(f"'{name}' is not installed.")
    click.echo(f"Upgrading {name}...")
    try:
        plugin_manager.install(name, upgrade=True)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.secho(f"✓ {name} upgraded.", fg="green")


@cli.command()
@click.argument("name")
@click.option("--path", default=".", show_default=True, type=click.Path(), help="Directory to create the plugin in.")
def new(name: str, path: str):
    """Scaffold a new plugin project."""
    description = click.prompt("Short description")
    try:
        plugin_dir = plugin_manager.scaffold(name, Path(path).resolve(), description)
    except FileExistsError as e:
        raise click.ClickException(str(e))
    click.secho(f"\n✓ Created {plugin_dir}", fg="green")
    click.echo("\nNext steps:")
    click.echo(f"  cd {plugin_dir}")
    click.echo(f"  swap plugins dev {plugin_dir}")


@cli.command(name="dev")
@click.argument("path", type=click.Path(exists=True))
def dev_install(path: str):
    """Install a plugin in editable mode from a local path."""
    subprocess.run(
        ["uv", "pip", "install", "--python", sys.executable, "--editable", path],
        check=True,
    )
    click.secho("✓ Installed in dev mode.", fg="green")


@cli.command(name="registry-info")
@click.argument("path", type=click.Path(exists=True))
def registry_info(path: str):
    """Print the registry entry JSON for a plugin directory."""
    import tomllib
    plugin_dir = Path(path).resolve()
    toml_path = plugin_dir / "pyproject.toml"
    if not toml_path.exists():
        raise click.ClickException(f"No pyproject.toml found in {plugin_dir}")
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    project = data.get("project", {})
    name = project.get("name", "").replace("swap-", "")
    description = project.get("description", "")
    entry = {
        name: {
            "description": description,
            "package": project.get("name", ""),
            "install": project.get("name", ""),
        }
    }
    click.echo(json.dumps(entry, indent=2))
```

- [ ] **Step 2: Commit**

```bash
git add swap/builtin/plugins/cli.py
git commit -m "feat: add plugins cli with list, install, uninstall, new, dev, registry-info"
```

---

## Task 9: swap/cli.py — root CLI entry point

**Files:**
- Create: `swap/cli.py`

- [ ] **Step 1: Implement swap/cli.py**

```python
from __future__ import annotations

import click
from importlib.metadata import entry_points, version, PackageNotFoundError


def _version() -> str:
    try:
        return version("swap")
    except PackageNotFoundError:
        return "dev"


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """swap — personal utilities, extensible via plugins."""
    if ctx.invoked_subcommand is None:
        v = _version()
        installed = sorted(ep.name for ep in entry_points(group="swap.plugins"))
        click.echo(f"swap v{v}\n")
        if installed:
            click.echo(f"Installed plugins: {', '.join(installed)}")
        else:
            click.secho("No plugins installed yet.", fg="yellow")
        click.echo("\nRun 'swap <plugin>' to use it, 'swap plugins list' to browse.")


@cli.command()
def upgrade():
    """Upgrade swap to the latest version."""
    from swap.core import upgrade as _upgrade
    click.echo("Upgrading swap...")
    _upgrade.upgrade_swap()
    click.secho("✓ Upgraded.", fg="green")


# Auto-register all installed swap plugins (including built-ins via entry-points)
for _ep in entry_points(group="swap.plugins"):
    cli.add_command(_ep.load())
```

- [ ] **Step 2: Verify the CLI is importable**

```bash
uv run python -c "from swap.cli import cli; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify `swap` command works**

```bash
uv run swap
```

Expected: Shows `swap vX.Y.Z`, lists installed plugins (at minimum `ssh` and `plugins`), and the run-subcommand prompt.

- [ ] **Step 4: Verify --help works**

```bash
uv run swap --help
uv run swap ssh --help
uv run swap plugins --help
```

Expected: Standard click help text for each.

- [ ] **Step 5: Commit**

```bash
git add swap/cli.py
git commit -m "feat: add root CLI with plugin auto-discovery"
```

---

## Task 10: install.sh — one-command installer

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Write install.sh**

```bash
#!/usr/bin/env bash
set -e

echo "Installing swap..."

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo "  uv not found, installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env"
fi

# Install swap as a uv tool
uv tool install git+https://github.com/swapnil/swap

echo ""
echo "swap installed. Run 'swap' to get started."
```

- [ ] **Step 2: Make it executable and verify syntax**

```bash
chmod +x install.sh
bash -n install.sh
```

Expected: no output (syntax valid).

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "feat: add one-command installer via uv tool install"
```

---

## Task 11: Integration smoke test

Verify the whole system works end-to-end in the current dev environment.

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass. Note which tests were skipped (if any).

- [ ] **Step 2: Verify `swap` entry point**

```bash
uv run swap
uv run swap ssh --help
uv run swap plugins --help
uv run swap plugins list
```

Expected:
- `swap` → shows version and plugin list
- `swap ssh --help` → shows `setup` subcommand
- `swap plugins --help` → shows `list`, `install`, `uninstall`, `upgrade`, `new`, `dev`, `registry-info`
- `swap plugins list` → no plugins from registry (registry.json is empty), but no crash

- [ ] **Step 3: Verify scaffold creates a valid project**

```bash
cd /tmp
uv run swap plugins new testplug
# Enter description: "A test plugin"
ls -la /tmp/swap-testplug/
cat /tmp/swap-testplug/pyproject.toml
```

Expected: directory created with pyproject.toml, README.md, testplug/cli.py, testplug/core.py.

- [ ] **Step 4: Commit and tag**

```bash
git add -A
git commit -m "chore: complete core infrastructure implementation"
git tag v0.1.0
```

---

## Self-Review

**Spec coverage check:**
- ✅ Project layout matches spec exactly
- ✅ Plugin discovery via `swap.plugins` entry points
- ✅ Registry with multi-source aggregation and file cache
- ✅ Config read/write (TOML) with plugin namespaces
- ✅ Plugin install/uninstall via `uv pip install --python sys.executable`
- ✅ Plugin scaffold with `pyproject.toml`, `cli.py`, `core.py`
- ✅ `swap plugins dev <path>` editable install
- ✅ `swap plugins registry-info` for publishing
- ✅ SSH core.py with zero CLI imports
- ✅ SSH cli.py with questionary prompts + flag fallback
- ✅ `swap upgrade` via `uv tool upgrade`
- ✅ `install.sh` one-liner via `uv tool install`
- ✅ Minimal dashboard on bare `swap` invocation
- ✅ TDD throughout (tests before implementation)

**Deferred per spec (not missing):**
- `swap config get/set/list` CLI commands
- Windows support
- Any plugins beyond ssh and plugins
