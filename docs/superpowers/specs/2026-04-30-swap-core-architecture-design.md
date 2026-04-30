# swap Core Architecture Design

**Date:** 2026-04-30  
**Status:** Approved — proceeding to implementation

---

## Context

swap is a personal CLI tool succeeding `efr`. It bundles utilities through a plugin system and is deeply integrated with `uv`. The ssh-config tool serves as the first built-in plugin and the reference implementation for everything else.

**What worked in efr:**
- One-command install
- Plugin system via Python entry points
- Registry JSON → install script pattern
- Plugin dev scaffolding command

**What to fix:**
- Commands get verbose and nested (`efr motorgo boards install --board-name motorgo_plink -a --force`)
- No configuration persistence
- `setup.py`-based, not `pyproject.toml`
- TUI (current ssh tool) is too GUI-like

---

## Project Layout

```
swap/
├── pyproject.toml
├── install.sh
├── swap/
│   ├── __init__.py
│   ├── cli.py              # Entry point: plugin discovery, top-level commands
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py       # Config read/write (TOML, global + per-plugin namespaces)
│   │   ├── plugin_manager.py  # List, install, uninstall, scaffold new plugins
│   │   ├── registry.py     # Aggregate registry from multiple sources
│   │   └── upgrade.py      # Self-upgrade via uv tool upgrade
│   └── builtin/
│       ├── __init__.py
│       ├── plugins/
│       │   ├── __init__.py
│       │   └── cli.py      # `swap plugins` commands (thin CLI over plugin_manager)
│       └── ssh/
│           ├── __init__.py
│           ├── cli.py      # `swap ssh` commands (thin CLI, uses questionary prompts)
│           └── core.py     # SSH logic: keygen, push key, update config (no CLI deps)
```

**Rule:** `core/` modules have zero CLI imports. `builtin/<plugin>/core.py` files have zero CLI imports. Business logic lives entirely in `core.py` files so it can be called by agents, tests, or other tools without side effects.

---

## Plugin System

### Discovery

Plugins register a click group/command under the `swap.plugins` entry point group. `cli.py` iterates `entry_points(group="swap.plugins")` and adds each to the root group. This is identical to efr's approach — it works well.

```toml
# A plugin's pyproject.toml
[project.entry-points."swap.plugins"]
myplug = "myplug.cli:cli"
```

### Package Convention

Plugin packages are named `swap-<name>` (e.g. `swap-ssh`, `swap-k8s`). The entry point name becomes the subcommand: `swap myplug`.

### Registry Format

The registry is a JSON file that can be hosted anywhere. swap aggregates from multiple sources (official + community + local).

```json
{
  "version": 1,
  "plugins": {
    "ssh": {
      "description": "SSH key management and host config",
      "package": "swap-ssh",
      "install": "swap-ssh"
    },
    "k8s": {
      "description": "Kubernetes helpers",
      "package": "swap-k8s",
      "install": "git+https://github.com/swapnil/swap-k8s"
    }
  }
}
```

`install` is the argument passed to `uv tool install` (PyPI name, git URL, or local path). This is more flexible than efr's shell-script-per-plugin approach.

### Registry Sources

Configured in `~/.swap/config.toml`:

```toml
[registries]
sources = [
  "https://raw.githubusercontent.com/swapnil/swap/main/registry.json",
  "~/.swap/local-registry.json"
]
```

`registry.py` fetches all sources, merges them (later sources override earlier for same plugin name), and caches the result. If a source is unreachable, it uses the cache with a warning.

### Plugin Install / Uninstall

```
swap plugins install <name>     # looks up registry, runs: uv pip install <install-arg>
swap plugins uninstall <name>   # uv pip uninstall swap-<name>
swap plugins list               # shows registry + installed status
swap plugins upgrade <name>     # uv pip install --upgrade <install-arg>
```

Because swap is installed as a `uv tool`, plugin packages must go into the same tool environment. The install command uses `uv tool run --from swap uv pip install` or equivalent to inject into the right venv. Concretely: `uv pip install --python $(uv tool dir swap)/bin/python <package>`.

### Plugin Dev Scaffolding

```
swap plugins new <name>         # scaffold a new plugin
swap plugins dev install <path> # editable install from local path
swap plugins registry-info <path> # generate registry entry JSON
```

`new` creates:
```
swap-<name>/
├── pyproject.toml   (with swap.plugins entry point, swap-<name> package name)
├── README.md
└── <name>/
    ├── __init__.py
    ├── cli.py        (thin click group with example command)
    └── core.py       (empty business logic module)
```

---

## Configuration System

### Storage

```
~/.swap/
├── config.toml       # global config + per-plugin sections
└── registry-cache/   # cached remote registry JSONs
    └── <hash>.json
```

### Format

```toml
[swap]
version = "0.1.0"   # written on first run, used for migration

[registries]
sources = ["https://raw.githubusercontent.com/.../registry.json"]

[plugins.ssh]
default_key_type = "ed25519"
default_username = "ubuntu"

[plugins.k8s]
default_namespace = "default"
```

### API (core/config.py)

```python
def get(section: str, key: str, default=None) -> Any
def set(section: str, key: str, value: Any) -> None
def get_plugin(plugin_name: str) -> dict
def set_plugin(plugin_name: str, key: str, value: Any) -> None
```

Config is always read fresh (no in-process caching) so plugins always see current values. TOML via `tomllib` (stdlib, Python 3.11+) for reads, `tomli-w` for writes.

### CLI

```
swap config get <section.key>
swap config set <section.key> <value>
swap config list                          # dump current config
```

---

## Install Script

Uses `uv tool install` — the cleanest possible approach. `uv tool` handles PATH registration, venv isolation, and upgrades natively.

```bash
#!/usr/bin/env bash
set -e

# Install uv if needed
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env"
fi

# Install swap as a uv tool
uv tool install git+https://github.com/swapnil/swap

echo "swap installed. Run 'swap' to get started."
```

One liner: `curl -sSL https://raw.githubusercontent.com/swapnil/swap/main/install.sh | bash`

### Upgrade

```bash
swap upgrade    # runs: uv tool upgrade swap
```

---

## Top-Level CLI Behavior

`swap` with no args prints a minimal dashboard:
```
swap v0.1.0

Installed plugins: ssh, k8s, plugins
Run 'swap <plugin>' to use it, 'swap plugins list' to browse available plugins.
```

No giant emoji banners. Just what you need.

`swap --help` shows standard click help.

---

## TUI Philosophy

**Principle:** Commands should work fully via flags for scripts/agents. Interactive mode is a convenience layer, not a requirement.

When a command is run without required flags, swap prompts for them interactively using `questionary` — sequential, inline prompts, not a full-screen app. Each prompt is one line. Progress is printed as steps complete.

Example (`swap ssh setup` with no flags):
```
? Host alias: myserver
? IP/Hostname: 192.168.1.100
? Username: ubuntu
? Key name [id_ed25519_myserver]: 
? Password: ****

  Generating key pair...   ✓
  Pushing public key...    ✓
  Updating ~/.ssh/config   ✓

Done. Connect with: ssh myserver
```

All fields also available as flags: `swap ssh setup --alias myserver --host 192.168.1.100 ...`

The existing Textual `SSHConfigApp` is replaced with this pattern. Textual remains available for genuinely complex interactions where it adds real value (e.g., a multi-item selection TUI for managing many SSH hosts).

---

## SSH Built-in Plugin (Reference Implementation)

`ssh/core.py` exposes:

```python
def generate_keypair(key_path: Path, key_type: str = "ed25519") -> KeyPair
def push_public_key(host: str, username: str, password: str, pub_key: str) -> None
def add_ssh_config_entry(alias: str, hostname: str, username: str, key_path: Path) -> None
def setup(alias, hostname, username, key_name, password, key_type="ed25519") -> None
```

`ssh/cli.py` is a thin wrapper: parses flags → calls `core.setup()`, handling prompt fallback for missing args.

---

## AI/Agentic Considerations

- `core.py` functions are directly importable by agents with no side effects
- Functions accept typed parameters and return typed results — no string parsing required
- No global state in core modules
- `config.py` is callable programmatically
- Future: a `--json` flag on commands for machine-readable output (not in scope now, but the architecture doesn't prevent it)

---

## What's Not In Scope Now

- TUI design beyond the questionary pattern described above (will design separately)
- The `config` CLI commands (architecture is defined, implementation deferred)
- Any specific plugins beyond `ssh` and `plugins`
- Windows support (not needed, follow efr's pattern when needed)
