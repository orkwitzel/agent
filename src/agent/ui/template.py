# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed access to Blueprint template children."""

from __future__ import annotations

from gi.repository import Gtk


def child[W: Gtk.Widget](widget_type: type[W]) -> W:
    """Declare a template child of type `widget_type`, like `Gtk.Template.Child()`.

    The stubs type `Gtk.Template.Child()` as Any. On an instance the attribute
    holds the widget the template built, so the annotation is accurate there.
    """
    return Gtk.Template.Child()  # pyright: ignore[reportAny]  # stub types it as Any
