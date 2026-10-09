# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from gettext import gettext as _

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from agent.core import APP_ID  # noqa: E402
from agent.core.claude_cli import ClaudeStatus  # noqa: E402
from agent.core.process import install_glib_event_loop  # noqa: E402
from agent.core.projects import ProjectList  # noqa: E402
from agent.core.store import Store, database_path  # noqa: E402
from agent.core.tasks import TaskSet  # noqa: E402
from agent.ui.actions import add_action  # noqa: E402
from agent.ui.preferences import PreferencesDialog  # noqa: E402
from agent.ui.window import AgentWindow  # noqa: E402


class AgentApplication(Adw.Application):
    def __init__(self, version: str):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            resource_base_path="/io/github/orkwitzel/Agent",
        )
        self._version = version
        self._settings = Gio.Settings.new(APP_ID)
        self._store = Store(database_path(GLib.get_user_data_dir()))
        self._projects = ProjectList(self._store)
        self._claude = ClaudeStatus()
        self._tasks = TaskSet()
        add_action(self, "quit", self._quit)
        add_action(self, "about", self._show_about)
        add_action(self, "preferences", self._show_preferences)
        self.set_accels_for_action("app.quit", ["<primary>q"])
        self.set_accels_for_action("app.preferences", ["<primary>comma"])

    def do_activate(self):
        window = self.get_active_window() or AgentWindow(
            application=self,
            settings=self._settings,
            projects=self._projects,
            claude=self._claude,
            tasks=self._tasks,
        )
        window.present()

    def do_shutdown(self):
        self._store.close()
        Adw.Application.do_shutdown(self)

    def _quit(self):
        # Each window confirms on close if threads are still running.
        for win in self.get_windows():
            win.close()

    def _show_about(self):
        about = Adw.AboutDialog(
            application_name="Agent",
            application_icon=APP_ID,
            developer_name="Or Kwitzel",
            version=self._version,
            website="https://github.com/orkwitzel/agent",
            issue_url="https://github.com/orkwitzel/agent/issues",
            license_type="gpl-3-0",
            comments=_("Agent is not affiliated with or endorsed by Anthropic."),
            copyright="© 2026 Or Kwitzel",
        )
        about.present(self.get_active_window())

    def _show_preferences(self):
        PreferencesDialog(self._settings).present(self.get_active_window())


def main(version: str) -> int:
    install_glib_event_loop()
    app = AgentApplication(version)
    return app.run(sys.argv)
