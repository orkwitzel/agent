# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3

from agent.core.events import (
    AssistantText,
    SessionStarted,
    TokenUsage,
    ToolCall,
    TurnCompleted,
    Unrecognized,
)
from agent.core.store import Store, database_path


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
        SessionStarted(session_id="sess", tools=("Read", "Bash")),
        AssistantText(text="hi"),
        ToolCall(tool_call_id="toolu_1", name="Bash", input={"command": "ls"}),
        TurnCompleted(
            session_id="sess",
            is_error=False,
            duration_ms=10,
            usage=TokenUsage(
                input_tokens=1, output_tokens=2, cache_read_tokens=3, cache_creation_tokens=4
            ),
            result="done",
        ),
    ]
    for event in events:
        store.append_event(thread.id, event)
    assert store.events(thread.id) == events


def test_event_of_unknown_kind_is_kept(tmp_path):
    path = tmp_path / "agent.db"
    store = Store(path)
    thread = store.create_thread(store.add_project("/p"), "t")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO events (thread_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (thread.id, "RemovedEvent", '{"text": "old"}', 0.0),
        )
    assert store.events(thread.id) == [
        Unrecognized(raw={"kind": "RemovedEvent", "payload": {"text": "old"}})
    ]


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
    store.append_event(thread.id, AssistantText(text="hi"))
    store.remove_project(project.id)
    assert store.projects() == []
    assert store.events(thread.id) == []


def test_database_path_is_named_after_app_id(tmp_path):
    path = database_path(tmp_path)
    assert path == tmp_path / "io.github.orkwitzel.Agent" / "agent.db"
    assert path.parent.is_dir()
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert database_path(tmp_path) == path  # folder already exists
    Store(path).close()
    assert path.is_file()
