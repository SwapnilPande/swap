# swap-devenv — Design

**Status:** Approved (brainstorm complete, spec written 2026-04-30)
**Repo:** New, `swap-devenv` (separate from `swap` core)

## Purpose

A swap plugin that hydrates a machine — laptop, server, or embedded target like a Jetson — from a user-controlled config repo. Idempotent, cross-OS, bidirectional.

The plugin's value is the **applicator and sync machinery**. The configs themselves live in any user repo with a `devenv.toml` manifest. Anyone can point `swap-devenv` at their own repo and have it work.

## Non-goals

- Not a generic config-management framework (no Ansible/Chef/Salt aspirations).
- Not a dotfile-symlink manager (uses copies, deliberately).
- Not a secrets manager. Convention is "don't put secrets in the repo." `sops`/`age` integration may come later.
- Not a templating engine. Per-host variation is handled by tags + per-host overlay files, not by Jinja.

## Mental model

Three explicit directions, no automatic two-way sync:

| Verb | Direction | Purpose |
|---|---|---|
| `apply` | repo → this machine | Copy files into place; install packages; run scripts |
| `capture` | this machine → repo | Pull current local file contents back into the repo |
| `push <ssh-alias>` | repo → remote machine | rsync the repo and run `apply` there |

Plus drift-safety primitives: `status`, `diff`, `--force`, `--skip`.

## The devenv repo

A devenv repo is any git repo with `devenv.toml` at its root. The repo is **standalone-readable**: a human (or another tool) can follow the manifest and reproduce the apply behavior without ever installing swap. Only `devenv.toml` is swap-specific; everything else is just files in directories.

`swap devenv init <path>` scaffolds a starter repo with:

```
my-devenv/
├── README.md          # generated, explains the layout in plain English
├── devenv.toml        # manifest (the only swap-specific file)
├── zsh/               # suggested layout — not enforced
├── git/
├── vscode/
└── scripts/
```

`swap devenv use <path-or-git-url>` sets the active devenv repo for the current machine. Stored in `~/.swap/config.toml`:

```toml
[plugins.devenv]
repo = "/home/swap/my-devenv"
tags = ["laptop", "darwin-arm"]
package_managers = ["brew", "cargo", "uv-tool", "shell"]   # optional override
```

All other commands operate on the active repo with no path argument.

## Manifest format

`devenv.toml` has four entry types: `[[file]]`, `[[directory]]`, `[[script]]`, `[[package]]`. Plus optional `[[catalog]]` extensions and `[meta]`.

### Files

```toml
[[file]]
name = "zshrc"            # used by `capture zshrc`, `diff zshrc`, etc.
src  = "zsh/zshrc"        # path within the repo
dest = "~/.zshrc"         # absolute or ~-relative target path
when = "linux | darwin"   # optional platform/tag filter
mode = "managed-block"    # default: "replace"
permissions = 0o644       # optional
```

**Modes:**
- `replace` (default) — `apply` overwrites `dest` with `<repo>/<src>` byte-for-byte.
- `managed-block` — content is written between markers in `dest`, leaving anything outside untouched. Markers' comment syntax is auto-inferred from the file extension. If it can't be inferred, `apply` errors with a clear message. Sample marker block (auto-injected by `apply`):
  ```sh
  # >>> swap-devenv managed (do not edit between markers) >>>
  <contents from repo>
  # <<< swap-devenv managed <<<
  ```
  In `<repo>/<src>`, the file does **not** contain markers — only the rendered/applied form does. `capture` extracts the between-markers region from `dest` and writes it to `<repo>/<src>` cleanly.

### Directories

```toml
[[directory]]
name = "nvim"
src  = "nvim"
dest = "~/.config/nvim"
when = "linux | darwin"
```

Recursively copied. Honors a `.devenvignore` file in `<repo>/<src>` (gitignore-style) — typically excludes `node_modules/`, `.DS_Store`, etc.

### Scripts

```toml
[[script]]
name    = "build-essential"
run     = "scripts/build-essential.sh"
when    = "linux"
runs_as = "root"            # default: "user"
```

Run after files are placed, in manifest order. Failure aborts `apply`.

### Packages — OS-agnostic

```toml
[[package]]
name = "ripgrep"

[[package]]
name = "neovim"

[[package]]
name = "uv"
```

The plugin maintains a **catalog** mapping logical names to per-manager recipes. A bundled catalog ships with v1 (~10–15 common dev tools); users extend it with `[[catalog]]` entries in their own `devenv.toml`:

```toml
[[catalog]]
name  = "ripgrep"
brew  = "ripgrep"
cargo = "ripgrep"
apt   = "ripgrep"

[[catalog]]
name  = "uv"
brew  = "uv"
shell = "curl -LsSf https://astral.sh/uv/install.sh | sh"

[[catalog]]
name = "my-private-tool"
shell = "curl -LsSf https://my.host/install.sh | sh"
```

**On `apply`, the plugin:**

1. Detects available managers (`brew`, `cargo`, `uv-tool`, `npm-global`, `apt`, `dnf`, `pacman`, plus `shell` fallback) and the OS/arch.
2. For each `[[package]]` without an explicit manager, picks the first available manager from the preference order. Default: `brew → cargo → uv-tool → npm-global → apt/dnf/pacman → shell`. Users override per-machine via `package_managers` in `~/.swap/config.toml` (e.g., embedded targets that shouldn't pull in brew).
3. Batches install calls per manager (`brew install a b c` once, not three times).
4. If no manager can satisfy a package, fails loudly with the list of unsatisfied packages — never silently skips.

Escape hatch for one-off oddities:

```toml
[[package]]
name    = "weird-pinned-thing"
manager = "apt"
package = "weird-thing=1.2.3"
```

### Tags

`when` is an OR'd list of tokens. Built-in tokens: `linux`, `darwin`, `windows`. User tokens come from `[plugins.devenv].tags` on the target machine. Examples: `when = "darwin"`, `when = "linux | jetson"`, `when = "laptop"`. No expression language — keeps the manifest declarative.

## Commands

```
swap devenv init <path>                    Scaffold a new devenv repo
swap devenv use <path-or-git-url>          Set the active devenv repo for this machine
swap devenv apply [--force] [--skip NAME]  Apply manifest to local machine
swap devenv capture [name…]                Pull local file state back into the repo
swap devenv push <ssh-alias>               Apply on a remote over SSH
swap devenv status                         Show drift, install state, package readiness
swap devenv diff <name>                    Unified diff for a single entry
swap devenv list                           Print manifest summary
swap devenv add <local-path>               Append [[file]] or [[directory]] entry (auto-detects)
swap devenv add package <name>             Append [[package]] entry
swap devenv remove <name>                  Remove an entry by name (deletes src for files/dirs)
```

`add` writes the manifest using **`tomlkit`** (round-trips formatting and comments) so hand-edited `devenv.toml` files survive verb-driven mutations.

## Drift safety

The hard part of using copies. Detected by content comparison:

- `replace` mode: byte-compare `dest` vs `<repo>/<src>`.
- `managed-block` mode: byte-compare the *between-markers* region of `dest` vs the full content of `<repo>/<src>`. Anything outside the markers is irrelevant.

`status` output:

```
Devenv status — repo: /home/swap/my-devenv  (tags: laptop, darwin-arm)

Files
  ✓ zshrc        ~/.zshrc                          in sync
  ! gitconfig    ~/.gitconfig                      drift (3 lines changed locally)
  ? nvim         ~/.config/nvim                    not yet applied here

Packages
  ✓ ripgrep      installed (brew)
  ✗ neovim       missing — run `swap devenv apply`

3 entries · 1 drifted · 1 missing on this machine
```

`apply` **refuses to overwrite drift by default**:

```
Refusing to apply: 1 file has uncaptured local changes.

  ! gitconfig    ~/.gitconfig    drift (3 lines)

Resolve with one of:
  swap devenv capture gitconfig    # pull local → repo (keep your edits)
  swap devenv apply --force        # repo → local (lose your edits)
  swap devenv apply --skip gitconfig
```

`--force` and `--skip` are deliberate, named escape hatches.

`capture`:

- No args → captures all drifted entries.
- `capture <name…>` → captures specific entries.
- For `replace` files: copy `dest` → `<repo>/<src>` verbatim.
- For `managed-block` files: extract content between markers, write to `<repo>/<src>` *without* markers (markers only live on the rendered form). Captured files have the same shape as hand-written ones.
- For `[[directory]]`: rsync-equivalent content sync, honoring `.devenvignore`.
- For `[[package]]` and `[[script]]`: no-op (unidirectional).
- Does **not** commit. Prints a hint:
  ```
  Captured 1 entry. Review and commit:
    git -C /home/swap/my-devenv diff
    git -C /home/swap/my-devenv commit -am "capture gitconfig from laptop"
  ```

**Trade-off:** the plugin does not maintain a "last-applied" snapshot, so it cannot do three-way diff. Two-way is sufficient for a personal tool — the user reads the diff and decides direction. This avoids state-management overhead in `~/.swap/`.

## Push to remote

`swap devenv push <ssh-alias>`:

1. Resolves `<ssh-alias>` from `~/.ssh/config` (managed by the existing `ssh` plugin).
2. rsyncs the active devenv repo to `~/.swap/devenv-staging/` on the remote.
3. SSHs in and runs `swap devenv apply` there. The remote's own `~/.swap/config.toml` decides which `tags` and `package_managers` apply.
4. Drift safety on the remote behaves identically: push aborts if the remote has uncaptured edits, with the same `--force` / `--skip` escape hatches passed through.

The remote must already have swap installed. (Bootstrap-on-push is deferred from v1.)

## Repo layout (recommended, not enforced)

```
my-devenv/
├── README.md              # generated by `swap devenv init`
├── devenv.toml            # the manifest
├── .devenvignore          # optional, repo-wide rsync excludes (also per-directory)
├── zsh/zshrc
├── git/gitconfig
├── vscode/settings.json
├── nvim/                  # whole-tree directory entry
│   ├── init.lua
│   └── lua/
└── scripts/
    └── build-essential.sh
```

## Out of scope for v1 (deferred)

- Templating / variable substitution in files.
- Three-way merge / last-applied snapshot.
- Secrets handling (`sops`, `age`).
- Bootstrap-on-push (auto-install swap on the remote).
- `add script` verb (manifest hand-edit).
- Manager-specific version pinning beyond `manager + package` escape hatch.
- Lockfile (`Brewfile.lock`-style version capture across machines).

## Open questions

- **Catalog hosting.** v1 ships the catalog bundled with the plugin. If it grows, do we move it to a separate fetched-and-cached file (like the swap registry)? Decision deferred until the bundled catalog hits ~50 entries.
- **Windows support.** Not in v1. The manifest format is OS-agnostic, but managed-block markers, directory paths, and the package manager set all need Windows-specific treatment.

## Implementation dependencies

- `click` (already in swap's stack)
- `tomlkit` — comment-preserving TOML round-trip for `add`/`remove`
- `tomllib` (stdlib, Python 3.11+) — read-only manifest parsing
- `paramiko` (already in swap's stack via `ssh` plugin) for SSH operations on push

## Test surface

- Manifest parsing: invalid types, unknown entry kinds, duplicate names.
- Tag matching: linux/darwin, custom tags, OR'd lists.
- Drift detection: replace mode, managed-block mode (markers present / absent / malformed).
- Apply: idempotency (apply twice → no change), `--force`, `--skip`.
- Capture: replace, managed-block (markers stripped), directory.
- Catalog resolution: tool present in catalog, tool missing, manager preference order honored, per-machine override honored.
- Add/remove: comment preservation in `devenv.toml`.
- Push: dry-run path (don't require live remote in CI; mock the SSH layer).
