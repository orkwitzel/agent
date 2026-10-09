# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the user's `claude` binary and reading its login state.

Agent never reads, stores or refreshes credentials. It only asks
`claude auth status` (and `claude --version` when that prints no
status) and, to sign in, runs `claude auth login`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

from gi.repository import GLib
from pydantic import Field, ValidationError

from agent.core import hostspawn
from agent.core.model import WireModel
from agent.core.process import run_capture

DOWNLOAD_URL = "https://code.claude.com/docs/en/setup"

# Where Anthropic's installer puts claude, for when PATH doesn't include it.
_FALLBACK_LOCATIONS = ("~/.local/bin/claude", "~/.claude/local/claude")

# What the app can do with the user's claude.
type ClaudeState = Literal["ready", "signed-out", "missing"]


class AuthStatus(WireModel):
    """What `claude auth status` reports. Never includes credentials."""

    logged_in: bool = Field(alias="loggedIn")
    method: str | None = Field(default=None, alias="authMethod")
    subscription: str | None = Field(default=None, alias="subscriptionType")


def find_claude(*, configured_path: str = "", flatpak: bool | None = None) -> str | None:
    """Resolve the claude executable.

    Natively: the configured path, PATH, then the installer's locations.

    In Flatpak the sandbox's PATH says nothing about the host's, so it
    isn't searched. `--filesystem=host` shows the installer's locations
    at the same paths as on the host, so those are tried; failing that,
    plain "claude" is returned for `flatpak-spawn --host` to look up on
    the host's PATH. Whether that exists is only known once it runs
    (see `check_claude`).
    """
    if configured_path:
        return configured_path
    if flatpak is None:
        flatpak = hostspawn.in_flatpak()
    if not flatpak:
        found = shutil.which("claude")
        if found:
            return found
    for candidate in _FALLBACK_LOCATIONS:
        path = Path(candidate).expanduser()
        if os.access(path, os.X_OK):
            return str(path)
    return "claude" if flatpak else None


def auth_status_argv(claude_path: str) -> list[str]:
    return [claude_path, "auth", "status"]


def auth_login_argv(claude_path: str) -> list[str]:
    return [claude_path, "auth", "login"]


def version_argv(claude_path: str) -> list[str]:
    return [claude_path, "--version"]


def parse_auth_status(output: str) -> AuthStatus | None:
    """Parse the JSON that `claude auth status` prints.

    Returns None when the output isn't a JSON object with a boolean
    `loggedIn`, meaning claude didn't run or printed something else.
    The exit status can't tell the two apart: claude exits 1 when signed
    out, and in Flatpak `flatpak-spawn --host` exits 1 with no output
    when claude isn't on the host's PATH. `check_claude` asks
    `claude --version` to tell them apart.
    """
    try:
        return AuthStatus.model_validate_json(output)
    except ValidationError:
        return None


async def check_claude(*, configured_path: str = "", flatpak: bool | None = None) -> ClaudeState:
    """Find claude and ask it whether the user is signed in.

    The exit status of `claude auth status` is ignored: claude exits 1
    when signed out. If it prints no status (see `parse_auth_status`),
    `claude --version` decides: if claude runs at all, offer to sign in.
    """
    claude = find_claude(configured_path=configured_path, flatpak=flatpak)
    if claude is None:
        return "missing"
    try:
        _status, output = await run_capture(
            hostspawn.host_argv(auth_status_argv(claude), flatpak=flatpak)
        )
        auth = parse_auth_status(output)
        if auth is None:
            status, _output = await run_capture(
                hostspawn.host_argv(version_argv(claude), flatpak=flatpak)
            )
            return "signed-out" if status == 0 else "missing"
    except GLib.Error:  # Couldn't spawn it.
        return "missing"
    return "ready" if auth.logged_in else "signed-out"
