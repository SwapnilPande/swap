# swap

A beautiful, Python-based CLI tool containing all common useful utilities in one place.

## Features

### SSH Config Tool
A terminal UI (TUI) powered by `textual` that simplifies the process of setting up new SSH hosts.

- **Automatic Key Generation**: Generates `ed25519` key pairs if they don't already exist.
- **Remote Key Deployment**: Connects via password authentication to push your public key to the remote host.
- **Local Config Management**: Automatically updates your `~/.ssh/config` file with a new Host entry.
- **Beautiful TUI**: Modern, responsive terminal interface.

## Installation

Ensure you have `uv` installed. Clone the repository and install it in editable mode:

```bash
uv pip install -e .
```

## Usage

Run the main utility:

```bash
swap --help
```

### Configure a New SSH Host

To launch the SSH configuration tool:

```bash
swap ssh-config
```

Fill out the form with the host alias, IP address, username, and desired key name. The tool will handle the rest!

## Development

Dependencies:
- `click`: CLI framework
- `textual`: TUI framework
- `paramiko`: SSH implementation
