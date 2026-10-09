# SPDX-License-Identifier: GPL-3.0-or-later
"""The Preferences dialog. Every row is bound to a GSettings key."""

from __future__ import annotations

from gi.repository import Adw, Gio, Gtk

from agent.ui import RESOURCE_PATH, template


@Gtk.Template(resource_path=f"{RESOURCE_PATH}/ui/preferences.ui")
class PreferencesDialog(Adw.PreferencesDialog):
    """Preferences, stored in GSettings as soon as they change."""

    __gtype_name__ = "AgentPreferencesDialog"

    claude_path_row = template.child(Adw.EntryRow)
    default_model_row = template.child(Adw.EntryRow)
    generate_titles_row = template.child(Adw.SwitchRow)
    token_counts_row = template.child(Adw.SwitchRow)
    updates_row = template.child(Adw.SwitchRow)

    def __init__(self, settings: Gio.Settings) -> None:
        super().__init__()
        flags = Gio.SettingsBindFlags.DEFAULT
        settings.bind("claude-path", self.claude_path_row, "text", flags)
        settings.bind("default-model", self.default_model_row, "text", flags)
        settings.bind("generate-titles", self.generate_titles_row, "active", flags)
        settings.bind("show-token-counts", self.token_counts_row, "active", flags)
        settings.bind("check-for-updates", self.updates_row, "active", flags)
