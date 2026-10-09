# SPDX-License-Identifier: GPL-3.0-or-later
"""The Adw.Application: app-wide state, app actions and the About dialog."""

from __future__ import annotations

from gettext import gettext as _
from typing import override

from gi.repository import Adw, Gio, GLib, Gtk

from agent.core import APP_ID
from agent.core.claude_cli import ClaudeStatus
from agent.core.mainloop import TaskSet
from agent.core.projects import ProjectList
from agent.core.store import Store, database_path
from agent.ui import RESOURCE_PATH
from agent.ui.actions import add_action
from agent.ui.preferences import PreferencesDialog
from agent.ui.window import AgentWindow


class AgentApplication(Adw.Application):
    """The application: owns the app's state and hands it to its window."""

    def __init__(self, version: str) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            resource_base_path=RESOURCE_PATH,
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

    @override
    def do_activate(self) -> None:
        window = self.get_active_window() or AgentWindow(
            application=self,
            settings=self._settings,
            projects=self._projects,
            claude=self._claude,
            tasks=self._tasks,
        )
        window.present()

    @override
    def do_shutdown(self) -> None:
        self._store.close()
        Adw.Application.do_shutdown(self)

    def _quit(self) -> None:
        # Each window confirms on close if threads are still running.
        for window in self.get_windows():
            window.close()

    def _show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name="Agent",
            application_icon=APP_ID,
            developer_name="Or Kwitzel",
            version=self._version,
            website="https://github.com/orkwitzel/agent",
            issue_url="https://github.com/orkwitzel/agent/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=_("Agent is not affiliated with or endorsed by Anthropic."),
            copyright="© 2026 Or Kwitzel",
        )
        about.present(self.get_active_window())

    def _show_preferences(self) -> None:
        PreferencesDialog(self._settings).present(self.get_active_window())
