# Contributing to swap

Thanks for taking a look. swap is a personal CLI but contributions and bug reports are welcome.

## Development setup

```bash
git clone https://github.com/SwapnilPande/swap
cd swap
uv sync                           # installs deps + dev deps
uv tool install --editable .      # installs the `swap` command from this checkout
uv run pytest                     # run the test suite
```

The `--editable` install means changes to source files are picked up immediately — no reinstall needed.

## Project layout

- `swap/cli.py` — root Click group; auto-loads every entry point in the `swap.plugins` group.
- `swap/core/` — shared infrastructure (config, registry, plugin install/upgrade, scaffolding).
- `swap/builtin/<name>/` — built-in plugins (`ssh`, `plugins`). Structurally identical to external plugins, just shipped in the same wheel.
- `tests/` — mirrors the package layout. Tests touching `~/.swap` or `~/.ssh` must monkeypatch `Path.home`.

A plugin = a Click group registered under `[project.entry-points."swap.plugins"]`. By convention CLI code lives in `cli.py` and pure logic in `core.py` so the logic is callable without going through Click.

## Pull requests

- Branches: `fix/<short-name>`, `feat/<short-name>`, `docs/<short-name>`.
- Keep PRs focused — one issue or one feature per PR.
- `uv run pytest` must pass. Add tests for new logic in `swap/core/` and plugin `core.py` modules; CLI wiring can be verified manually.
- Reference the issue you're closing in the PR description (`Fixes #N`).

## Versioning

swap follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`). The version lives in **one place**: the `version` field of `pyproject.toml`. `swap --help` and `swap` (no args) read it via `importlib.metadata.version("swap")`.

When changes are merged to `main`:

- **PATCH** (`0.1.0` → `0.1.1`) — bug fixes, doc-only changes, internal refactors.
- **MINOR** (`0.1.0` → `0.2.0`) — new commands, new plugin APIs, additive changes that don't break existing behavior.
- **MAJOR** (`0.x.y` → `1.0.0` and beyond) — breaking changes to CLI surface, config schema, or registry format. While `0.x`, breaking changes bump MINOR per SemVer convention.

### Release flow

1. Bump `version` in `pyproject.toml` in a dedicated commit on `main` (or as part of the merging PR).
2. Tag the commit: `git tag v<version> && git push origin v<version>`.
3. That's it — there is no PyPI publish step. swap is installed directly from the GitHub repo.

### How `swap upgrade` works

`swap upgrade` runs `uv tool upgrade swap`. Because the tool was installed from `git+https://github.com/SwapnilPande/swap` (via `install.sh` or `uv tool install`), `uv` re-resolves that git source — which means it pulls whatever `main` currently points to and reinstalls if the resolved commit changed.

Implications:

- Users get whatever is on `main` HEAD when they upgrade. **`main` must always be installable and shippable.** Do not merge work-in-progress or known-broken commits.
- Bumping `pyproject.toml`'s `version` is what makes `swap` (no args) and `swap --help` report a new version after upgrade. If you ship a change without bumping the version, users will see an upgraded binary but an unchanged version string — confusing, so always bump.
- Tags are not strictly required for `swap upgrade` to function, but they make it possible to install a specific past version with `uv tool install git+https://github.com/SwapnilPande/swap@v0.1.2`.

If swap is ever published to PyPI, `uv tool upgrade swap` will use PyPI versions instead, and the tag/version bump becomes the trigger rather than a `main` push.

## Plugin contributions

Built-in plugins (in `swap/builtin/`) are reserved for genuinely universal utilities. Most new plugins should be separate `swap-<name>` packages — see `swap plugins new <name>` for a working scaffold and the README for the workflow.

To list a plugin in the default registry, edit `registry.json` and open a PR; `swap plugins registry-info <path>` prints the JSON entry to paste in.
