from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_swap_home(tmp_path, monkeypatch):
    from swap.core import config
    monkeypatch.setattr(config, "SWAP_HOME", tmp_path)
    monkeypatch.setattr(config, "SWAP_DATA_DIR", tmp_path / "data")
    yield tmp_path


# --- name validation ---------------------------------------------------------


def test_validate_name_accepts_simple(isolated_swap_home):
    from swap_agents import core
    core.validate_name("triage")
    core.validate_name("my-agent_1")


@pytest.mark.parametrize("bad", ["", "/foo", "..", "with space", "-leading", "a" * 65])
def test_validate_name_rejects_bad(isolated_swap_home, bad):
    from swap_agents import core
    with pytest.raises(ValueError):
        core.validate_name(bad)


# --- schedule validation -----------------------------------------------------


def test_validate_schedule_expands_macros(isolated_swap_home):
    from swap_agents import core
    assert core.validate_schedule("@hourly") == "0 * * * *"
    assert core.validate_schedule("@daily") == "0 0 * * *"


def test_validate_schedule_rejects_garbage(isolated_swap_home):
    from swap_agents import core
    with pytest.raises(ValueError):
        core.validate_schedule("nope")
    with pytest.raises(ValueError):
        core.validate_schedule("0 * * *")  # only 4 fields


def test_validate_schedule_accepts_steps(isolated_swap_home):
    from swap_agents import core
    assert core.validate_schedule("*/5 * * * *") == "*/5 * * * *"


def test_next_run_at_returns_future(isolated_swap_home):
    from swap_agents import core
    base = 0.0
    nxt = core.next_run_at("@hourly", base=base)
    assert nxt > base


# --- CRUD --------------------------------------------------------------------


def test_add_creates_config(isolated_swap_home):
    from swap_agents import core
    a = core.add("foo", "@hourly", command="echo hello")
    assert a.name == "foo"
    assert a.schedule == "0 * * * *"
    assert a.command == "echo hello"
    assert (a.dir / "agent.toml").exists()


def test_add_rejects_duplicate(isolated_swap_home):
    from swap_agents import core
    core.add("foo", "@hourly", command="echo")
    with pytest.raises(ValueError, match="already exists"):
        core.add("foo", "@hourly", command="echo")


def test_add_requires_command_or_script(isolated_swap_home):
    from swap_agents import core
    with pytest.raises(ValueError):
        core.add("foo", "@hourly")
    with pytest.raises(ValueError):
        core.add("foo", "@hourly", command="x", script_source=Path("/etc/hostname"))


def test_add_with_script_copies_and_chmod(tmp_path, isolated_swap_home):
    from swap_agents import core
    src = tmp_path / "in.sh"
    src.write_text("#!/bin/sh\necho hi\n")
    a = core.add("foo", "@hourly", script_source=src)
    dest = a.dir / "script.sh"
    assert dest.exists()
    assert dest.read_text() == src.read_text()
    assert dest.stat().st_mode & 0o111  # executable bit


def test_load_round_trip(isolated_swap_home):
    from swap_agents import core
    core.add("foo", "@hourly", command="echo hi", description="my agent")
    a = core.load("foo")
    assert a.command == "echo hi"
    assert a.description == "my agent"
    assert a.enabled is True


def test_list_agents_returns_only_valid(isolated_swap_home):
    from swap_agents import core
    core.add("foo", "@hourly", command="x")
    core.add("bar", "@daily", command="y")
    # Stray dir without agent.toml should be ignored
    (core.agents_dir() / "stray").mkdir()
    names = [a.name for a in core.list_agents()]
    assert names == ["bar", "foo"]


def test_remove_purge_clears_dir(isolated_swap_home, monkeypatch):
    from swap_agents import core

    class NoopScheduler(core.Scheduler):
        def install(self, agent): pass
        def uninstall(self, name): pass
        def is_enabled(self, name): return False

    monkeypatch.setattr(core, "get_scheduler", lambda: NoopScheduler())
    core.add("foo", "@hourly", command="x")
    d = core.agent_dir("foo")
    assert d.exists()
    core.remove("foo", purge=True)
    assert not d.exists()


def test_remove_without_purge_keeps_dir(isolated_swap_home, monkeypatch):
    from swap_agents import core

    class NoopScheduler(core.Scheduler):
        def install(self, agent): pass
        def uninstall(self, name): pass
        def is_enabled(self, name): return False

    monkeypatch.setattr(core, "get_scheduler", lambda: NoopScheduler())
    core.add("foo", "@hourly", command="x")
    d = core.agent_dir("foo")
    core.remove("foo")
    assert d.exists()


def test_enable_disable_round_trip(isolated_swap_home, monkeypatch):
    from swap_agents import core

    installs: list[str] = []
    uninstalls: list[str] = []

    class TrackingScheduler(core.Scheduler):
        def install(self, agent): installs.append(agent.name)
        def uninstall(self, name): uninstalls.append(name)
        def is_enabled(self, name): return True

    monkeypatch.setattr(core, "get_scheduler", lambda: TrackingScheduler())
    core.add("foo", "@hourly", command="x")
    core.disable("foo")
    assert core.load("foo").enabled is False
    assert uninstalls == ["foo"]
    core.enable("foo")
    assert core.load("foo").enabled is True
    assert installs == ["foo"]


# --- launchd translator ------------------------------------------------------


def test_cron_to_launchd_simple_hourly(isolated_swap_home):
    from swap_agents import core
    intervals = core.cron_to_launchd_intervals("0 * * * *")
    assert intervals == [{"Minute": 0}]


def test_cron_to_launchd_specific_time(isolated_swap_home):
    from swap_agents import core
    intervals = core.cron_to_launchd_intervals("30 9 * * *")
    assert intervals == [{"Minute": 30, "Hour": 9}]


def test_cron_to_launchd_weekdays(isolated_swap_home):
    from swap_agents import core
    intervals = core.cron_to_launchd_intervals("0 9 * * 1-5")
    assert len(intervals) == 5
    assert all(d["Hour"] == 9 and d["Minute"] == 0 for d in intervals)
    assert sorted(d["Weekday"] for d in intervals) == [1, 2, 3, 4, 5]


def test_cron_to_launchd_too_many_intervals_errors(isolated_swap_home):
    from swap_agents import core
    # "* * * * *" omits all fields (all-full), so total = 1 — that's fine.
    # But explicit lists explode: 50 minutes × 3 hours = 150 entries > 100 cap.
    with pytest.raises(ValueError, match="expands to"):
        core.cron_to_launchd_intervals("1-50 1-3 * * *")


# --- systemd translator ------------------------------------------------------


def test_cron_to_systemd_simple_hourly(isolated_swap_home):
    from swap_agents import core
    out = core.cron_to_systemd_oncalendar("0 * * * *")
    assert out == ["*-*-* *:00:00"]


def test_cron_to_systemd_weekdays_named(isolated_swap_home):
    from swap_agents import core
    out = core.cron_to_systemd_oncalendar("0 9 * * 1-5")
    assert out == ["Mon,Tue,Wed,Thu,Fri *-*-* 09:00:00"]


def test_cron_to_systemd_step_minute(isolated_swap_home):
    from swap_agents import core
    out = core.cron_to_systemd_oncalendar("*/15 * * * *")
    assert out == ["*-*-* *:00,15,30,45:00"]


# --- launchd scheduler -------------------------------------------------------


def test_launchd_install_writes_plist(isolated_swap_home, monkeypatch):
    from swap_agents import core
    monkeypatch.setattr(core, "_LAUNCHD_DIR", isolated_swap_home / "LaunchAgents")
    monkeypatch.setattr(core.LaunchdScheduler, "_launchctl",
                        staticmethod(lambda args, *, check: None))
    sched = core.LaunchdScheduler()
    core.add("foo", "@hourly", command="echo hi")
    agent = core.load("foo")
    sched.install(agent)
    plist = isolated_swap_home / "LaunchAgents" / "com.swap.agents.foo.plist"
    assert plist.exists()
    content = plist.read_text()
    assert "<string>com.swap.agents.foo</string>" in content
    assert "<key>Minute</key><integer>0</integer>" in content
    assert "agents" in content and "run" in content


def test_launchd_uninstall_removes_plist(isolated_swap_home, monkeypatch):
    from swap_agents import core
    monkeypatch.setattr(core, "_LAUNCHD_DIR", isolated_swap_home / "LaunchAgents")
    monkeypatch.setattr(core.LaunchdScheduler, "_launchctl",
                        staticmethod(lambda args, *, check: None))
    sched = core.LaunchdScheduler()
    core.add("foo", "@hourly", command="echo hi")
    sched.install(core.load("foo"))
    plist = isolated_swap_home / "LaunchAgents" / "com.swap.agents.foo.plist"
    assert plist.exists()
    sched.uninstall("foo")
    assert not plist.exists()


# --- systemd scheduler -------------------------------------------------------


def test_systemd_install_writes_units(isolated_swap_home, monkeypatch):
    from swap_agents import core
    monkeypatch.setattr(core, "_SYSTEMD_DIR", isolated_swap_home / "systemd")
    monkeypatch.setattr(core.SystemdUserScheduler, "_systemctl",
                        staticmethod(lambda args, *, check: None))
    sched = core.SystemdUserScheduler()
    core.add("foo", "@hourly", command="echo hi")
    sched.install(core.load("foo"))
    service = isolated_swap_home / "systemd" / "swap-agents-foo.service"
    timer = isolated_swap_home / "systemd" / "swap-agents-foo.timer"
    assert service.exists()
    assert timer.exists()
    assert "OnCalendar=*-*-* *:00:00" in timer.read_text()
    assert "Type=oneshot" in service.read_text()


def test_systemd_uninstall_removes_units(isolated_swap_home, monkeypatch):
    from swap_agents import core
    monkeypatch.setattr(core, "_SYSTEMD_DIR", isolated_swap_home / "systemd")
    monkeypatch.setattr(core.SystemdUserScheduler, "_systemctl",
                        staticmethod(lambda args, *, check: None))
    sched = core.SystemdUserScheduler()
    core.add("foo", "@hourly", command="x")
    sched.install(core.load("foo"))
    sched.uninstall("foo")
    assert not (isolated_swap_home / "systemd" / "swap-agents-foo.service").exists()
    assert not (isolated_swap_home / "systemd" / "swap-agents-foo.timer").exists()


# --- crontab scheduler -------------------------------------------------------


def test_crontab_install_round_trip(isolated_swap_home, monkeypatch):
    from swap_agents import core

    storage = {"content": ""}

    def fake_run(argv, **kwargs):
        if argv[:2] == ["crontab", "-l"]:
            return subprocess.CompletedProcess(argv, 0, stdout=storage["content"], stderr="")
        if argv == ["crontab", "-"]:
            storage["content"] = kwargs.get("input", "")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    sched = core.CrontabScheduler()
    core.add("foo", "@hourly", command="echo hi")
    sched.install(core.load("foo"))
    assert "BEGIN swap-agents foo" in storage["content"]
    assert "0 * * * *" in storage["content"]
    sched.uninstall("foo")
    assert "BEGIN swap-agents foo" not in storage["content"]


def test_crontab_strip_block_preserves_other_entries(isolated_swap_home):
    from swap_agents import core
    content = (
        "# user line\n"
        "0 0 * * * /home/me/script\n"
        "# BEGIN swap-agents foo\n"
        "0 * * * * /usr/local/bin/swap agents run foo --scheduled\n"
        "# END swap-agents foo\n"
        "# another user line\n"
    )
    out = core.CrontabScheduler._strip_block(content, "foo")
    assert "BEGIN swap-agents foo" not in out
    assert "/home/me/script" in out
    assert "another user line" in out


# --- run() -------------------------------------------------------------------


def test_run_executes_and_writes_state(isolated_swap_home):
    from swap_agents import core
    core.add("foo", "@hourly", command="echo hello-from-agent")
    rc = core.run("foo")
    assert rc == 0
    log = (core.agent_dir("foo") / "last_run.log").read_text()
    assert "hello-from-agent" in log
    state = core.read_state("foo")
    assert state["last_exit_code"] == 0
    assert "last_run_at" in state


def test_run_captures_failure_exit_code(isolated_swap_home):
    from swap_agents import core
    core.add("foo", "@hourly", command="exit 7")
    rc = core.run("foo")
    assert rc == 7
    state = core.read_state("foo")
    assert state["last_exit_code"] == 7


def test_run_truncates_log_each_run(isolated_swap_home):
    from swap_agents import core
    core.add("foo", "@hourly", command="echo first")
    core.run("foo")
    core.add  # silence unused import warnings if any
    # second run with different output
    a = core.load("foo")
    a.command = "echo second"
    core._write_config(a)
    core.run("foo")
    log = (core.agent_dir("foo") / "last_run.log").read_text()
    assert "first" not in log
    assert "second" in log


def test_run_scheduled_skips_when_locked(isolated_swap_home):
    from swap_agents import core
    import fcntl

    core.add("foo", "@hourly", command="echo hi")
    # Hold the lock from the test process.
    lock_path = core.agent_dir("foo") / ".lock"
    lock_path.touch()
    fd = os.open(lock_path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        rc = core.run("foo", scheduled=True)
        assert rc == 0  # skipped, but no error
        # No state should have been written since we skipped.
        assert core.read_state("foo") == {}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_run_manual_raises_when_locked(isolated_swap_home):
    from swap_agents import core
    import fcntl

    core.add("foo", "@hourly", command="echo hi")
    lock_path = core.agent_dir("foo") / ".lock"
    lock_path.touch()
    fd = os.open(lock_path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(core.LockHeld):
            core.run("foo")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# --- scheduler picker --------------------------------------------------------


def test_get_scheduler_respects_env_override(isolated_swap_home, monkeypatch):
    from swap_agents import core
    monkeypatch.setenv("SWAP_AGENTS_SCHEDULER", "crontab")
    assert isinstance(core.get_scheduler(), core.CrontabScheduler)
    monkeypatch.setenv("SWAP_AGENTS_SCHEDULER", "launchd")
    assert isinstance(core.get_scheduler(), core.LaunchdScheduler)
    monkeypatch.setenv("SWAP_AGENTS_SCHEDULER", "systemd")
    assert isinstance(core.get_scheduler(), core.SystemdUserScheduler)
