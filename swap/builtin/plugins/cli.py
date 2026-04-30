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
    available, statuses = registry.get_plugins_with_status()
    installed = plugin_manager.get_installed_plugins()
    any_reachable = any(reachable for _, reachable in statuses)

    if not any_reachable:
        click.echo(style.warn("Registry unreachable.") + style.dim(" Showing installed plugins only:"))
        click.echo()
        for name in sorted(installed):
            click.echo(f"  {style.check()} {style.name(name)}")
        click.echo()
        click.echo(style.dim("Sources tried:"))
        for source, _ in statuses:
            click.echo(f"  {style.bullet()} {style.dim(source)}")
        return

    if not available:
        click.echo(style.dim("Registry is empty — no plugins published yet."))
        if installed:
            click.echo()
            click.echo(style.header("Installed plugins"))
            for name in sorted(installed):
                click.echo(f"  {style.check()} {style.name(name)}")
        return

    click.echo(style.header("Available plugins"))
    for name, info in sorted(available.items()):
        desc = info.get("description", "")
        marker = style.check() if name in installed else style.bullet()
        line = f"  {marker} {style.name(name)}"
        if desc:
            line += f"  {style.dim('— ' + desc)}"
        click.echo(line)
    click.echo()
    click.echo(
        style.dim("Install with ")
        + style.value("swap plugins install <name>")
        + style.dim(", or run ")
        + style.value("swap plugins info <name>")
        + style.dim(" for details.")
    )


@cli.command()
@click.argument("name")
def info(name: str):
    """Show detailed information about a plugin."""
    registry_entry = registry.get_plugin(name) or {}
    ep = plugin_manager.get_installed_entry_point(name)
    installed = ep is not None

    if not registry_entry and not installed:
        raise click.ClickException(
            f"No plugin named '{name}' is installed or published in the registry."
        )

    click.echo()
    click.echo(f"{style.header(name)}")
    description = registry_entry.get("description") or _loaded_help(ep)
    if description:
        click.echo(f"  {style.dim(description)}")
    click.echo()

    if installed:
        pkg_name = ep.dist.metadata["Name"] if ep.dist else "unknown"
        pkg_version = ep.dist.version if ep.dist else "unknown"
        click.echo(f"  {style.dim('Status:')}     {style.success('installed')}")
        click.echo(f"  {style.dim('Package:')}    {style.value(pkg_name)} {style.dim(f'v{pkg_version}')}")
    else:
        click.echo(f"  {style.dim('Status:')}     {style.warn('not installed')}")
        if registry_entry.get("install"):
            click.echo(
                f"  {style.dim('Install:')}    "
                + style.value(f"swap plugins install {name}")
            )

    if registry_entry.get("install"):
        click.echo(f"  {style.dim('Source:')}     {style.value(registry_entry['install'])}")

    if installed:
        commands = _list_commands(ep)
        if commands:
            click.echo()
            click.echo(style.header("Commands"))
            width = max(len(c[0]) for c in commands)
            for cmd_name, cmd_help in commands:
                line = f"  {style.name(cmd_name.ljust(width))}"
                if cmd_help:
                    line += f"  {style.dim(cmd_help)}"
                click.echo(line)
            click.echo()
            click.echo(
                style.dim("Run ")
                + style.value(f"swap {name} <command> --help")
                + style.dim(" for usage.")
            )


def _loaded_help(ep) -> str:
    if ep is None:
        return ""
    try:
        cmd = ep.load()
        if isinstance(cmd, click.Command) and cmd.help:
            return cmd.help.strip().splitlines()[0]
    except Exception:
        pass
    return ""


def _list_commands(ep) -> list[tuple[str, str]]:
    """Return [(subcommand_name, short_help), ...] for a plugin's Click group."""
    try:
        cmd = ep.load()
    except Exception:
        return []
    if not isinstance(cmd, click.Group):
        return []
    out: list[tuple[str, str]] = []
    for sub_name, sub_cmd in sorted(cmd.commands.items()):
        short = (sub_cmd.help or "").strip().splitlines()[0] if sub_cmd.help else ""
        out.append((sub_name, short))
    return out


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
