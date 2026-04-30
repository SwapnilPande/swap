from __future__ import annotations

import click
from importlib.metadata import entry_points, version, PackageNotFoundError

from swap.core import style


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
        plugins = sorted(entry_points(group="swap.plugins"), key=lambda ep: ep.name)
        click.echo(f"{style.header('swap')} {style.dim(f'v{v}')}")
        click.echo()
        if plugins:
            click.echo(style.header("Installed plugins"))
            for ep in plugins:
                desc = _plugin_short_help(ep)
                line = f"  {style.bullet()} {style.name(ep.name)}"
                if desc:
                    line += f"  {style.dim(desc)}"
                click.echo(line)
            click.echo()
            click.echo(
                style.dim("Run ")
                + style.value("swap plugins info <name>")
                + style.dim(" for details, or ")
                + style.value("swap plugins list")
                + style.dim(" to browse more.")
            )
        else:
            click.echo(style.warn("No plugins installed yet."))
            click.echo()
            click.echo(
                style.dim("Run ") + style.value("swap plugins list") + style.dim(" to browse available plugins.")
            )


def _plugin_short_help(ep) -> str:
    """Best-effort short description for a plugin entry point.

    Loads the Click group's help docstring without forcing a second load.
    """
    try:
        cmd = ep.load()
        if isinstance(cmd, click.Command) and cmd.help:
            return cmd.help.strip().splitlines()[0]
    except Exception:
        pass
    return ""


@cli.command()
def upgrade():
    """Upgrade swap to the latest version."""
    from swap.core import upgrade as _upgrade
    click.echo(style.dim("Upgrading swap..."))
    _upgrade.upgrade_swap()
    click.echo(f"{style.check()} {style.success('Upgraded.')}")


# Auto-register all installed swap plugins (including built-ins via entry-points)
for _ep in entry_points(group="swap.plugins"):
    cli.add_command(_ep.load())
