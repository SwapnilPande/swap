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
