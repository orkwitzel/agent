# SPDX-License-Identifier: GPL-3.0-or-later
"""The user's projects as a list model the UI binds to."""

from __future__ import annotations

from gi.repository import Gio, GObject

from agent.core.store import Project, Store


class ProjectItem(GObject.Object):
    """One project in a list model. Its properties come from the `Project` it wraps."""

    __gtype_name__ = "AgentProjectItem"

    def __init__(self, project: Project) -> None:
        super().__init__()
        self._project = project

    @GObject.Property(type=str, flags=GObject.ParamFlags.READABLE)
    def name(self) -> str:
        """The project's display name."""
        return self._project.name

    @GObject.Property(type=str, flags=GObject.ParamFlags.READABLE)
    def path(self) -> str:
        """The project's folder."""
        return self._project.path


class ProjectList:
    """The projects in the store, sorted by name, kept in step with it."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._items: Gio.ListStore[ProjectItem] = Gio.ListStore(item_type=ProjectItem)
        self._reload()

    @property
    def items(self) -> Gio.ListModel[ProjectItem]:
        """A list model of `ProjectItem`. Change it through this object, not directly."""
        return self._items

    def add(self, path: str) -> None:
        """Add the folder at `path` as a project, if it isn't one already."""
        self._store.add_project(path)
        self._reload()

    def _reload(self) -> None:
        items = [ProjectItem(project) for project in self._store.projects()]
        self._items.splice(0, self._items.get_n_items(), items)
