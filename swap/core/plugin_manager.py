from __future__ import annotations

import json
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


def get_installed_entry_point(plugin_name: str):
    """Return the importlib EntryPoint for an installed plugin, or None."""
    for ep in entry_points(group="swap.plugins"):
        if ep.name == plugin_name:
            return ep
    return None


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
    desc = json.dumps(description)  # produces '"some description"' with proper escaping
    return f'''\
[project]
name = "swap-{name}"
version = "0.1.0"
description = {desc}
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
