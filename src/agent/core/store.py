# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent's own record of projects, threads and their events (SQLite).

Claude keeps its own session files; we only store the session id so a
thread can be resumed with `claude --resume`.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import get_args

from pydantic import JsonValue, TypeAdapter

from agent.core import APP_ID
from agent.core.events import Event, Unrecognized
from agent.core.model import Model


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

# Events are stored by class name, so a stored event decodes to its class.
_EVENT_CLASSES: tuple[type[Event], ...] = get_args(Event)
_EVENT_TYPES = {cls.__name__: cls for cls in _EVENT_CLASSES}

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class Project(Model):
    """A folder the user works in."""

    id: int
    path: str
    name: str


class Thread(Model):
    """One conversation with an agent, in a project's folder."""

    id: int
    project_id: int
    title: str
    provider: str
    provider_session_id: str | None
    model: str | None
    working_dir: str
    branch: str | None


# Columns are named like the fields of the model they hold.
_PROJECT_COLUMNS = ", ".join(Project.model_fields)
_THREAD_COLUMNS = ", ".join(Thread.model_fields)


class Store:
    """Agent's SQLite database, migrated to the latest schema on open."""

    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        """Close the database. The store can't be used afterwards."""
        self._db.close()

    def _migrate(self) -> None:
        row: tuple[int] = self._db.execute("PRAGMA user_version").fetchone()
        (version,) = row
        for target, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            with self._db:
                self._db.executescript(script)
                self._db.execute(f"PRAGMA user_version = {target}")

    # Projects

    def add_project(self, path: str, *, name: str | None = None) -> Project:
        """Add the folder at `path`, or return it if it's already a project.

        `name` defaults to the folder's name.
        """
        name = name or Path(path).name or path
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO projects (path, name, created_at) VALUES (?, ?, ?)",
                (path, name, time.time()),
            )
        row: tuple[object, ...] = self._db.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE path = ?", (path,)
        ).fetchone()
        return _from_row(Project, row)

    def projects(self) -> list[Project]:
        """All projects, sorted by name."""
        rows: list[tuple[object, ...]] = self._db.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [_from_row(Project, row) for row in rows]

    def remove_project(self, project_id: int) -> None:
        """Remove a project with its threads and their events."""
        with self._db:
            self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # Threads

    def create_thread(self, project: Project, title: str, *, model: str | None = None) -> Thread:
        """Start a thread in `project`'s folder. `model` None means the agent's default."""
        now = time.time()
        with self._db:
            row: tuple[object, ...] = self._db.execute(
                "INSERT INTO threads"
                " (project_id, title, model, working_dir, created_at, updated_at)"
                f" VALUES (?, ?, ?, ?, ?, ?) RETURNING {_THREAD_COLUMNS}",
                (project.id, title, model, project.path, now, now),
            ).fetchone()
        return _from_row(Thread, row)

    def thread(self, thread_id: int) -> Thread:
        """The thread with this id. Raises KeyError if there is none."""
        row: tuple[object, ...] | None = self._db.execute(
            f"SELECT {_THREAD_COLUMNS} FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            raise KeyError(thread_id)
        return _from_row(Thread, row)

    def threads(self, project_id: int) -> list[Thread]:
        """A project's threads, most recently active first."""
        rows: list[tuple[object, ...]] = self._db.execute(
            f"SELECT {_THREAD_COLUMNS} FROM threads WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
        return [_from_row(Thread, row) for row in rows]

    def rename_thread(self, thread_id: int, title: str) -> None:
        """Change a thread's title."""
        self._update_thread(thread_id, title=title)

    def set_provider_session(self, thread_id: int, session_id: str) -> None:
        """Remember the agent's session id, so the thread can be resumed."""
        self._update_thread(thread_id, provider_session_id=session_id)

    def set_thread_model(self, thread_id: int, model: str | None) -> None:
        """Change a thread's model. None means the agent's default."""
        self._update_thread(thread_id, model=model)

    def delete_thread(self, thread_id: int) -> None:
        """Delete a thread and its events."""
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

    def append_event(self, thread_id: int, event: Event) -> None:
        """Record an event at the end of a thread."""
        now = time.time()
        with self._db:
            self._db.execute(
                "INSERT INTO events (thread_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, type(event).__name__, event.model_dump_json(), now),
            )
            self._db.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))

    def events(self, thread_id: int) -> list[Event]:
        """A thread's events, oldest first."""
        rows: list[tuple[str, str]] = self._db.execute(
            "SELECT kind, payload FROM events WHERE thread_id = ? ORDER BY id", (thread_id,)
        ).fetchall()
        return [_decode_event(kind, payload) for kind, payload in rows]


def _from_row[M: Model](model: type[M], row: tuple[object, ...]) -> M:
    return model.model_validate(dict(zip(model.model_fields, row, strict=True)))


def _decode_event(kind: str, payload: str) -> Event:
    cls = _EVENT_TYPES.get(kind)
    if cls is None:
        return Unrecognized(raw={"kind": kind, "payload": _JSON.validate_json(payload)})
    return cls.model_validate_json(payload)
