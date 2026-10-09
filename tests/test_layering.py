# SPDX-License-Identifier: GPL-3.0-or-later
"""agent.core must stay free of GTK so providers can be tested headless."""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "src" / "agent" / "core"
FORBIDDEN = {"Gtk", "Adw", "Gdk", "GtkSource", "Vte", "agent.ui"}


def imported_names(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_core_does_not_import_ui():
    for path in CORE.rglob("*.py"):
        bad = FORBIDDEN.intersection(imported_names(path))
        assert not bad, f"{path.relative_to(CORE)} imports {bad}"
