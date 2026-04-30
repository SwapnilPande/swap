from __future__ import annotations

import subprocess


def upgrade_swap() -> None:
    """Upgrade swap using uv tool upgrade."""
    subprocess.run(["uv", "tool", "upgrade", "swap"], check=True)
