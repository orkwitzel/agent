# SPDX-License-Identifier: GPL-3.0-or-later
"""Registering commands as Gio actions."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gio, GLib


def add_action(group: Gio.ActionMap, name: str, callback: Callable[[], None]) -> None:
    """Add a parameterless action `name` to `group` that calls `callback`.

    Buttons and menus reach it as "app.<name>" or "win.<name>"; shortcuts
    are set with `Gtk.Application.set_accels_for_action`.
    """
    action = Gio.SimpleAction.new(name, None)

    def on_action_activate(_action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        callback()

    action.connect("activate", on_action_activate)
    group.add_action(action)
