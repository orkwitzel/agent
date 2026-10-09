# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, Gtk

from agent.core import claude_cli, hostspawn
from agent.core.process import run_capture
from agent.core.store import Project, Store, database_path


@Gtk.Template(resource_path="/io/github/orkwitzel/Agent/ui/window.ui")
class AgentWindow(Adw.ApplicationWindow):
    __gtype_name__ = "AgentWindow"

    split_view = Gtk.Template.Child()
    sidebar_stack = Gtk.Template.Child()
    project_list = Gtk.Template.Child()
    content_stack = Gtk.Template.Child()
    download_link = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings = self.get_application().settings
        self.store = Store(database_path(GLib.get_user_data_dir()))
        self._tasks: set[asyncio.Task] = set()

        self.download_link.set_uri(claude_cli.DOWNLOAD_URL)
        self._restore_size()
        self._add_window_action("add-project", self._on_add_project)
        self._add_window_action("check-claude", lambda *_: self._spawn(self._check_claude()))

        self._reload_projects()
        self._spawn(self._check_claude())

    # Claude detection

    async def _check_claude(self):
        self.content_stack.set_visible_child_name("checking")
        claude = claude_cli.find_claude(self.settings.get_string("claude-path"))
        if claude is None:
            self.content_stack.set_visible_child_name("missing")
            return
        argv = hostspawn.host_argv(claude_cli.auth_status_argv(claude))
        try:
            _status, output = await run_capture(argv)
        except GLib.Error:
            self.content_stack.set_visible_child_name("missing")
            return
        # The exit status is ignored: claude exits 1 when signed out.
        auth = claude_cli.parse_auth_status(output)
        if auth is None:
            # No status to read. If claude runs at all, offer to sign in.
            argv = hostspawn.host_argv(claude_cli.version_argv(claude))
            status, _output = await run_capture(argv)
            page = "signed-out" if status == 0 else "missing"
        elif auth.logged_in:
            page = "ready"
        else:
            page = "signed-out"
        self.content_stack.set_visible_child_name(page)

    # Projects

    def _on_add_project(self, *_args):
        dialog = Gtk.FileDialog(title=_("Add Project"), modal=True)
        self._spawn(self._pick_project(dialog))

    async def _pick_project(self, dialog: Gtk.FileDialog):
        try:
            folder = await dialog.select_folder(self, None)
        except GLib.Error:
            return  # Cancelled.
        path = folder.get_path()
        if path:
            self.store.add_project(path)
            self._reload_projects()

    def _reload_projects(self):
        self.project_list.remove_all()
        projects = self.store.projects()
        for project in projects:
            self.project_list.append(self._project_row(project))
        self.sidebar_stack.set_visible_child_name("projects" if projects else "empty")

    def _project_row(self, project: Project) -> Gtk.Widget:
        row = Adw.ActionRow(title=project.name, subtitle=project.path)
        row.add_prefix(Gtk.Image(icon_name="folder-symbolic"))
        return row

    # Window state

    def _restore_size(self):
        self.set_default_size(
            self.settings.get_int("window-width"), self.settings.get_int("window-height")
        )
        if self.settings.get_boolean("window-maximized"):
            self.maximize()

    def do_close_request(self):
        width, height = self.get_default_size()
        self.settings.set_int("window-width", width)
        self.settings.set_int("window-height", height)
        self.settings.set_boolean("window-maximized", self.is_maximized())
        self.store.close()
        return False

    # Helpers

    def _spawn(self, coro):
        # Keep a strong reference: asyncio only holds tasks weakly.
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _add_window_action(self, name, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
