# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent's provider layer. Must never import Gtk or Adw (see tests/test_layering.py).

Pins the versions of the GLib libraries the layer uses, so its modules can
import them directly.
"""

from __future__ import annotations

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Gio", "2.0")

APP_ID = "io.github.orkwitzel.Agent"
