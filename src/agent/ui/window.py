# SPDX-License-Identifier: GPL-3.0-or-later

from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from agent.core import claude_cli
from agent.core.claude_cli import ClaudeStatus
from agent.core.projects import ProjectList
from agent.core.tasks import TaskSet
from agent.ui.actions import add_action


@Gtk.Template(resource_path="/io/github/orkwitzel/Agent/ui/window.ui")
class AgentWindow(Adw.ApplicationWindow):
    __gtype_name__ = "AgentWindow"

    split_view = Gtk.Template.Child()
    sidebar_stack = Gtk.Template.Child()
    project_list = Gtk.Template.Child()
    content_stack = Gtk.Template.Child()
    download_link = Gtk.Template.Child()

    def __init__(
        self,
        *,
        application: Adw.Application,
        settings: Gio.Settings,
        projects: ProjectList,
        claude: ClaudeStatus,
        tasks: TaskSet,
    ):
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
            lambda _binding, n_items: "projects" if n_items else "empty",
        )
        # The stack's pages are named after the states.
        claude.bind_property(
            "state", self.content_stack, "visible-child-name", GObject.BindingFlags.SYNC_CREATE
        )

        self._restore_size()
        add_action(self, "add-project", self._add_project)
        add_action(self, "check-claude", self._check_claude)
        self._check_claude()

    def _check_claude(self):
        configured_path = self._settings.get_string("claude-path")
        self._tasks.spawn(self._claude.check(configured_path=configured_path))

    def _add_project(self):
        self._tasks.spawn(self._pick_project())

    async def _pick_project(self):
        dialog = Gtk.FileDialog(title=_("Add Project"), modal=True)
        try:
            folder = await dialog.select_folder(self, None)
        except GLib.Error:
            return  # Cancelled.
        path = folder.get_path()
        if path:
            self._projects.add(path)

    # Window state

    def _restore_size(self):
        self.set_default_size(
            self._settings.get_int("window-width"), self._settings.get_int("window-height")
        )
        if self._settings.get_boolean("window-maximized"):
            self.maximize()

    def do_close_request(self):
        width, height = self.get_default_size()
        self._settings.set_int("window-width", width)
        self._settings.set_int("window-height", height)
        self._settings.set_boolean("window-maximized", self.is_maximized())
        return False
