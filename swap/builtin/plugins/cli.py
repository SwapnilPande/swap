from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from swap.core import plugin_manager, registry, style


@click.group(name="plugins")
def cli():
    """Browse, install, and manage swap plugins."""


@cli.command(name="list")
def list_plugins():
    """List available plugins and installation status."""
    available = registry.get_plugins()
    installed = plugin_manager.get_installed_plugins()

    if not available:
        click.echo(style.warn("Registry unavailable.") + style.dim(" Showing installed plugins only:"))
        click.echo()
        for name in sorted(installed):
            click.echo(f"  {style.check()} {style.name(name)}")
        return

    click.echo(style.header("Available plugins"))
    for name, info in sorted(available.items()):
        desc = info.get("description", "")
        if name in installed:
            marker = style.check()
        else:
            marker = style.bullet()
        line = f"  {marker} {style.name(name)}"
        if desc:
            line += f"  {style.dim('— ' + desc)}"
        click.echo(line)
    click.echo()
    click.echo(
        style.dim("Install with ")
        + style.value("swap plugins install <name>")
        + style.dim(".")
    )


@cli.command()
@click.argument("name")
@click.option("--upgrade", is_flag=True, help="Re-install even if already installed.")
def install(name: str, upgrade: bool):
    """Install a plugin by name."""
    if plugin_manager.is_installed(name) and not upgrade:
        click.echo(
            style.warn(f"'{name}' is already installed.")
            + style.dim(" Use --upgrade to re-install.")
        )
        return
    click.echo(style.dim(f"Installing {name}..."))
    try:
        plugin_manager.install(name, upgrade=upgrade)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{style.check()} {style.success(f'{name} installed.')}")


@cli.command()
@click.argument("name")
def uninstall(name: str):
    """Uninstall a plugin."""
    try:
        plugin_manager.uninstall(name)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{style.check()} {style.success(f'{name} uninstalled.')}")


@cli.command()
@click.argument("name")
def upgrade(name: str):
    """Upgrade an installed plugin."""
    if not plugin_manager.is_installed(name):
        raise click.ClickException(f"'{name}' is not installed.")
    click.echo(style.dim(f"Upgrading {name}..."))
    try:
        plugin_manager.install(name, upgrade=True)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{style.check()} {style.success(f'{name} upgraded.')}")


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
    click.echo()
    click.echo(f"{style.check()} {style.success(f'Created {plugin_dir}')}")
    click.echo()
    click.echo(style.header("Next steps"))
    click.echo(f"  {style.dim('cd')} {style.value(str(plugin_dir))}")
    click.echo(f"  {style.dim('swap plugins dev')} {style.value(str(plugin_dir))}")


@cli.command(name="dev")
@click.argument("path", type=click.Path(exists=True))
def dev_install(path: str):
    """Install a plugin in editable mode from a local path."""
    try:
        subprocess.run(
            ["uv", "pip", "install", "--python", sys.executable, "--editable", path],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"uv pip install failed (exit code {e.returncode})")
    click.echo(f"{style.check()} {style.success('Installed in dev mode.')}")


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
