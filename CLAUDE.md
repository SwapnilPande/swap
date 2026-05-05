# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for environment and packaging.

```bash
uv sync                            # install deps + dev deps into .venv
uv run pytest                      # run the full test suite
uv run pytest tests/core/test_registry.py::test_name  # run a single test
uv tool install --editable .       # install the swap CLI from this checkout
uv tool upgrade swap               # what `swap upgrade` runs internally
```

There is no separate lint step configured.

## Architecture

`swap` is a Click CLI whose subcommands are loaded dynamically from the `swap.plugins` setuptools entry-point group. The root command lives in `swap/cli.py`; on import it iterates `entry_points(group="swap.plugins")` and calls `cli.add_command(ep.load())` for each. This means **adding a plugin = adding an entry-point**, not editing the root CLI.

Only `plugins` (the plugin-manager itself) is bundled in the swap wheel — registered under `[project.entry-points."swap.plugins"]` in this repo's own `pyproject.toml` and living at `swap/builtin/plugins/`. Everything else (including first-party plugins like `ssh` and `agents`) is a separate distribution that the user opts into via `swap plugins install <name>`.

First-party plugins live in this repo as a uv workspace under `packages/swap-<name>/` (each with its own `pyproject.toml`, source tree, and tests) and are listed in `registry.json`. They are NOT a dependency of the main `swap` package, so they are not installed by default — they're picked up only when a user runs `swap plugins install`. The dev dependency group includes them so the repo's test suite can exercise them locally.

Adding a new first-party plugin = create `packages/swap-<name>/` (the `swap plugins new` scaffolder produces the right shape), add it to `[tool.uv.sources]` and the dev group in the root `pyproject.toml`, and add an entry to `registry.json`.

### Plugin lifecycle (`swap/core/`)

- `plugin_manager.py` — install/uninstall/scaffold. `install()` and `uninstall()` shell out to `uv pip --python sys.executable` so plugins land in swap's own env (the one `uv tool install` created), not the user's active venv. `scaffold()` writes a working `swap-<name>/` skeleton with the entry-point already wired.
- `registry.py` — fetches and merges plugin registries. Each source is a JSON document with a `plugins` map; sources can be local paths, `~/...` paths, or HTTP(S) URLs. HTTP responses are cached at `~/.swap/registry-cache/<sha256>.json` for `CACHE_TTL` seconds (1h), with stale cache used as fallback on network failure. Multiple sources merge with later sources overriding earlier ones.
- `config.py` — TOML-backed user config at `~/.swap/config.toml`. Registry sources come from `[registries].sources`; default is `_DEFAULT_REGISTRY` in this file. Note: paths in the user's home (`~/.swap/`) are real I/O — tests that touch config must monkeypatch `Path.home`.
- `upgrade.py` — `swap upgrade` shells out to `uv tool upgrade swap`. Versioning behavior is documented in `CONTRIBUTING.md`.

### Plugin shape

Each plugin exposes a top-level Click group via its entry point. By convention plugins keep CLI concerns in `cli.py` and pure logic in `core.py` so the logic is callable without going through Click — see `packages/swap-ssh/swap_ssh/` for the canonical example. The scaffolder in `plugin_manager._cli_template` / `_core_template` enforces this layout for new plugins.

For persistent files beyond `config.toml` (scripts, keys, larger blobs), plugins call `from swap.core.config import get_plugin_data_dir` to get a writable `~/.swap/data/<plugin>/` Path (created on demand). The CLI exposes `swap plugins data-dir <name>` to print this path; `swap plugins uninstall <name> --purge` removes it.

### Registry entry format

A plugin entry in a registry JSON looks like:

```json
{ "myplugin": { "description": "...", "package": "swap-myplugin", "install": "swap-myplugin" } }
```

`install` is what's passed to `uv pip install` (so it can be a PyPI name, a git URL, etc.); `package` is the dist name used to identify the plugin for uninstall. `swap plugins registry-info <path>` generates a correct entry from a plugin's `pyproject.toml`.
