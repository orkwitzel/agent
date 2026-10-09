# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent's GTK layer: windows and widgets bound to the state in agent.core.

Pins the GTK and libadwaita versions, so its modules can import them directly.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

# The GResource prefix of the compiled UI files (see src/agent.gresource.xml).
RESOURCE_PATH = "/io/github/orkwitzel/Agent"
