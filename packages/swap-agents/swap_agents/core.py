"""Core logic for the agents plugin: scheduled command runner.

An "agent" is a named scheduled command/script. Each agent lives at
``~/.swap/data/agents/<name>/`` with an ``agent.toml`` config and (after
the first run) a ``state.json`` and ``last_run.log``.

This module is platform-aware via the :class:`Scheduler` abstraction:
launchd on macOS, systemd user timers (or crontab fallback) on Linux.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tomllib
import tomli_w

from swap.core.config import get_plugin_data_dir

PLUGIN_NAME = "agents"
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"
_SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
_LAUNCHD_PREFIX = "com.swap.agents."
_SYSTEMD_PREFIX = "swap-agents-"
_CRONTAB_BEGIN = "# BEGIN swap-agents {name}"
_CRONTAB_END = "# END swap-agents {name}"


# --- agent definition --------------------------------------------------------


@dataclass
class Agent:
    name: str
    schedule: str
    command: Optional[str] = None
    script: Optional[str] = None  # relative filename inside agent_dir
    cwd: Optional[str] = None
    description: str = ""
    enabled: bool = True
    env: dict = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return agent_dir(self.name)

    def invocation(self) -> tuple[list[str], Path]:
        """Return (argv, cwd_path) for executing this agent."""
        if self.command:
            argv = ["/bin/sh", "-c", self.command]
        elif self.script:
            argv = [str(self.dir / self.script)]
        else:
            raise ValueError(f"agent '{self.name}' has neither command nor script")
        cwd_path = Path(os.path.expanduser(self.cwd)) if self.cwd else self.dir
        return argv, cwd_path


# --- paths -------------------------------------------------------------------


def agents_dir() -> Path:
    return get_plugin_data_dir(PLUGIN_NAME)


def agent_dir(name: str) -> Path:
    validate_name(name)
    return agents_dir() / name


def _config_path(name: str) -> Path:
    return agent_dir(name) / "agent.toml"


def _state_path(name: str) -> Path:
    return agent_dir(name) / "state.json"


def _log_path(name: str) -> Path:
    return agent_dir(name) / "last_run.log"


def _lock_path(name: str) -> Path:
    return agent_dir(name) / ".lock"


# --- validation --------------------------------------------------------------


def validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid agent name {name!r}: must match [a-zA-Z0-9][a-zA-Z0-9_-]{{0,63}}"
        )


_CRON_MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


def normalize_schedule(schedule: str) -> str:
    """Expand @-macros to standard 5-field cron expressions."""
    s = schedule.strip()
    return _CRON_MACROS.get(s.lower(), s)


def validate_schedule(schedule: str) -> str:
    """Validate `schedule` and return its normalized 5-field cron form.

    Raises ValueError on invalid input.
    """
    from croniter import croniter, CroniterBadCronError

    expr = normalize_schedule(schedule)
    try:
        if not croniter.is_valid(expr):
            raise ValueError(f"Invalid cron expression: {schedule!r}")
    except CroniterBadCronError as e:
        raise ValueError(f"Invalid cron expression {schedule!r}: {e}") from e
    if len(expr.split()) != 5:
        raise ValueError(
            f"Schedule must be a 5-field cron expression, got {schedule!r}"
        )
    return expr


def next_run_at(schedule: str, base: Optional[float] = None) -> float:
    """Return the next-run unix timestamp for `schedule`."""
    from croniter import croniter

    expr = normalize_schedule(schedule)
    base_time = base if base is not None else time.time()
    return croniter(expr, base_time).get_next(float)


# --- CRUD --------------------------------------------------------------------


def add(
    name: str,
    schedule: str,
    *,
    command: Optional[str] = None,
    script_source: Optional[Path] = None,
    cwd: Optional[str] = None,
    description: str = "",
    env: Optional[dict] = None,
) -> Agent:
    """Create a new agent. Exactly one of `command` or `script_source` must be set.

    `script_source` is a file path; its contents are copied into the agent dir
    as ``script.sh`` and made executable.
    """
    validate_name(name)
    if exists(name):
        raise ValueError(f"Agent {name!r} already exists.")
    if (command is None) == (script_source is None):
        raise ValueError("Provide exactly one of --command or --script.")

    expr = validate_schedule(schedule)

    d = agent_dir(name)
    d.mkdir(parents=True, exist_ok=True)

    script_filename: Optional[str] = None
    if script_source is not None:
        src = Path(script_source).expanduser().resolve()
        if not src.is_file():
            raise ValueError(f"Script not found: {src}")
        dest = d / "script.sh"
        shutil.copyfile(src, dest)
        dest.chmod(0o755)
        script_filename = "script.sh"

    agent = Agent(
        name=name,
        schedule=expr,
        command=command,
        script=script_filename,
        cwd=cwd,
        description=description,
        enabled=True,
        env=dict(env or {}),
    )
    _write_config(agent)
    return agent


def remove(name: str, *, purge: bool = False) -> None:
    """Remove an agent. Always uninstalls scheduler artifacts; with `purge`,
    also deletes the agent directory (config, logs, state)."""
    if not exists(name):
        raise ValueError(f"Agent {name!r} does not exist.")
    sched = get_scheduler()
    try:
        sched.uninstall(name)
    except SchedulerError:
        # Best-effort: even if scheduler removal fails, we should still delete state.
        pass
    if purge:
        shutil.rmtree(agent_dir(name), ignore_errors=True)


def exists(name: str) -> bool:
    try:
        return _config_path(name).exists()
    except ValueError:
        return False


def load(name: str) -> Agent:
    if not exists(name):
        raise ValueError(f"Agent {name!r} does not exist.")
    with open(_config_path(name), "rb") as f:
        data = tomllib.load(f)
    return Agent(
        name=name,
        schedule=data.get("schedule", ""),
        command=data.get("command"),
        script=data.get("script"),
        cwd=data.get("cwd"),
        description=data.get("description", ""),
        enabled=bool(data.get("enabled", True)),
        env=dict(data.get("env", {})),
    )


def list_agents() -> list[Agent]:
    base = agents_dir()
    if not base.exists():
        return []
    out: list[Agent] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "agent.toml").exists():
            continue
        try:
            out.append(load(child.name))
        except (ValueError, OSError):
            continue
    return out


def _write_config(agent: Agent) -> None:
    data: dict = {
        "schedule": agent.schedule,
        "enabled": agent.enabled,
    }
    if agent.command is not None:
        data["command"] = agent.command
    if agent.script is not None:
        data["script"] = agent.script
    if agent.cwd:
        data["cwd"] = agent.cwd
    if agent.description:
        data["description"] = agent.description
    if agent.env:
        data["env"] = agent.env
    path = _config_path(agent.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


# --- enable/disable ----------------------------------------------------------


def enable(name: str) -> None:
    agent = load(name)
    if agent.enabled:
        return
    agent.enabled = True
    _write_config(agent)
    get_scheduler().install(agent)


def disable(name: str) -> None:
    agent = load(name)
    if not agent.enabled:
        return
    agent.enabled = False
    _write_config(agent)
    try:
        get_scheduler().uninstall(name)
    except SchedulerError:
        pass


# --- state -------------------------------------------------------------------


def read_state(name: str) -> dict:
    p = _state_path(name)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(name: str, state: dict) -> None:
    p = _state_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(state, f, indent=2)


# --- run ---------------------------------------------------------------------


class LockHeld(RuntimeError):
    """Raised when another invocation holds the agent's flock."""


def run(name: str, *, scheduled: bool = False, force: bool = False) -> int:
    """Execute an agent. Returns the exit code.

    - Acquires a non-blocking flock on ``.lock``. If held: scheduled runs skip
      (return 0), manual runs raise LockHeld unless ``force=True``.
    - Redirects stdout+stderr to ``last_run.log`` (truncate-on-open).
    - Updates ``state.json`` with last_run_at and last_exit_code.
    """
    import fcntl

    agent = load(name)
    argv, cwd_path = agent.invocation()

    d = agent.dir
    d.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(_lock_path(name), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if not force:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if scheduled:
                    return 0
                raise LockHeld(
                    f"Agent {name!r} is already running. Use --force to override."
                )
        else:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

        env = os.environ.copy()
        env.update(agent.env)

        log_path = _log_path(name)
        started_at = time.time()
        with open(log_path, "wb") as logf:
            proc = subprocess.run(
                argv,
                cwd=str(cwd_path),
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                check=False,
            )
        ended_at = time.time()
        state = {
            "last_run_at": started_at,
            "last_run_finished_at": ended_at,
            "last_exit_code": proc.returncode,
            "last_run_scheduled": scheduled,
        }
        _write_state(name, state)
        return proc.returncode
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)


def tail_log(name: str) -> str:
    p = _log_path(name)
    if not p.exists():
        return ""
    return p.read_text(errors="replace")


# --- scheduler abstraction ---------------------------------------------------


class SchedulerError(RuntimeError):
    """Raised when interacting with the underlying OS scheduler fails."""


class Scheduler:
    """Abstract scheduler interface."""

    name: str = "abstract"

    def install(self, agent: Agent) -> None:
        raise NotImplementedError

    def uninstall(self, name: str) -> None:
        raise NotImplementedError

    def is_enabled(self, name: str) -> bool:
        raise NotImplementedError


def _swap_executable() -> str:
    """Find the swap executable to invoke from scheduler entries.

    Prefer the absolute path from `which` so the schedule isn't sensitive to
    PATH at run time.
    """
    found = shutil.which("swap")
    if found:
        return found
    # Fallback: same Python that's running this code, in case the user is
    # developing without `swap` on PATH.
    return f"{sys.executable} -m swap.cli"


def _scheduled_argv(name: str) -> list[str]:
    """Argv used by all schedulers to fire a scheduled run."""
    swap = _swap_executable()
    if swap.startswith(sys.executable):
        return swap.split() + ["agents", "run", name, "--scheduled"]
    return [swap, "agents", "run", name, "--scheduled"]


# --- launchd -----------------------------------------------------------------


class LaunchdScheduler(Scheduler):
    name = "launchd"

    def install(self, agent: Agent) -> None:
        plist_path = self._plist_path(agent.name)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        intervals = cron_to_launchd_intervals(agent.schedule)
        plist_path.write_text(_render_launchd_plist(agent.name, intervals))
        # Best-effort load. If launchctl is missing (tests), don't blow up.
        self._launchctl(["bootout", f"gui/{os.getuid()}", str(plist_path)], check=False)
        self._launchctl(
            ["bootstrap", f"gui/{os.getuid()}", str(plist_path)], check=True
        )

    def uninstall(self, name: str) -> None:
        plist_path = self._plist_path(name)
        if plist_path.exists():
            self._launchctl(
                ["bootout", f"gui/{os.getuid()}", str(plist_path)], check=False
            )
            plist_path.unlink()

    def is_enabled(self, name: str) -> bool:
        return self._plist_path(name).exists()

    @staticmethod
    def _plist_path(name: str) -> Path:
        return _LAUNCHD_DIR / f"{_LAUNCHD_PREFIX}{name}.plist"

    @staticmethod
    def _launchctl(args: list[str], *, check: bool) -> None:
        try:
            subprocess.run(["launchctl", *args], check=check, capture_output=True)
        except FileNotFoundError as e:
            raise SchedulerError("launchctl not found on this system") from e
        except subprocess.CalledProcessError as e:
            if check:
                raise SchedulerError(
                    f"launchctl {' '.join(args)} failed: "
                    f"{e.stderr.decode(errors='replace').strip()}"
                ) from e


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_launchd_plist(name: str, intervals: list[dict[str, int]]) -> str:
    label = f"{_LAUNCHD_PREFIX}{name}"
    argv = _scheduled_argv(name)
    args_xml = "\n".join(f"    <string>{_xml_escape(a)}</string>" for a in argv)

    if len(intervals) == 1:
        inv = intervals[0]
        cal_xml = "  <key>StartCalendarInterval</key>\n  <dict>\n"
        for k, v in sorted(inv.items()):
            cal_xml += f"    <key>{k}</key><integer>{v}</integer>\n"
        cal_xml += "  </dict>"
    else:
        cal_xml = "  <key>StartCalendarInterval</key>\n  <array>\n"
        for inv in intervals:
            cal_xml += "    <dict>\n"
            for k, v in sorted(inv.items()):
                cal_xml += f"      <key>{k}</key><integer>{v}</integer>\n"
            cal_xml += "    </dict>\n"
        cal_xml += "  </array>"

    log_path = _log_path(name)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
{cal_xml}
  <key>StandardOutPath</key>
  <string>{_xml_escape(str(log_path))}</string>
  <key>StandardErrorPath</key>
  <string>{_xml_escape(str(log_path))}</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
"""


# --- systemd-user ------------------------------------------------------------


class SystemdUserScheduler(Scheduler):
    name = "systemd-user"

    def install(self, agent: Agent) -> None:
        _SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
        on_calendar = cron_to_systemd_oncalendar(agent.schedule)
        service_path, timer_path = self._unit_paths(agent.name)
        service_path.write_text(_render_systemd_service(agent.name))
        timer_path.write_text(_render_systemd_timer(agent.name, on_calendar))
        self._systemctl(["daemon-reload"], check=False)
        self._systemctl(["enable", "--now", timer_path.name], check=True)

    def uninstall(self, name: str) -> None:
        service_path, timer_path = self._unit_paths(name)
        if timer_path.exists():
            self._systemctl(["disable", "--now", timer_path.name], check=False)
            timer_path.unlink()
        if service_path.exists():
            service_path.unlink()
        self._systemctl(["daemon-reload"], check=False)

    def is_enabled(self, name: str) -> bool:
        _, timer_path = self._unit_paths(name)
        return timer_path.exists()

    @staticmethod
    def _unit_paths(name: str) -> tuple[Path, Path]:
        return (
            _SYSTEMD_DIR / f"{_SYSTEMD_PREFIX}{name}.service",
            _SYSTEMD_DIR / f"{_SYSTEMD_PREFIX}{name}.timer",
        )

    @staticmethod
    def _systemctl(args: list[str], *, check: bool) -> None:
        try:
            subprocess.run(
                ["systemctl", "--user", *args], check=check, capture_output=True
            )
        except FileNotFoundError as e:
            raise SchedulerError("systemctl not found on this system") from e
        except subprocess.CalledProcessError as e:
            if check:
                raise SchedulerError(
                    f"systemctl --user {' '.join(args)} failed: "
                    f"{e.stderr.decode(errors='replace').strip()}"
                ) from e


def _render_systemd_service(name: str) -> str:
    argv = _scheduled_argv(name)
    exec_start = " ".join(_systemd_quote(a) for a in argv)
    log_path = _log_path(name)
    return f"""[Unit]
Description=swap agent {name}

[Service]
Type=oneshot
ExecStart={exec_start}
StandardOutput=truncate:{log_path}
StandardError=inherit
"""


def _render_systemd_timer(name: str, on_calendar: list[str]) -> str:
    lines = "\n".join(f"OnCalendar={oc}" for oc in on_calendar)
    return f"""[Unit]
Description=swap agent {name} timer

[Timer]
{lines}
Persistent=true

[Install]
WantedBy=timers.target
"""


def _systemd_quote(s: str) -> str:
    if any(c.isspace() or c in "\"'$" for c in s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


# --- crontab fallback --------------------------------------------------------


class CrontabScheduler(Scheduler):
    name = "crontab"

    def install(self, agent: Agent) -> None:
        existing = self._read()
        block = self._render_block(agent)
        new = self._strip_block(existing, agent.name) + block
        self._write(new)

    def uninstall(self, name: str) -> None:
        existing = self._read()
        new = self._strip_block(existing, name)
        self._write(new)

    def is_enabled(self, name: str) -> bool:
        existing = self._read()
        return _CRONTAB_BEGIN.format(name=name) in existing

    @staticmethod
    def _render_block(agent: Agent) -> str:
        argv = _scheduled_argv(agent.name)
        log = _log_path(agent.name)
        cmd = " ".join(_shell_quote(a) for a in argv) + f" >{_shell_quote(str(log))} 2>&1"
        return (
            f"{_CRONTAB_BEGIN.format(name=agent.name)}\n"
            f"{agent.schedule} {cmd}\n"
            f"{_CRONTAB_END.format(name=agent.name)}\n"
        )

    @staticmethod
    def _strip_block(content: str, name: str) -> str:
        begin = _CRONTAB_BEGIN.format(name=name)
        end = _CRONTAB_END.format(name=name)
        out_lines: list[str] = []
        in_block = False
        for line in content.splitlines():
            if line.strip() == begin:
                in_block = True
                continue
            if in_block and line.strip() == end:
                in_block = False
                continue
            if not in_block:
                out_lines.append(line)
        return ("\n".join(out_lines) + "\n") if out_lines else ""

    @staticmethod
    def _read() -> str:
        try:
            r = subprocess.run(
                ["crontab", "-l"], capture_output=True, check=False, text=True
            )
        except FileNotFoundError as e:
            raise SchedulerError("crontab not found on this system") from e
        # Empty crontab gives non-zero exit on some systems; treat as empty.
        if r.returncode != 0 and "no crontab" not in r.stderr.lower():
            # Other failure (e.g. permission)
            return r.stdout
        return r.stdout

    @staticmethod
    def _write(content: str) -> None:
        try:
            subprocess.run(
                ["crontab", "-"], input=content, text=True, check=True, capture_output=True
            )
        except FileNotFoundError as e:
            raise SchedulerError("crontab not found on this system") from e
        except subprocess.CalledProcessError as e:
            raise SchedulerError(f"crontab write failed: {e.stderr.strip()}") from e


def _shell_quote(s: str) -> str:
    if not s or any(c in s for c in " \t\n\"'$\\&|;<>()*?[]{}~`#!"):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


# --- scheduler picker --------------------------------------------------------


def get_scheduler() -> Scheduler:
    """Pick the right scheduler for the current platform.

    Override with ``SWAP_AGENTS_SCHEDULER`` (``launchd``, ``systemd``, ``crontab``)
    — primarily for tests.
    """
    override = os.environ.get("SWAP_AGENTS_SCHEDULER", "").strip().lower()
    if override == "launchd":
        return LaunchdScheduler()
    if override == "systemd":
        return SystemdUserScheduler()
    if override == "crontab":
        return CrontabScheduler()

    system = platform.system()
    if system == "Darwin":
        return LaunchdScheduler()
    if system == "Linux":
        if Path(f"/run/user/{os.getuid()}/systemd").exists():
            return SystemdUserScheduler()
        return CrontabScheduler()
    raise SchedulerError(
        f"No scheduler available for platform {system!r}. "
        "Set SWAP_AGENTS_SCHEDULER to override."
    )


# --- cron translators --------------------------------------------------------

_LAUNCHD_FIELD_KEYS = ["Minute", "Hour", "Day", "Month", "Weekday"]
_FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
_LAUNCHD_MAX_INTERVALS = 100
_SYSTEMD_MAX_LINES = 100


def _expand_field(field_str: str, low: int, high: int) -> list[int]:
    """Expand one cron field (no L/W/# extensions) into the concrete values."""
    if field_str == "*":
        return list(range(low, high + 1))
    out: set[int] = set()
    for piece in field_str.split(","):
        step = 1
        if "/" in piece:
            piece, step_str = piece.split("/", 1)
            step = int(step_str)
        if piece in ("*", ""):
            start, end = low, high
        elif "-" in piece:
            a, b = piece.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(piece)
        if start < low or end > high or start > end:
            raise ValueError(f"Field value out of range: {field_str!r}")
        for v in range(start, end + 1, step):
            out.add(v)
    return sorted(out)


def cron_to_launchd_intervals(schedule: str) -> list[dict[str, int]]:
    """Translate a cron expression into a list of launchd StartCalendarInterval dicts.

    Strategy: enumerate the cartesian product of expanded fields. Fields where
    every value is selected are omitted (which means "any" in launchd). Errors
    if the resulting product would exceed _LAUNCHD_MAX_INTERVALS entries.
    """
    expr = validate_schedule(schedule)
    fields = expr.split()
    expanded: list[list[int]] = []
    omit: list[bool] = []
    for f, (lo, hi) in zip(fields, _FIELD_RANGES):
        values = _expand_field(f, lo, hi)
        expanded.append(values)
        omit.append(values == list(range(lo, hi + 1)))

    total = 1
    for vs, om in zip(expanded, omit):
        if not om:
            total *= len(vs)
    if total > _LAUNCHD_MAX_INTERVALS:
        raise ValueError(
            f"Cron expression {schedule!r} expands to {total} launchd intervals "
            f"(max {_LAUNCHD_MAX_INTERVALS}). Use a simpler schedule."
        )

    out: list[dict[str, int]] = [{}]
    for key, values, om in zip(_LAUNCHD_FIELD_KEYS, expanded, omit):
        if om:
            continue
        out = [{**d, key: v} for d in out for v in values]
    return out


def cron_to_systemd_oncalendar(schedule: str) -> list[str]:
    """Translate a cron expression into one or more systemd OnCalendar lines.

    Format: ``DOW *-MM-DD HH:MM:00`` where each component is a comma-separated
    list (or ``*``). Errors if any component would have more than
    _SYSTEMD_MAX_LINES values.
    """
    expr = validate_schedule(schedule)
    minute, hour, day, month, dow = expr.split()
    weekdays = _expand_field(dow, 0, 6)
    minutes = _expand_field(minute, 0, 59)
    hours = _expand_field(hour, 0, 23)
    days = _expand_field(day, 1, 31)
    months = _expand_field(month, 1, 12)

    for values, name in [(minutes, "minute"), (hours, "hour"), (days, "day"),
                         (months, "month"), (weekdays, "weekday")]:
        if len(values) > _SYSTEMD_MAX_LINES:
            raise ValueError(
                f"Cron expression {schedule!r} has too many {name} values "
                f"(max {_SYSTEMD_MAX_LINES})."
            )

    def _fmt(vals: list[int], full_low: int, full_high: int, width: int = 0) -> str:
        if vals == list(range(full_low, full_high + 1)):
            return "*"
        return ",".join(f"{v:0{width}d}" for v in vals) if width else ",".join(map(str, vals))

    dow_part = ""
    if weekdays != list(range(0, 7)):
        names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        dow_part = ",".join(names[v] for v in weekdays) + " "

    date = f"*-{_fmt(months, 1, 12, 2)}-{_fmt(days, 1, 31, 2)}"
    timepart = f"{_fmt(hours, 0, 23, 2)}:{_fmt(minutes, 0, 59, 2)}:00"
    return [f"{dow_part}{date} {timepart}"]
