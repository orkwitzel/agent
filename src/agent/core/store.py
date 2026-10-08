# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent's own record of projects, threads and their events (SQLite).

Claude keeps its own session files; we only store the session id so a
thread can be resumed with `claude --resume`.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from agent.core import APP_ID
from agent.core import events as ev


def database_path(data_dir: str | Path) -> Path:
    """Return `<data_dir>/<app id>/agent.db`, creating the folder if needed.

    The caller passes `GLib.get_user_data_dir()`; it is a parameter because
    GLib caches that value, so tests can't redirect it with `XDG_DATA_HOME`.
    """
    directory = Path(data_dir) / APP_ID
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / "agent.db"


_MIGRATIONS = [
    """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE threads (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'claude',
        provider_session_id TEXT,
        model TEXT,
        working_dir TEXT NOT NULL,
        branch TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX events_by_thread ON events(thread_id, id);
    """,
]

_EVENT_TYPES: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        ev.SessionStarted,
        ev.AssistantText,
        ev.AssistantThinking,
        ev.ToolCall,
        ev.ToolResult,
        ev.PermissionRequest,
        ev.TurnCompleted,
        ev.ControlReply,
        ev.Unrecognized,
    )
}


@dataclass(frozen=True)
class Project:
    id: int
    path: str
    name: str


@dataclass(frozen=True)
class Thread:
    id: int
    project_id: int
    title: str
    provider: str
    provider_session_id: str | None
    model: str | None
    working_dir: str
    branch: str | None


class Store:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path))
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
        for i, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            with self._db:
                self._db.executescript(script)
                self._db.execute(f"PRAGMA user_version = {i}")

    # Projects

    def add_project(self, path: str, name: str | None = None) -> Project:
        name = name or Path(path).name or path
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO projects (path, name, created_at) VALUES (?, ?, ?)",
                (path, name, time.time()),
            )
        row = self._db.execute(
            "SELECT id, path, name FROM projects WHERE path = ?", (path,)
        ).fetchone()
        return Project(*row)

    def projects(self) -> list[Project]:
        rows = self._db.execute("SELECT id, path, name FROM projects ORDER BY name COLLATE NOCASE")
        return [Project(*row) for row in rows]

    def remove_project(self, project_id: int) -> None:
        with self._db:
            self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # Threads

    _THREAD_COLUMNS = (
        "id, project_id, title, provider, provider_session_id, model, working_dir, branch"
    )

    def create_thread(self, project: Project, title: str, model: str | None = None) -> Thread:
        now = time.time()
        with self._db:
            cur = self._db.execute(
                "INSERT INTO threads"
                " (project_id, title, model, working_dir, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (project.id, title, model, project.path, now, now),
            )
        return self.thread(cur.lastrowid)

    def thread(self, thread_id: int) -> Thread:
        row = self._db.execute(
            f"SELECT {self._THREAD_COLUMNS} FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            raise KeyError(thread_id)
        return Thread(*row)

    def threads(self, project_id: int) -> list[Thread]:
        rows = self._db.execute(
            f"SELECT {self._THREAD_COLUMNS} FROM threads WHERE project_id = ?"
            " ORDER BY updated_at DESC",
            (project_id,),
        )
        return [Thread(*row) for row in rows]

    def rename_thread(self, thread_id: int, title: str) -> None:
        self._update_thread(thread_id, title=title)

    def set_provider_session(self, thread_id: int, session_id: str) -> None:
        self._update_thread(thread_id, provider_session_id=session_id)

    def set_thread_model(self, thread_id: int, model: str | None) -> None:
        self._update_thread(thread_id, model=model)

    def delete_thread(self, thread_id: int) -> None:
        with self._db:
            self._db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))

    def _update_thread(self, thread_id: int, **fields: object) -> None:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._db:
            self._db.execute(
                f"UPDATE threads SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), time.time(), thread_id),
            )

    # Events

    def append_event(self, thread_id: int, event: ev.Event) -> None:
        payload = json.dumps(dataclasses.asdict(event))
        now = time.time()
        with self._db:
            self._db.execute(
                "INSERT INTO events (thread_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, type(event).__name__, payload, now),
            )
            self._db.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))

    def events(self, thread_id: int) -> list[ev.Event]:
        rows = self._db.execute(
            "SELECT kind, payload FROM events WHERE thread_id = ? ORDER BY id", (thread_id,)
        )
        return [_decode_event(kind, payload) for kind, payload in rows]


def _decode_event(kind: str, payload: str) -> ev.Event:
    data = json.loads(payload)
    cls = _EVENT_TYPES.get(kind)
    if cls is None:
        return ev.Unrecognized({"kind": kind, **data})
    if cls is ev.TurnCompleted:
        data["usage"] = ev.TokenUsage(**data["usage"])
    return cls(**data)
