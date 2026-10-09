# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FIXTURES = ROOT / "tests" / "fixtures"
FAKE_CLAUDE = ROOT / "tests" / "fake_claude.py"


def run(coro):
    """Run `coro` to completion on a fresh GLib-backed event loop."""
    from agent.core.process import install_glib_event_loop

    install_glib_event_loop()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
