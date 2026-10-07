# SPDX-License-Identifier: GPL-3.0-or-later
"""Running processes on the GLib main loop with asyncio.

Uses Gio.Subprocess and PyGObject's asyncio integration, so everything
runs on one thread. Uses GLib/Gio only, never GTK.
"""

from __future__ import annotations

import asyncio
import itertools
import warnings
from collections.abc import AsyncIterator, Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from agent.core import claude_stream  # noqa: E402
from agent.core.events import Event, PermissionRequest  # noqa: E402


def install_glib_event_loop() -> None:
    """Make asyncio run on the GLib main loop.

    PyGObject >= 3.55.3 can do this without a policy, but Debian 13 ships
    3.50, which still needs GLibEventLoopPolicy. Python 3.14 deprecates
    policies, hence the warning filter.
    """
    from gi.events import GLibEventLoopPolicy

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(GLibEventLoopPolicy())


async def run_capture(argv: list[str], cwd: str | None = None) -> tuple[int, str]:
    """Run a short command; return (exit status, stdout)."""
    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
    )
    if cwd:
        launcher.set_cwd(cwd)
    proc = launcher.spawnv(argv)
    _ok, stdout, _stderr = await proc.communicate_utf8_async(None, None)
    await proc.wait_async(None)
    status = proc.get_exit_status() if proc.get_if_exited() else -1
    return status, stdout or ""


class AgentProcess:
    """One long-lived `claude` process for one thread.

    Reads stream-json from stdout and yields neutral events. With
    `auto_allow` (v1 behaviour) every permission request is approved
    in code; the request is still yielded so the UI can show it.
    """

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        auto_allow: bool = True,
        on_stderr: Callable[[str], None] | None = None,
    ):
        self._argv = argv
        self._cwd = cwd
        self._auto_allow = auto_allow
        self._on_stderr = on_stderr
        self._proc: Gio.Subprocess | None = None
        self._stdin: Gio.OutputStream | None = None
        self._ids = itertools.count(1)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.get_identifier() is not None

    def start(self) -> None:
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDIN_PIPE
            | Gio.SubprocessFlags.STDOUT_PIPE
            | Gio.SubprocessFlags.STDERR_PIPE
        )
        if self._cwd:
            launcher.set_cwd(self._cwd)
        self._proc = launcher.spawnv(self._argv)
        self._stdin = self._proc.get_stdin_pipe()
        if self._on_stderr:
            self._stderr_task = asyncio.ensure_future(self._drain_stderr())

    def next_request_id(self) -> str:
        return f"agent-{next(self._ids)}"

    async def send(self, message: dict) -> None:
        assert self._stdin is not None, "process not started"
        data = claude_stream.encode(message)
        await self._stdin.write_all_async(data, GLib.PRIORITY_DEFAULT, None)

    async def send_user_message(
        self, text: str, images: list[tuple[str, str]] | None = None
    ) -> None:
        await self.send(claude_stream.user_message(text, images))

    async def interrupt(self) -> None:
        await self.send(claude_stream.interrupt(self.next_request_id()))

    async def events(self) -> AsyncIterator[Event]:
        assert self._proc is not None, "process not started"
        stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        while True:
            line, _length = await stream.read_line_async(GLib.PRIORITY_DEFAULT, None)
            if line is None:
                return
            for event in claude_stream.parse_line(line):
                if self._auto_allow and isinstance(event, PermissionRequest):
                    await self.send(claude_stream.allow_tool(event))
                yield event

    async def close(self) -> int:
        """Close stdin and wait for exit. Returns the exit status."""
        if self._proc is None:
            return -1
        if self._stdin is not None and not self._stdin.is_closed():
            await self._stdin.close_async(GLib.PRIORITY_DEFAULT, None)
        await self._proc.wait_async(None)
        return self._proc.get_exit_status() if self._proc.get_if_exited() else -1

    def kill(self) -> None:
        if self._proc is not None:
            self._proc.force_exit()

    async def _drain_stderr(self) -> None:
        stream = Gio.DataInputStream.new(self._proc.get_stderr_pipe())
        while True:
            line, _length = await stream.read_line_async(GLib.PRIORITY_DEFAULT, None)
            if line is None:
                return
            self._on_stderr(line.decode("utf-8", errors="replace"))
