# SPDX-License-Identifier: GPL-3.0-or-later
from agent.core.events import AssistantText, TokenUsage, ToolCall, TurnCompleted
from agent.core.store import Store


def test_projects_and_threads(tmp_path):
    store = Store(tmp_path / "agent.db")
    project = store.add_project("/home/me/code/app")
    assert project.name == "app"
    assert store.add_project("/home/me/code/app") == project  # idempotent

    thread = store.create_thread(project, "Fix login", model="opus")
    assert thread.working_dir == "/home/me/code/app"
    assert thread.provider == "claude"

    store.set_provider_session(thread.id, "sess-1")
    store.rename_thread(thread.id, "Fix login redirect")
    thread = store.thread(thread.id)
    assert thread.provider_session_id == "sess-1"
    assert thread.title == "Fix login redirect"
    assert store.threads(project.id) == [thread]


def test_events_round_trip(tmp_path):
    store = Store(tmp_path / "agent.db")
    thread = store.create_thread(store.add_project("/p"), "t")
    events = [
        AssistantText("hi"),
        ToolCall("toolu_1", "Bash", {"command": "ls"}),
        TurnCompleted("sess", False, 10, TokenUsage(1, 2, 3, 4), "done"),
    ]
    for event in events:
        store.append_event(thread.id, event)
    assert store.events(thread.id) == events


def test_reopen_keeps_data(tmp_path):
    path = tmp_path / "agent.db"
    store = Store(path)
    store.add_project("/p")
    store.close()
    assert [p.path for p in Store(path).projects()] == ["/p"]


def test_removing_project_removes_threads(tmp_path):
    store = Store(tmp_path / "agent.db")
    project = store.add_project("/p")
    thread = store.create_thread(project, "t")
    store.append_event(thread.id, AssistantText("hi"))
    store.remove_project(project.id)
    assert store.projects() == []
    assert store.events(thread.id) == []
