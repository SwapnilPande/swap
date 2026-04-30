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
        pushed = core.push_public_key(hostname, username, password, pub_key)
        if pushed:
            _ok()
        else:
            _skip("key already in authorized_keys")

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
