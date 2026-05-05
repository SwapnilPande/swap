# `swap agents`

Schedule and manage background agents — named cron jobs that run a command
or script on a schedule, with per-agent logs and exit-code tracking.

The plugin is general-purpose: an "agent" is just a scheduled shell command.
Agents that happen to invoke an LLM (Claude, opencode, codex) are no
different from agents that hit an API or run a build.

## Quick start

```bash
# Hourly cron job that runs Claude in headless mode
swap agents add triage \
  --schedule "@hourly" \
  --command "claude -p --permission-mode acceptEdits 'Review issues in ~/code/myrepo and tag ready ones'"

swap agents list
swap agents run triage          # ad-hoc fire now
swap agents tail triage         # see the last run's output
swap agents status triage       # last exit code, next run time
swap agents disable triage      # stop scheduling, keep config
swap agents enable triage
swap agents remove triage --purge
```

## Schedules

Schedules are 5-field cron expressions (`min hour day month dow`) plus the
following macros:

| Macro       | Cron equivalent |
|-------------|-----------------|
| `@hourly`   | `0 * * * *`     |
| `@daily`    | `0 0 * * *`     |
| `@weekly`   | `0 0 * * 0`     |
| `@monthly`  | `0 0 1 * *`     |
| `@yearly`   | `0 0 1 1 *`     |

## Where state lives

| Path                                     | Contents                            |
|------------------------------------------|-------------------------------------|
| `~/.swap/data/agents/<name>/agent.toml`  | Agent config (see schema below)     |
| `~/.swap/data/agents/<name>/script.sh`   | Optional script (when `--script`)   |
| `~/.swap/data/agents/<name>/last_run.log`| Stdout+stderr of the most recent run (overwritten each run) |
| `~/.swap/data/agents/<name>/state.json`  | `last_run_at`, `last_exit_code`     |

The plugin also writes a single OS-scheduler artifact per agent:

- **macOS:** `~/Library/LaunchAgents/com.swap.agents.<name>.plist`
- **Linux (systemd-user):** `~/.config/systemd/user/swap-agents-<name>.{service,timer}`
- **Linux (crontab fallback):** a marked block in your user crontab

## `agent.toml` schema

```toml
schedule = "0 * * * *"          # required; cron expression or @macro
command = "claude -p 'foo'"     # exactly one of command or script
# script = "script.sh"          # path relative to the agent dir
cwd = "~/code/swap"             # optional; defaults to the agent dir
description = "..."             # optional, shown in `swap agents list`
enabled = true                  # disabled agents are not scheduled

[env]
PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
```

## CLI reference

| Command                         | Purpose                                        |
|---------------------------------|------------------------------------------------|
| `swap agents add <name> ...`    | Create and schedule an agent                   |
| `swap agents remove <name>`     | Unschedule and remove (`--purge` deletes data) |
| `swap agents list`              | List agents with status and schedule           |
| `swap agents show <name>`       | Full config + next run time                    |
| `swap agents run <name>`        | Run ad-hoc (`--force` overrides the lock)      |
| `swap agents tail <name>`       | Print `last_run.log`                           |
| `swap agents status <name>`     | Last/next run, exit code, log path             |
| `swap agents enable <name>`     | Re-install scheduler entry                     |
| `swap agents disable <name>`    | Remove scheduler entry, keep config            |
| `swap agents edit <name>`       | Open `agent.toml` in `$EDITOR`                 |

## Concurrency

Each agent has a per-agent flock at `<agent-dir>/.lock`. If a scheduled run
fires while a previous invocation is still running, it exits 0 (skipped) —
your schedule will not stack up runs. Manual `swap agents run` errors out
unless you pass `--force`.

## Running Claude (or other agents) headlessly

Claude Code's non-interactive mode (`-p` / `--print`) is purpose-built for
agent scripts. A typical setup:

```bash
swap agents add issue-triage \
  --schedule "@hourly" \
  --script ./triage.sh
```

…where `triage.sh` is something like:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd ~/code/myrepo
claude -p \
  --permission-mode acceptEdits \
  --allowed-tools "Bash,Read,Edit" \
  "Review open issues, leave clarifying questions, tag ready ones."
```

The plugin captures stdout+stderr to `last_run.log` and records the exit
code in `state.json`. You can wire failure notifications on top of that
later — for now, `swap agents list` and `swap agents status` surface the
exit code with a ✓/✗ marker.

## Platform support

| Platform | Backend         | Notes                                              |
|----------|-----------------|----------------------------------------------------|
| macOS    | launchd         | Plist installed in `~/Library/LaunchAgents/`       |
| Linux    | systemd-user    | Used when `/run/user/$UID/systemd` exists          |
| Linux    | crontab         | Fallback when systemd-user is unavailable          |
| Windows  | —               | Not yet supported (tracked separately)             |

You can override the auto-detected scheduler by setting
`SWAP_AGENTS_SCHEDULER` to one of `launchd`, `systemd`, `crontab` — useful
for tests and for forcing crontab on systemd-enabled hosts.
