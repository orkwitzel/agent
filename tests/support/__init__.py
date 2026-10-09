# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers shared by the tests: paths to the fake claude and its fixtures, and `run`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent.core.mainloop import install_glib_event_loop

SUPPORT = Path(__file__).resolve().parent
FIXTURES = SUPPORT / "fixtures"
FAKE_CLAUDE = SUPPORT / "fake_claude.py"


def run(coro):
    """Run `coro` to completion on a fresh GLib-backed event loop."""
    install_glib_event_loop()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
