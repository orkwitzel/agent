# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end over a real pipe, using the fake claude and the GLib loop."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from agent.core.events import PermissionRequest, TurnCompleted, Unrecognized
from agent.core.process import STDERR_TAIL_BYTES, AgentProcess, run_capture
from support import FAKE_CLAUDE, FIXTURES, run


async def collect(events):
    return [event async for event in events]


# How long a test waits on a process. A hang fails the test with
# TimeoutError instead of blocking the run.
TIMEOUT = 10


async def turn(process):
    """Iterate events() up to and including TurnCompleted, within TIMEOUT."""

    async def read():
        seen = []
        async with contextlib.aclosing(process.events()) as events:
            async for event in events:
                seen.append(event)
                if isinstance(event, TurnCompleted):
                    break
        return seen

    return await asyncio.wait_for(read(), TIMEOUT)


async def one_turn(process):
    """Start `process`, send one message, read the turn and close.

    Returns (events, exit status). Each step is bounded by TIMEOUT, and
    the process is killed on the way out, whatever happened.
    """
    process.start()
    try:
        await process.send_user_message("hello")
        seen = await turn(process)
        return seen, await asyncio.wait_for(process.close(), TIMEOUT)
    finally:
        process.kill()


def alive(pid):
    """False once `pid` has exited, even if it hasn't been reaped yet."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):  # reaped
        return False
    return stat.rpartition(")")[2].split()[0] != "Z"


def test_turn_with_auto_allow(tmp_path):
    record = tmp_path / "stdin.jsonl"
    argv = [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl"), str(record)]

    seen, status = run(one_turn(AgentProcess(argv)))
    assert status == 0
    assert any(isinstance(event, PermissionRequest) for event in seen)
    assert isinstance(seen[-1], TurnCompleted)

    sent = [json.loads(line) for line in record.read_text().splitlines()]
    assert sent[0]["type"] == "user"
    assert sent[1]["response"]["request_id"] == "cli-req-1"
    assert sent[1]["response"]["response"]["behavior"] == "allow"


def test_unknown_control_request_gets_error_reply(tmp_path):
    # The fake waits for our reply, so without one the turn times out.
    record = tmp_path / "stdin.jsonl"
    fixture = FIXTURES / "unknown_control_request.jsonl"
    argv = [sys.executable, str(FAKE_CLAUDE), str(fixture), str(record)]

    seen, status = run(one_turn(AgentProcess(argv)))
    assert status == 0
    assert isinstance(seen[-1], TurnCompleted)
    assert any(
        isinstance(event, Unrecognized) and event.raw.get("type") == "control_request"
        for event in seen
    )

    sent = [json.loads(line) for line in record.read_text().splitlines()]
    assert sent[1] == {
        "type": "control_response",
        "response": {
            "subtype": "error",
            "request_id": "cli-req-1",
            "error": "Agent does not support future_subtype",
        },
    }


STDERR_BYTES = 200_000  # well past the 64 KiB pipe buffer


def test_large_stderr_without_callback(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_STDERR_BYTES", str(STDERR_BYTES))
    process = AgentProcess([sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")])

    seen, status = run(one_turn(process))
    assert seen
    assert isinstance(seen[-1], TurnCompleted)
    assert status == 0
    assert len(process.stderr_tail.encode()) == STDERR_TAIL_BYTES


def test_stderr_tail_after_exit(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_STDERR_BYTES", str(STDERR_BYTES))
    lines = []
    process = AgentProcess(
        [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")],
        on_stderr=lines.append,
    )

    _seen, status = run(one_turn(process))
    assert status == 0
    written = "".join(f"{line}\n" for line in lines)
    assert len(written) >= STDERR_BYTES
    assert process.stderr_tail == written[-STDERR_TAIL_BYTES:]


def test_failing_stderr_callback_keeps_draining(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_STDERR_BYTES", str(STDERR_BYTES))
    lines = []

    def on_stderr(line):
        lines.append(line)
        if len(lines) == 1:
            raise ValueError("bug in the callback")

    process = AgentProcess(
        [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")],
        on_stderr=on_stderr,
    )

    seen, status = run(one_turn(process))
    assert isinstance(seen[-1], TurnCompleted)
    assert status == 0
    assert len(lines) > 1


def test_stderr_tail_after_crash():
    # 3-byte characters, so the cut at STDERR_TAIL_BYTES splits one.
    script = (
        "import sys\n"
        f"sys.stderr.buffer.write('\\u20ac'.encode() * {STDERR_TAIL_BYTES})\n"
        "sys.exit(3)\n"
    )
    process = AgentProcess([sys.executable, "-c", script])

    async def scenario():
        process.start()
        try:
            return await asyncio.wait_for(process.close(), TIMEOUT)
        finally:
            process.kill()

    assert run(scenario()) == 3
    assert process.stderr_tail == "\u20ac" * (STDERR_TAIL_BYTES // 3)


def test_run_capture():
    status, out = run(run_capture([sys.executable, "-c", "print('hi')"]))
    assert (status, out) == (0, "hi\n")


def test_events_task_can_be_cancelled():
    argv = [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")]

    async def scenario():
        process = AgentProcess(argv)
        process.start()
        try:
            reader = asyncio.ensure_future(collect(process.events()))
            await asyncio.sleep(0.2)  # idle: no user message, so no output
            reader.cancel()
            await asyncio.wait([reader], timeout=1)
            if not reader.done():
                return False, None, None
            cancelled = reader.cancelled()
            # Free the cancelled iteration, and its stream with it.
            del reader
            gc.collect()
            # Only that read was cancelled; the process is still usable.
            await process.send_user_message("hello")
            seen = await turn(process)
            status = await asyncio.wait_for(process.close(), TIMEOUT)
            return cancelled, seen, status
        finally:
            process.kill()

    cancelled, seen, status = run(scenario())
    assert cancelled
    assert isinstance(seen[-1], TurnCompleted)
    assert status == 0


def test_cancelling_twice_still_waits_for_the_read():
    argv = [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")]
    errors = []

    async def scenario():
        asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: errors.append(ctx))
        process = AgentProcess(argv)
        process.start()
        try:
            reader = asyncio.ensure_future(collect(process.events()))
            await asyncio.sleep(0.2)
            reader.cancel()
            await asyncio.sleep(0)  # the reader is now waiting for the read to end
            reader.cancel()
            await asyncio.wait([reader], timeout=1)
            if not reader.done():
                return False
            cancelled = reader.cancelled()
            del reader
            gc.collect()
            # The cancelled read has ended, so a new one can start on the stream.
            await process.send_user_message("hello")
            await turn(process)
            return cancelled
        finally:
            process.kill()

    assert run(scenario())
    gc.collect()
    assert errors == []


def test_kill_ends_events_while_stdout_stays_open(tmp_path):
    # A grandchild keeps stdout open after the child is killed, like claude
    # behind flatpak-spawn or systemd-run. Only cancelling the read ends it.
    pidfile = tmp_path / "grandchild.pid"
    argv = ["sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(pidfile)]

    async def scenario():
        process = AgentProcess(argv)
        process.start()
        reader = asyncio.ensure_future(collect(process.events()))
        await asyncio.sleep(0.2)
        process.kill()
        await asyncio.wait([reader], timeout=1)
        if not reader.done():
            reader.cancel()
            return None, None
        return reader.result(), await asyncio.wait_for(process.close(), 1)

    try:
        seen, status = run(scenario())
    finally:
        with contextlib.suppress(OSError):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
    assert seen == []
    assert status == -1


def test_close_can_time_out():
    async def scenario():
        process = AgentProcess(["sleep", "30"])  # ignores stdin closing
        process.start()
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(process.close(), 1)
            return time.monotonic() - started
        finally:
            process.kill()

    assert run(scenario()) < 2


def test_run_capture_timeout_kills_child(tmp_path):
    pidfile = tmp_path / "child.pid"
    argv = ["sh", "-c", 'echo $$ > "$0"; exec sleep 30', str(pidfile)]

    async def scenario():
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(run_capture(argv), 1)
        elapsed = time.monotonic() - started
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 1
        # Polls another process: there is no event to wait on.
        while alive(pid) and time.monotonic() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        return elapsed, alive(pid)

    elapsed, still_alive = run(scenario())
    assert 0.9 < elapsed < 2
    assert not still_alive


def test_events_end_at_end_of_stream():
    # A blank line doesn't end the stream; closing stdout does, even
    # before TurnCompleted.
    argv = ["sh", "-c", 'printf \'\\n{"type":"mystery"}\\n\\n\'']

    async def scenario():
        process = AgentProcess(argv)
        process.start()
        try:
            return await asyncio.wait_for(collect(process.events()), TIMEOUT)
        finally:
            process.kill()

    seen = run(scenario())
    assert [event.raw for event in seen] == [{"type": "mystery"}]  # Unrecognized
