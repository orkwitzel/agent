# SPDX-License-Identifier: GPL-3.0-or-later
"""Running processes on the GLib main loop with asyncio.

Uses Gio.Subprocess and PyGObject's asyncio integration, so everything
runs on one thread. Uses GLib/Gio only, never GTK.
"""

from __future__ import annotations

import asyncio
import contextlib
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


def _is_cancelled(error: GLib.Error) -> bool:
    return error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)


async def _gio(start, finish, *args, cancellable: Gio.Cancellable | None = None):
    """Await the Gio async call `start(*args)`; return `finish(result)`.

    The call gets its own Gio.Cancellable, which is cancelled when
    `cancellable` is, or when the awaiting task is cancelled. In that
    case the call is cancelled and waited for before CancelledError is
    re-raised, so it isn't still pending on the stream or process. Its
    outcome is dropped, even if the call finished before the
    cancellation reached it.

    This uses the callback form instead of awaiting PyGObject's Async
    object, because before PyGObject 3.56.3 Async.cancel() rejects the
    argument asyncio passes it, so cancelling the task raises TypeError
    and the await stays pending.
    """
    future = asyncio.get_running_loop().create_future()
    call_cancellable = Gio.Cancellable()

    def done(_source, result):
        try:
            future.set_result(finish(result))
        except Exception as error:
            future.set_exception(error)

    # Gio's Cancellable.connect (not GObject's): runs at once if already
    # cancelled, and then returns 0.
    handler_id = cancellable.connect(call_cancellable.cancel) if cancellable is not None else 0
    try:
        start(*args, call_cancellable, done)
        # asyncio.wait never cancels `future`, and unlike asyncio.shield it
        # doesn't log the CANCELLED error the call ends with.
        try:
            await asyncio.wait([future])
        except asyncio.CancelledError:
            call_cancellable.cancel()
            # A second task.cancel() mustn't cut this wait short: the call
            # would still be pending, and its error never retrieved.
            while not future.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait([future])
            future.exception()  # the outcome is dropped; mark it retrieved
            raise
        return future.result()
    finally:
        if handler_id:
            cancellable.disconnect(handler_id)


async def run_capture(argv: list[str], cwd: str | None = None) -> tuple[int, str]:
    """Run a short command; return (exit status, stdout).

    Cancelling the awaiting task kills the command.
    """
    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
    )
    if cwd:
        launcher.set_cwd(cwd)
    proc = launcher.spawnv(argv)
    try:
        _ok, stdout, _stderr = await _gio(
            proc.communicate_utf8_async, proc.communicate_utf8_finish, None
        )
        await _gio(proc.wait_async, proc.wait_finish)
    except asyncio.CancelledError:
        proc.force_exit()
        raise
    status = proc.get_exit_status() if proc.get_if_exited() else -1
    return status, stdout or ""


class AgentProcess:
    """One long-lived `claude` process for one thread.

    Reads stream-json from stdout and yields neutral events. With
    `auto_allow` (v1 behaviour) every permission request is approved
    in code; the request is still yielded so the UI can show it.

    Every pending call can be cancelled by cancelling the task awaiting
    it, and kill() cancels all of them. Cancelling the task iterating
    events() leaves the process usable, but can drop the events of the
    line being read or yielded at that moment. To stop a turn, use
    interrupt() instead.
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
        self._stdout: Gio.DataInputStream | None = None
        self._cancellable = Gio.Cancellable()
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
        # One buffered stream for the process's lifetime, so a later events()
        # call keeps its buffered data, and freeing an iteration doesn't close
        # the pipe (a DataInputStream closes its base stream when disposed).
        self._stdout = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        if self._on_stderr:
            self._stderr_task = asyncio.ensure_future(self._drain_stderr())

    def next_request_id(self) -> str:
        return f"agent-{next(self._ids)}"

    async def send(self, message: dict) -> None:
        """Write one message to stdin.

        Cancelling this mid-write can leave part of a large message on
        stdin, so kill() the process after that.
        """
        assert self._stdin is not None, "process not started"
        data = claude_stream.encode(message)
        await _gio(
            self._stdin.write_all_async,
            self._stdin.write_all_finish,
            data,
            GLib.PRIORITY_DEFAULT,
            cancellable=self._cancellable,
        )

    async def send_user_message(
        self, text: str, images: list[tuple[str, str]] | None = None
    ) -> None:
        await self.send(claude_stream.user_message(text, images))

    async def interrupt(self) -> None:
        await self.send(claude_stream.interrupt(self.next_request_id()))

    async def events(self) -> AsyncIterator[Event]:
        """Yield events until stdout closes or kill() is called.

        Calling it again after an earlier iteration ended carries on
        where that one stopped reading stdout.
        """
        assert self._stdout is not None, "process not started"
        try:
            while (line := await self._read_line(self._stdout)) is not None:
                for event in claude_stream.parse_line(line):
                    if self._auto_allow and isinstance(event, PermissionRequest):
                        await self.send(claude_stream.allow_tool(event))
                    yield event
        except GLib.Error as error:
            if not _is_cancelled(error):
                raise

    async def close(self) -> int:
        """Close stdin and wait for exit.

        Returns the exit status, or -1 if the process was killed.
        """
        if self._proc is None:
            return -1
        try:
            if self._stdin is not None and not self._stdin.is_closed():
                await _gio(
                    self._stdin.close_async,
                    self._stdin.close_finish,
                    GLib.PRIORITY_DEFAULT,
                    cancellable=self._cancellable,
                )
            await _gio(self._proc.wait_async, self._proc.wait_finish, cancellable=self._cancellable)
        except GLib.Error as error:
            if not _is_cancelled(error):
                raise
            return -1
        return self._proc.get_exit_status() if self._proc.get_if_exited() else -1

    def kill(self) -> None:
        """Kill the process and cancel everything pending on it.

        After this, events() and close() end at once, and send() raises
        a CANCELLED GLib.Error.
        """
        self._cancellable.cancel()
        if self._proc is not None:
            self._proc.force_exit()

    async def _read_line(self, stream: Gio.DataInputStream) -> bytes | None:
        line, _length = await _gio(
            stream.read_line_async,
            stream.read_line_finish,
            GLib.PRIORITY_DEFAULT,
            cancellable=self._cancellable,
        )
        return line

    async def _drain_stderr(self) -> None:
        stream = Gio.DataInputStream.new(self._proc.get_stderr_pipe())
        try:
            while (line := await self._read_line(stream)) is not None:
                self._on_stderr(line.decode("utf-8", errors="replace"))
        except GLib.Error as error:
            if not _is_cancelled(error):
                raise
