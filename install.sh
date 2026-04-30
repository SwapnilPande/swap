#!/usr/bin/env bash
set -e

echo "Installing swap..."

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo "  uv not found, installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env"
fi

# Install swap as a uv tool
uv tool install git+https://github.com/SwapnilPande/swap

echo ""
echo "swap installed. Run 'swap' to get started."
