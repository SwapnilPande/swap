from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from swap.core import config
    monkeypatch.setattr(config, "SWAP_HOME", tmp_path)
    monkeypatch.setattr(config, "SWAP_DATA_DIR", tmp_path / "data")
    return tmp_path


@pytest.fixture
def noop_scheduler(monkeypatch):
    from swap_agents import core

    class NoopScheduler(core.Scheduler):
        def install(self, agent): pass
        def uninstall(self, name): pass
        def is_enabled(self, name): return True

    monkeypatch.setattr(core, "get_scheduler", lambda: NoopScheduler())


def test_add_command(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "echo hi"])
    assert result.exit_code == 0, result.output
    assert "added" in result.output


def test_add_invalid_schedule(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["add", "foo", "--schedule", "nonsense", "--command", "x"])
    assert result.exit_code != 0


def test_list_shows_added(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "x"])
    runner.invoke(cli, ["add", "bar", "--schedule", "@daily", "--command", "y"])
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "foo" in result.output
    assert "bar" in result.output


def test_show_outputs_config(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "echo hi", "--description", "d"])
    result = runner.invoke(cli, ["show", "foo"])
    assert result.exit_code == 0, result.output
    assert "0 * * * *" in result.output
    assert "echo hi" in result.output


def test_remove_purge_clears_dir(isolated, noop_scheduler):
    from swap_agents.cli import cli
    from swap_agents import core
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "x"])
    d = core.agent_dir("foo")
    assert d.exists()
    result = runner.invoke(cli, ["remove", "foo", "--purge"])
    assert result.exit_code == 0, result.output
    assert not d.exists()


def test_run_executes_and_returns_exit_code(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "exit 0"])
    result = runner.invoke(cli, ["run", "foo"])
    assert result.exit_code == 0


def test_run_propagates_failure_exit_code(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "exit 3"])
    result = runner.invoke(cli, ["run", "foo"])
    assert result.exit_code == 3


def test_tail_shows_log(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "echo bananas"])
    runner.invoke(cli, ["run", "foo"])
    result = runner.invoke(cli, ["tail", "foo"])
    assert result.exit_code == 0
    assert "bananas" in result.output


def test_status_before_first_run(isolated, noop_scheduler):
    from swap_agents.cli import cli
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "x"])
    result = runner.invoke(cli, ["status", "foo"])
    assert result.exit_code == 0
    assert "never" in result.output


def test_disable_then_enable(isolated, noop_scheduler):
    from swap_agents.cli import cli
    from swap_agents import core
    runner = CliRunner()
    runner.invoke(cli, ["add", "foo", "--schedule", "@hourly", "--command", "x"])
    result = runner.invoke(cli, ["disable", "foo"])
    assert result.exit_code == 0
    assert core.load("foo").enabled is False
    result = runner.invoke(cli, ["enable", "foo"])
    assert result.exit_code == 0
    assert core.load("foo").enabled is True
