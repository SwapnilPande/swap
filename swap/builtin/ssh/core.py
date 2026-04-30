from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paramiko


@dataclass
class SSHSetupResult:
    alias: str
    hostname: str
    username: str
    key_path: Path
    key_generated: bool
    key_pushed: bool
    config_updated: bool


def generate_keypair(key_path: Path, key_type: str = "ed25519") -> bool:
    """Generate an SSH keypair at key_path. Returns True if generated, False if already existed."""
    if key_path.exists():
        return False
    key_path.parent.mkdir(mode=0o700, exist_ok=True)
    result = subprocess.run(
        ["ssh-keygen", "-t", key_type, "-f", str(key_path), "-N", ""],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {result.stderr.decode().strip()}")
    return True


def push_public_key(hostname: str, username: str, password: str, pub_key: str) -> bool:
    """Push pub_key to authorized_keys on the remote host via SFTP.

    Returns True if the key was appended, False if it was already present.
    Uses SFTP to avoid shell injection. AutoAddPolicy is intentional for a personal tool.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password, timeout=10)
    try:
        with client.open_sftp() as sftp:
            try:
                sftp.stat(".ssh")
            except FileNotFoundError:
                sftp.mkdir(".ssh")
                sftp.chmod(".ssh", 0o700)

            existing = ""
            try:
                with sftp.open(".ssh/authorized_keys", "r") as f:
                    existing = f.read().decode()
            except (IOError, FileNotFoundError):
                pass

            if pub_key in existing:
                return False

            with sftp.open(".ssh/authorized_keys", "a") as f:
                f.write(f"\n{pub_key}\n".encode())
            sftp.chmod(".ssh/authorized_keys", 0o600)
            return True
    finally:
        client.close()


def add_config_entry(
    alias: str,
    hostname: str,
    username: str,
    key_path: Path,
    config_path: Optional[Path] = None,
) -> bool:
    """Add a Host block to the SSH config file.

    Returns True if written, False if the alias already existed.
    config_path defaults to ~/.ssh/config (override for testing).
    """
    if config_path is None:
        config_path = Path.home() / ".ssh" / "config"

    entry = f"\nHost {alias}\n    HostName {hostname}\n    User {username}\n    IdentityFile {key_path}\n"

    if config_path.exists():
        content = config_path.read_text()
        if re.search(rf"^Host\s+{re.escape(alias)}\s*$", content, re.MULTILINE):
            return False
        config_path.write_text(content + entry)
    else:
        config_path.parent.mkdir(mode=0o700, exist_ok=True)
        config_path.write_text(entry.lstrip())
    return True


def setup(
    alias: str,
    hostname: str,
    username: str,
    key_name: str,
    password: str,
    key_type: str = "ed25519",
) -> SSHSetupResult:
    """Full SSH setup: generate keypair, push to remote, update local config."""
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    key_path = ssh_dir / key_name

    key_generated = generate_keypair(key_path, key_type)
    pub_key_path = key_path.with_suffix(".pub")
    if not pub_key_path.exists():
        raise FileNotFoundError(
            f"Public key not found at {pub_key_path}. "
            "Run generate_keypair() first or check key file integrity."
        )
    pub_key = pub_key_path.read_text().strip()
    key_pushed = push_public_key(hostname, username, password, pub_key)
    config_updated = add_config_entry(alias, hostname, username, key_path)

    return SSHSetupResult(
        alias=alias,
        hostname=hostname,
        username=username,
        key_path=key_path,
        key_generated=key_generated,
        key_pushed=key_pushed,
        config_updated=config_updated,
    )
