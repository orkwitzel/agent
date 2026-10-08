# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the user's `claude` binary and reading its login state.

Agent never reads, stores or refreshes credentials. It only asks
`claude auth status` and, to sign in, runs `claude auth login`.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass

from agent.core import hostspawn

DOWNLOAD_URL = "https://code.claude.com/docs/en/setup"

# Where Anthropic's installer puts claude, for when PATH doesn't include it.
_FALLBACK_LOCATIONS = ("~/.local/bin/claude", "~/.claude/local/claude")


@dataclass(frozen=True)
class AuthStatus:
    logged_in: bool
    method: str | None = None
    subscription: str | None = None


def find_claude(configured_path: str = "", *, flatpak: bool | None = None) -> str | None:
    """Resolve the claude executable.

    Natively: the configured path, PATH, then the installer's locations.

    In Flatpak the sandbox's PATH says nothing about the host's, so it
    isn't searched. `--filesystem=host` shows the installer's locations
    at the same paths as on the host, so those are tried; failing that,
    plain "claude" is returned for `flatpak-spawn --host` to look up on
    the host's PATH. Whether that exists is only known once
    `claude auth status` runs (see `parse_auth_status`).
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
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return "claude" if flatpak else None


def auth_status_argv(claude_path: str) -> list[str]:
    return [claude_path, "auth", "status"]


def auth_login_argv(claude_path: str) -> list[str]:
    return [claude_path, "auth", "login"]


def parse_auth_status(output: str) -> AuthStatus | None:
    """Parse the JSON that `claude auth status` prints.

    Returns None when the output isn't a JSON object, meaning claude
    didn't run or printed something unexpected. The exit status can't
    tell the two apart: claude exits 1 when signed out, and in Flatpak
    `flatpak-spawn --host` exits non-zero with no output when claude
    isn't on the host's PATH.
    """
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return AuthStatus(
        logged_in=bool(data.get("loggedIn", False)),
        method=data.get("authMethod"),
        subscription=data.get("subscriptionType"),
    )
