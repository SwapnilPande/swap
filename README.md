# swap

Personal utilities CLI, extensible via plugins.

## Install

```bash
curl -sSL https://raw.githubusercontent.com/swapnil/swap/main/install.sh | bash
```

Or for development:

```bash
uv tool install --editable .
```

## Usage

```bash
swap                      # show installed plugins
swap plugins list         # browse available plugins
swap plugins install ssh  # install a plugin
swap ssh setup            # set up SSH key auth for a new host
swap upgrade              # upgrade swap itself
```

## Plugins

swap is built around plugins. Each plugin is a separate Python package registered under the `swap.plugins` entry point group.

Built-in plugins:
- `ssh` — SSH key generation, key push, and `~/.ssh/config` management
- `plugins` — browse, install, uninstall, and scaffold plugins

## Developing a Plugin

```bash
swap plugins new myplugin       # scaffold boilerplate
cd swap-myplugin
swap plugins dev .              # install in editable mode
swap myplugin example           # try it out
```

## Dependencies

- `click` — CLI framework
- `questionary` — interactive prompts
- `paramiko` — SSH
- `requests` — registry fetching
- `tomli-w` — config writes
