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

DOWNLOAD_URL = "https://code.claude.com/docs/en/setup"

# Where Anthropic's installer puts claude, for when PATH doesn't include it.
_FALLBACK_LOCATIONS = ("~/.local/bin/claude", "~/.claude/local/claude")


@dataclass(frozen=True)
class AuthStatus:
    logged_in: bool
    method: str | None = None
    subscription: str | None = None


def find_claude(configured_path: str = "") -> str | None:
    """Resolve the claude executable on this side of the sandbox.

    In Flatpak the binary lives on the host, so we can't check it here;
    the configured path or plain "claude" is passed through and checked
    by running `claude auth status` on the host instead.
    """
    if configured_path:
        return configured_path
    if os.path.exists("/.flatpak-info"):
        return "claude"
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _FALLBACK_LOCATIONS:
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return None


def auth_status_argv(claude_path: str) -> list[str]:
    return [claude_path, "auth", "status"]


def auth_login_argv(claude_path: str) -> list[str]:
    return [claude_path, "auth", "login"]


def parse_auth_status(output: str) -> AuthStatus:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return AuthStatus(logged_in=False)
    if not isinstance(data, dict):
        return AuthStatus(logged_in=False)
    return AuthStatus(
        logged_in=bool(data.get("loggedIn", False)),
        method=data.get("authMethod"),
        subscription=data.get("subscriptionType"),
    )
