# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from gettext import gettext as _

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from agent.core import APP_ID  # noqa: E402
from agent.core.process import install_glib_event_loop  # noqa: E402
from agent.ui.preferences import PreferencesDialog  # noqa: E402
from agent.ui.window import AgentWindow  # noqa: E402


class AgentApplication(Adw.Application):
    def __init__(self, version: str):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            resource_base_path="/io/github/orkwitzel/Agent",
        )
        self.version = version
        self.settings = Gio.Settings.new(APP_ID)
        self._add_action("quit", lambda *_: self._quit(), ["<primary>q"])
        self._add_action("about", self._on_about)
        self._add_action("preferences", self._on_preferences, ["<primary>comma"])

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = AgentWindow(application=self)
        win.present()

    def _quit(self):
        # Each window confirms on close if threads are still running.
        for win in self.get_windows():
            win.close()

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name="Agent",
            application_icon=APP_ID,
            developer_name="Or Kwitzel",
            version=self.version,
            website="https://github.com/orkwitzel/agent",
            issue_url="https://github.com/orkwitzel/agent/issues",
            license_type="gpl-3-0",
            comments=_("Agent is not affiliated with or endorsed by Anthropic."),
            copyright="© 2026 Or Kwitzel",
        )
        about.present(self.props.active_window)

    def _on_preferences(self, *_args):
        PreferencesDialog(self.settings).present(self.props.active_window)

    def _add_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version: str) -> int:
    install_glib_event_loop()
    app = AgentApplication(version)
    return app.run(sys.argv)
