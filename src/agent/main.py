# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point: run the application on the GLib main loop."""

from __future__ import annotations

import sys

from agent.core.mainloop import install_glib_event_loop
from agent.ui.application import AgentApplication


def main(version: str) -> int:
    """Run Agent; returns the exit status."""
    install_glib_event_loop()
    return AgentApplication(version).run(sys.argv)
