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
