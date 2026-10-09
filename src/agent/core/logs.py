# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging set up the way GLib's is, so debug output works like any GNOME app's."""

from __future__ import annotations

import logging

from agent.core import APP_ID


def configure_logging(messages_debug: str) -> None:
    """Send warnings and up to stderr, plus our debug logs if `G_MESSAGES_DEBUG` asks.

    Call it once, from `main`. `messages_debug` is the variable's value.
    """
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(levelname)s: %(message)s")
    if debug_enabled(messages_debug):
        logging.getLogger("agent").setLevel(logging.DEBUG)


def debug_enabled(messages_debug: str) -> bool:
    """Whether `G_MESSAGES_DEBUG` names our app or "all", as GLib reads it."""
    domains = messages_debug.replace(",", " ").split()
    return "all" in domains or APP_ID in domains
