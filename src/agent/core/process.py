# SPDX-License-Identifier: GPL-3.0-or-later
"""Running processes with Gio.Subprocess, awaited on the GLib main loop."""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator, Callable, Sequence

from gi.repository import Gio, GLib
from pydantic import JsonValue

from agent.core import claude_stream
from agent.core.events import Event, PermissionRequest, Unrecognized
from agent.core.mainloop import gio_call, is_cancelled

# How much of the end of stderr AgentProcess keeps, to explain an exit.
STDERR_TAIL_BYTES = 8192

# How long close() waits for the rest of stderr once the process has exited.
# A hook or MCP server that inherited the pipe can keep it open for longer.
_STDERR_EOF_TIMEOUT = 1.0

# UTF-8 continuation bytes, left at the start of the tail when the cut
# falls inside a character.
_UTF8_CONTINUATION = bytes(range(0x80, 0xC0))

_logger = logging.getLogger(__name__)


async def run_capture(argv: list[str], *, cwd: str | None = None) -> tuple[int, str]:
    """Run a short command; return (exit status, stdout).

    Cancelling the awaiting task kills the command.
    """
    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
    )
    if cwd:
        launcher.set_cwd(cwd)
    process = launcher.spawnv(argv)
    try:
        _ok, stdout, _stderr = await gio_call(
            process.communicate_utf8_async, process.communicate_utf8_finish, None
        )
        await gio_call(process.wait_async, process.wait_finish)
    except asyncio.CancelledError:
        process.force_exit()
        raise
    status = process.get_exit_status() if process.get_if_exited() else -1
    return status, stdout or ""


class AgentProcess:
    """One long-lived `claude` process for one thread.

    Reads stream-json from stdout and yields neutral events. With
    `auto_allow` (v1 behaviour) every permission request is approved
    in code; the request is still yielded so the UI can show it.
    Control requests we don't handle get an error reply and are yielded
    as `Unrecognized`.

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
    ) -> None:
        self._argv = argv
        self._cwd = cwd
        self._auto_allow = auto_allow
        self._on_stderr = on_stderr
        self._process: Gio.Subprocess | None = None
        self._stdin: Gio.OutputStream | None = None
        self._stdout: Gio.DataInputStream | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail = bytearray()
        self._cancellable = Gio.Cancellable()
        self._ids = itertools.count(1)

    @property
    def running(self) -> bool:
        """Whether the process has been started and hasn't exited."""
        return self._process is not None and self._process.get_identifier() is not None

    @property
    def stderr_tail(self) -> str:
        """The last STDERR_TAIL_BYTES bytes the process wrote to stderr, decoded.

        Once close() has returned it holds what the process wrote before it
        exited, so the UI can show why it exited. A hook or MCP server that
        inherited stderr can still add to it after that.
        """
        tail = self._stderr_tail.lstrip(_UTF8_CONTINUATION)
        return tail.decode("utf-8", errors="replace")

    def start(self) -> None:
        """Spawn the process. Call it once, before anything else."""
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDIN_PIPE
            | Gio.SubprocessFlags.STDOUT_PIPE
            | Gio.SubprocessFlags.STDERR_PIPE
        )
        if self._cwd:
            launcher.set_cwd(self._cwd)
        process = launcher.spawnv(self._argv)
        stdin = process.get_stdin_pipe()
        stdout = process.get_stdout_pipe()
        stderr = process.get_stderr_pipe()
        assert stdin is not None, "spawned with STDIN_PIPE"
        assert stdout is not None, "spawned with STDOUT_PIPE"
        assert stderr is not None, "spawned with STDERR_PIPE"
        self._process = process
        self._stdin = stdin
        # One buffered stream for the process's lifetime, so a later events()
        # call keeps its buffered data, and freeing an iteration doesn't close
        # the pipe (a DataInputStream closes its base stream when disposed).
        self._stdout = Gio.DataInputStream.new(stdout)
        # Always drain stderr: once the pipe buffer fills, the child blocks.
        self._stderr_task = asyncio.ensure_future(self._drain_stderr(stderr))

    def next_request_id(self) -> str:
        """A fresh id for a control request we send."""
        return f"agent-{next(self._ids)}"

    async def send(self, message: dict[str, JsonValue]) -> None:
        """Write one message to stdin.

        Cancelling this mid-write can leave part of a large message on
        stdin, so kill() the process after that.
        """
        assert self._stdin is not None, "process not started"
        data = claude_stream.encode(message)
        await gio_call(
            self._stdin.write_all_async,
            self._stdin.write_all_finish,
            data,
            GLib.PRIORITY_DEFAULT,
            cancellable=self._cancellable,
        )

    async def send_user_message(self, text: str, *, images: Sequence[tuple[str, str]] = ()) -> None:
        """Send a user turn. `images` holds (media_type, base64_data) pairs."""
        await self.send(claude_stream.user_message(text, images=images))

    async def interrupt(self) -> None:
        """Ask claude to stop the running turn."""
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
                    await self._reply(event)
                    yield event
        except GLib.Error as error:
            if not is_cancelled(error):
                raise

    async def close(self) -> int:
        """Close stdin and wait for exit.

        Returns the exit status, or -1 if the process was killed.
        """
        if self._process is None:
            return -1
        try:
            if self._stdin is not None and not self._stdin.is_closed():
                await gio_call(
                    self._stdin.close_async,
                    self._stdin.close_finish,
                    GLib.PRIORITY_DEFAULT,
                    cancellable=self._cancellable,
                )
            await gio_call(
                self._process.wait_async, self._process.wait_finish, cancellable=self._cancellable
            )
        except GLib.Error as error:
            if not is_cancelled(error):
                raise
            return -1
        if self._stderr_task is not None:
            await asyncio.wait([self._stderr_task], timeout=_STDERR_EOF_TIMEOUT)
        return self._process.get_exit_status() if self._process.get_if_exited() else -1

    def kill(self) -> None:
        """Kill the process and cancel everything pending on it.

        After this, events() and close() end at once, and send() raises
        a CANCELLED GLib.Error.
        """
        self._cancellable.cancel()
        if self._process is not None:
            self._process.force_exit()

    async def _reply(self, event: Event) -> None:
        """Answer what claude waits on: auto-allowed permissions, unhandled control requests."""
        if self._auto_allow and isinstance(event, PermissionRequest):
            await self.send(claude_stream.allow_tool(event))
        elif isinstance(event, Unrecognized):
            reply = claude_stream.unsupported_control_request(event.raw)
            if reply is not None:
                await self.send(reply)

    async def _read_line(self, stream: Gio.DataInputStream) -> str | None:
        """Read one line; None at end of stream.

        Uses read_line_finish_utf8: read_line_finish returns b"" both for
        an empty line and at end of stream (PyGObject 3.56.3), so it can't
        tell when to stop. A line that isn't UTF-8 raises GLib.Error.
        """
        line, _length = await gio_call(
            stream.read_line_async,
            stream.read_line_finish_utf8,
            GLib.PRIORITY_DEFAULT,
            cancellable=self._cancellable,
        )
        return line

    async def _drain_stderr(self, pipe: Gio.InputStream) -> None:
        """Read stderr until EOF or kill(), keeping its tail and passing lines to on_stderr.

        Reads raw chunks rather than lines, so stderr that isn't UTF-8 can't
        end the drain.
        """
        partial = bytearray()
        try:
            while data := await self._read_chunk(pipe):
                self._stderr_tail += data
                del self._stderr_tail[:-STDERR_TAIL_BYTES]
                if self._on_stderr is not None:
                    _emit_complete_lines(self._on_stderr, partial, data)
        except GLib.Error as error:
            # Nothing awaits this task, so log rather than raise.
            if not is_cancelled(error):
                _logger.warning("Reading stderr failed: %s", error.message)
        if self._on_stderr is not None and partial:
            _emit_stderr(self._on_stderr, partial)

    async def _read_chunk(self, pipe: Gio.InputStream) -> bytes:
        """Read what's available, up to 4 KiB; b"" at end of stream."""
        chunk = await gio_call(
            pipe.read_bytes_async,
            pipe.read_bytes_finish,
            4096,
            GLib.PRIORITY_DEFAULT,
            cancellable=self._cancellable,
        )
        return chunk.get_data() or b""


def _emit_complete_lines(on_stderr: Callable[[str], None], partial: bytearray, data: bytes) -> None:
    """Pass each line `data` completes to on_stderr; keep the unfinished end in `partial`."""
    # Split only the new data, so a long line isn't copied per chunk.
    *lines, rest = data.split(b"\n")
    for line in lines:
        partial += line
        _emit_stderr(on_stderr, partial)
        partial.clear()
    partial += rest


def _emit_stderr(on_stderr: Callable[[str], None], line: bytearray) -> None:
    # A failing callback must not end the drain, or the child blocks again.
    try:
        on_stderr(line.decode("utf-8", errors="replace"))
    except Exception:
        _logger.exception("on_stderr callback failed")
