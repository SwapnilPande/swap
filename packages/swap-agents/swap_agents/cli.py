"""CLI for the agents plugin."""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import click

from swap_agents import core
from swap.core import style


@click.group(name="agents")
def cli():
    """Schedule and manage background agent commands."""


@cli.command()
@click.argument("name")
@click.option("--schedule", required=True, help="Cron expression or @hourly/@daily/etc.")
@click.option("--command", "command", default=None, help="Inline shell command to run.")
@click.option(
    "--script", "script_path", default=None, type=click.Path(exists=True, dir_okay=False),
    help="Path to a script file (copied into the agent dir).",
)
@click.option("--cwd", default=None, help="Working directory for the agent.")
@click.option("--description", default="", help="Optional description.")
def add(name, schedule, command, script_path, cwd, description):
    """Create and schedule a new agent."""
    try:
        agent = core.add(
            name,
            schedule,
            command=command,
            script_source=Path(script_path) if script_path else None,
            cwd=cwd,
            description=description,
        )
    except ValueError as e:
        raise click.ClickException(str(e))

    try:
        core.get_scheduler().install(agent)
    except core.SchedulerError as e:
        click.echo(style.warn(f"Created config but scheduler install failed: {e}"))
        click.echo(style.dim("Fix the issue and run: ") + style.value(f"swap agents enable {name}"))
        return

    click.echo(f"{style.check()} {style.success(f'Agent {name!r} added.')}")
    click.echo(f"  {style.dim('Schedule:')} {style.value(agent.schedule)}")
    click.echo(f"  {style.dim('Next run:')} {style.value(_fmt_ts(core.next_run_at(agent.schedule)))}")


@cli.command()
@click.argument("name")
@click.option("--purge", is_flag=True, help="Also delete the agent's data directory.")
def remove(name, purge):
    """Remove an agent and unschedule it."""
    try:
        core.remove(name, purge=purge)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{style.check()} {style.success(f'Agent {name!r} removed.')}")
    if purge:
        click.echo(style.dim("Data directory removed."))


@cli.command(name="list")
def list_cmd():
    """List all configured agents."""
    agents = core.list_agents()
    if not agents:
        click.echo(style.dim("No agents configured. Add one with ") + style.value("swap agents add"))
        return

    click.echo(style.header("Agents"))
    for a in agents:
        state = core.read_state(a.name)
        last = state.get("last_exit_code")
        if last is None:
            status_mark = style.dim("·")
        elif last == 0:
            status_mark = style.check()
        else:
            status_mark = style.cross()

        enabled_mark = "" if a.enabled else style.warn(" (disabled)")
        line = f"  {status_mark} {style.name(a.name)}{enabled_mark}  {style.dim(a.schedule)}"
        if a.description:
            line += f"  {style.dim('— ' + a.description)}"
        click.echo(line)


@cli.command()
@click.argument("name")
def show(name):
    """Show full configuration for an agent."""
    try:
        agent = core.load(name)
    except ValueError as e:
        raise click.ClickException(str(e))

    click.echo()
    click.echo(style.header(name))
    if agent.description:
        click.echo(f"  {style.dim(agent.description)}")
    click.echo()
    click.echo(f"  {style.dim('Schedule:')}  {style.value(agent.schedule)}")
    click.echo(f"  {style.dim('Enabled:')}   {style.value(str(agent.enabled))}")
    if agent.command:
        click.echo(f"  {style.dim('Command:')}   {style.value(agent.command)}")
    if agent.script:
        click.echo(f"  {style.dim('Script:')}    {style.value(str(agent.dir / agent.script))}")
    if agent.cwd:
        click.echo(f"  {style.dim('Cwd:')}       {style.value(agent.cwd)}")
    if agent.env:
        click.echo(f"  {style.dim('Env:')}")
        for k, v in agent.env.items():
            click.echo(f"    {style.dim(k)}={style.value(v)}")
    click.echo(f"  {style.dim('Dir:')}       {style.value(str(agent.dir))}")
    click.echo(f"  {style.dim('Next run:')}  {style.value(_fmt_ts(core.next_run_at(agent.schedule)))}")


@cli.command()
@click.argument("name")
@click.option("--force", is_flag=True, help="Run even if a previous invocation holds the lock.")
@click.option("--scheduled", is_flag=True, hidden=True)
def run(name, force, scheduled):
    """Run an agent ad-hoc (or as a scheduled invocation, internally)."""
    try:
        rc = core.run(name, scheduled=scheduled, force=force)
    except core.LockHeld as e:
        raise click.ClickException(str(e))
    except ValueError as e:
        raise click.ClickException(str(e))

    if scheduled:
        # Stay quiet on scheduled runs; the launchd/systemd unit captures
        # the log already and we don't want noisy stderr in user mail.
        raise SystemExit(rc)

    if rc == 0:
        click.echo(f"{style.check()} {style.success('Done.')} ({rc})")
    else:
        click.echo(f"{style.cross()} {style.error(f'Exit code {rc}')}")
    click.echo(style.dim("Tail with: ") + style.value(f"swap agents tail {name}"))
    raise SystemExit(rc)


@cli.command()
@click.argument("name")
def tail(name):
    """Print the last_run.log for an agent."""
    if not core.exists(name):
        raise click.ClickException(f"Agent {name!r} does not exist.")
    text = core.tail_log(name)
    if not text:
        click.echo(style.dim("No log yet — agent has not run."))
        return
    click.echo(text, nl=False)


@cli.command()
@click.argument("name")
def status(name):
    """Show last/next run, exit code, and log location for an agent."""
    try:
        agent = core.load(name)
    except ValueError as e:
        raise click.ClickException(str(e))
    state = core.read_state(name)

    click.echo()
    click.echo(style.header(name))
    click.echo(f"  {style.dim('Enabled:')}    {style.value(str(agent.enabled))}")
    click.echo(f"  {style.dim('Schedule:')}   {style.value(agent.schedule)}")
    if state:
        click.echo(f"  {style.dim('Last run:')}   {style.value(_fmt_ts(state.get('last_run_at', 0)))}")
        rc = state.get("last_exit_code")
        rc_style = style.success(str(rc)) if rc == 0 else style.error(str(rc))
        click.echo(f"  {style.dim('Last exit:')}  {rc_style}")
    else:
        click.echo(f"  {style.dim('Last run:')}   {style.dim('never')}")
    click.echo(f"  {style.dim('Next run:')}   {style.value(_fmt_ts(core.next_run_at(agent.schedule)))}")
    click.echo(f"  {style.dim('Log:')}        {style.value(str(agent.dir / 'last_run.log'))}")


@cli.command()
@click.argument("name")
def enable(name):
    """Enable a disabled agent (re-installs scheduler)."""
    try:
        core.enable(name)
    except ValueError as e:
        raise click.ClickException(str(e))
    except core.SchedulerError as e:
        raise click.ClickException(str(e))
    click.echo(f"{style.check()} {style.success(f'{name} enabled.')}")


@cli.command()
@click.argument("name")
def disable(name):
    """Disable an agent (removes scheduler entry, keeps config)."""
    try:
        core.disable(name)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{style.check()} {style.success(f'{name} disabled.')}")


@cli.command()
@click.argument("name")
@click.option("--script", "edit_script", is_flag=True, help="Edit script.sh instead of agent.toml.")
def edit(name, edit_script):
    """Open the agent's config (or script) in $EDITOR."""
    try:
        agent = core.load(name)
    except ValueError as e:
        raise click.ClickException(str(e))

    if edit_script:
        if not agent.script:
            raise click.ClickException(f"Agent {name!r} has no script file.")
        target = agent.dir / agent.script
    else:
        target = agent.dir / "agent.toml"

    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.run([editor, str(target)], check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"editor exited with code {e.returncode}")

    if not edit_script:
        # If schedule changed, reinstall scheduler.
        try:
            updated = core.load(name)
        except ValueError as e:
            raise click.ClickException(str(e))
        if updated.enabled and updated.schedule != agent.schedule:
            try:
                core.get_scheduler().install(updated)
                click.echo(style.dim("Schedule updated; scheduler reinstalled."))
            except core.SchedulerError as e:
                click.echo(style.warn(f"Schedule changed but scheduler reinstall failed: {e}"))


def _fmt_ts(ts: float) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
