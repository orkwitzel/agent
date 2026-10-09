# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window: projects in the sidebar, the thread or Claude's status beside them."""

from __future__ import annotations

from gettext import gettext as _
from typing import override

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from agent.core import claude_cli
from agent.core.claude_cli import ClaudeStatus
from agent.core.mainloop import TaskSet, gio_call
from agent.core.projects import ProjectList
from agent.ui import RESOURCE_PATH, template
from agent.ui.actions import add_action


@Gtk.Template(resource_path=f"{RESOURCE_PATH}/ui/window.ui")
class AgentWindow(Adw.ApplicationWindow):
    """The main window. It binds to the app's state and forwards actions to it."""

    __gtype_name__ = "AgentWindow"

    sidebar_stack = template.child(Gtk.Stack)
    project_list = template.child(Gtk.ListView)
    content_stack = template.child(Gtk.Stack)
    download_link = template.child(Gtk.LinkButton)

    def __init__(
        self,
        *,
        application: Adw.Application,
        settings: Gio.Settings,
        projects: ProjectList,
        claude: ClaudeStatus,
        tasks: TaskSet,
    ) -> None:
        super().__init__(application=application)
        self._settings = settings
        self._projects = projects
        self._claude = claude
        self._tasks = tasks

        self.download_link.set_uri(claude_cli.DOWNLOAD_URL)
        self.project_list.set_model(Gtk.NoSelection.new(projects.items))
        projects.items.bind_property(
            "n-items",
            self.sidebar_stack,
            "visible-child-name",
            GObject.BindingFlags.SYNC_CREATE,
            _sidebar_page,
        )
        # The stack's pages are named after the states.
        claude.bind_property(
            "state", self.content_stack, "visible-child-name", GObject.BindingFlags.SYNC_CREATE
        )

        self._restore_size()
        add_action(self, "add-project", self._add_project)
        add_action(self, "check-claude", self._check_claude)
        self._check_claude()

    @override
    def do_close_request(self) -> bool:
        width, height = self.get_default_size()
        self._settings.set_int("window-width", width)
        self._settings.set_int("window-height", height)
        self._settings.set_boolean("window-maximized", self.is_maximized())
        return False

    def _check_claude(self) -> None:
        configured_path = self._settings.get_string("claude-path")
        self._tasks.spawn(self._claude.check(configured_path=configured_path))

    def _add_project(self) -> None:
        self._tasks.spawn(self._pick_project())

    async def _pick_project(self) -> None:
        dialog = Gtk.FileDialog(title=_("Add Project"), modal=True)
        try:
            folder = await gio_call(dialog.select_folder, dialog.select_folder_finish, self)
        except GLib.Error:
            return  # Dismissed.
        path = folder.get_path()
        if path:
            self._projects.add(path)

    def _restore_size(self) -> None:
        self.set_default_size(
            self._settings.get_int("window-width"), self._settings.get_int("window-height")
        )
        if self._settings.get_boolean("window-maximized"):
            self.maximize()


def _sidebar_page(_binding: GObject.Binding, n_items: int) -> str:
    return "projects" if n_items else "empty"
