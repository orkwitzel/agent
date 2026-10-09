# SPDX-License-Identifier: GPL-3.0-or-later
"""Every external command goes through here.

Inside Flatpak, commands run on the host via `flatpak-spawn --host`.
Agent threads additionally run in their own systemd user scope, so the
whole process tree (claude, MCP servers, shell tools) can be stopped as
one unit, and later frozen and reclaimed while idle.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.core import APP_ID

FLATPAK_INFO = "/.flatpak-info"


def in_flatpak() -> bool:
    """Whether Agent runs inside a Flatpak sandbox."""
    return Path(FLATPAK_INFO).exists()


def scope_unit_name(thread_id: int, nonce: str) -> str:
    """The systemd scope a thread's process tree runs in. `nonce` keeps it unique."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", nonce)
    return f"app-{APP_ID}-thread{thread_id}-{safe}.scope"


def host_argv(
    argv: list[str],
    *,
    cwd: str | None = None,
    scope_unit: str | None = None,
    flatpak: bool | None = None,
) -> list[str]:
    """Wrap `argv` so it runs on the host, optionally in a systemd scope."""
    if flatpak is None:
        flatpak = in_flatpak()

    command = list(argv)
    if scope_unit:
        command = [
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            f"--unit={scope_unit}",
            "--",
            *command,
        ]

    if flatpak:
        prefix = ["flatpak-spawn", "--host", "--watch-bus"]
        if cwd:
            prefix.append(f"--directory={cwd}")
        command = [*prefix, *command]

    return command
