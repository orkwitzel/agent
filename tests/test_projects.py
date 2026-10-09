# SPDX-License-Identifier: GPL-3.0-or-later
from agent.core.projects import ProjectList
from agent.core.store import Store


def names(projects):
    return [item.props.name for item in projects.items]


def test_lists_existing_projects_by_name(tmp_path):
    store = Store(tmp_path / "agent.db")
    store.add_project("/code/zeta")
    store.add_project("/code/Alpha")

    projects = ProjectList(store)
    assert names(projects) == ["Alpha", "zeta"]
    assert [item.props.path for item in projects.items] == ["/code/Alpha", "/code/zeta"]


def test_add_updates_the_list(tmp_path):
    projects = ProjectList(Store(tmp_path / "agent.db"))
    changes = []
    projects.items.connect("items-changed", lambda *args: changes.append(args[1:]))

    projects.add("/code/app")
    projects.add("/code/app")  # already a project
    assert names(projects) == ["app"]
    assert projects.items.props.n_items == 1
    assert changes[0] == (0, 0, 1)
