"""Consistent styling helpers for swap CLI output.

Centralizes the color/style palette so commands stay visually coherent.
Uses Click's built-in styling (no extra dependency).
"""
from __future__ import annotations

import click


def header(text: str) -> str:
    """Section heading, e.g. 'Installed plugins'."""
    return click.style(text, fg="cyan", bold=True)


def name(text: str) -> str:
    """A plugin or command name."""
    return click.style(text, bold=True)


def dim(text: str) -> str:
    """De-emphasized text — descriptions, hints, secondary info."""
    return click.style(text, dim=True)


def value(text: str) -> str:
    """Inline value the user might copy, e.g. a hostname or path."""
    return click.style(text, fg="cyan")


def success(text: str) -> str:
    return click.style(text, fg="green")


def warn(text: str) -> str:
    return click.style(text, fg="yellow")


def error(text: str) -> str:
    return click.style(text, fg="red", bold=True)


def check() -> str:
    return click.style("✓", fg="green", bold=True)


def cross() -> str:
    return click.style("✗", fg="red", bold=True)


def bullet() -> str:
    return click.style("•", dim=True)
