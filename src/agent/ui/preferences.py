# SPDX-License-Identifier: GPL-3.0-or-later

from gi.repository import Adw, Gio, Gtk


@Gtk.Template(resource_path="/io/github/orkwitzel/Agent/ui/preferences.ui")
class PreferencesDialog(Adw.PreferencesDialog):
    __gtype_name__ = "AgentPreferencesDialog"

    claude_path_row = Gtk.Template.Child()
    default_model_row = Gtk.Template.Child()
    generate_titles_row = Gtk.Template.Child()
    token_counts_row = Gtk.Template.Child()
    updates_row = Gtk.Template.Child()

    def __init__(self, settings: Gio.Settings, **kwargs):
        super().__init__(**kwargs)
        flags = Gio.SettingsBindFlags.DEFAULT
        settings.bind("claude-path", self.claude_path_row, "text", flags)
        settings.bind("default-model", self.default_model_row, "text", flags)
        settings.bind("generate-titles", self.generate_titles_row, "active", flags)
        settings.bind("show-token-counts", self.token_counts_row, "active", flags)
        settings.bind("check-for-updates", self.updates_row, "active", flags)
