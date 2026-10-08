# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end over a real pipe, using the fake claude and the GLib loop."""

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

from agent.core.events import PermissionRequest, TurnCompleted
from agent.core.process import AgentProcess, install_glib_event_loop, run_capture
from conftest import FAKE_CLAUDE, FIXTURES


def run(coro):
    install_glib_event_loop()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def collect(events):
    return [event async for event in events]


# How long a test waits on a process. A hang fails the test with
# TimeoutError instead of blocking the run.
TIMEOUT = 10


async def turn(proc):
    """Iterate events() up to and including TurnCompleted, within TIMEOUT."""

    async def read():
        seen = []
        async with contextlib.aclosing(proc.events()) as events:
            async for event in events:
                seen.append(event)
                if isinstance(event, TurnCompleted):
                    break
        return seen

    return await asyncio.wait_for(read(), TIMEOUT)


async def one_turn(proc):
    """Start `proc`, send one message, read the turn and close.

    Returns (events, exit status). Each step is bounded by TIMEOUT, and
    the process is killed on the way out, whatever happened.
    """
    proc.start()
    try:
        await proc.send_user_message("hello")
        seen = await turn(proc)
        return seen, await asyncio.wait_for(proc.close(), TIMEOUT)
    finally:
        proc.kill()


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
    assert any(isinstance(e, PermissionRequest) for e in seen)
    assert isinstance(seen[-1], TurnCompleted)

    sent = [json.loads(line) for line in record.read_text().splitlines()]
    assert sent[0]["type"] == "user"
    assert sent[1]["response"]["request_id"] == "cli-req-1"
    assert sent[1]["response"]["response"]["behavior"] == "allow"


def test_run_capture():
    status, out = run(run_capture([sys.executable, "-c", "print('hi')"]))
    assert (status, out) == (0, "hi\n")


def test_events_task_can_be_cancelled():
    argv = [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")]

    async def scenario():
        proc = AgentProcess(argv)
        proc.start()
        try:
            reader = asyncio.ensure_future(collect(proc.events()))
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
            await proc.send_user_message("hello")
            seen = await turn(proc)
            status = await asyncio.wait_for(proc.close(), TIMEOUT)
            return cancelled, seen, status
        finally:
            proc.kill()

    cancelled, seen, status = run(scenario())
    assert cancelled
    assert isinstance(seen[-1], TurnCompleted)
    assert status == 0


def test_cancelling_twice_still_waits_for_the_read():
    argv = [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl")]
    errors = []

    async def scenario():
        asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: errors.append(ctx))
        proc = AgentProcess(argv)
        proc.start()
        try:
            reader = asyncio.ensure_future(collect(proc.events()))
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
            await proc.send_user_message("hello")
            await turn(proc)
            return cancelled
        finally:
            proc.kill()

    assert run(scenario())
    gc.collect()
    assert errors == []


def test_kill_ends_events_while_stdout_stays_open(tmp_path):
    # A grandchild keeps stdout open after the child is killed, like claude
    # behind flatpak-spawn or systemd-run. Only cancelling the read ends it.
    pidfile = tmp_path / "grandchild.pid"
    argv = ["sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(pidfile)]

    async def scenario():
        proc = AgentProcess(argv)
        proc.start()
        reader = asyncio.ensure_future(collect(proc.events()))
        await asyncio.sleep(0.2)
        proc.kill()
        await asyncio.wait([reader], timeout=1)
        if not reader.done():
            reader.cancel()
            return None, None
        return reader.result(), await asyncio.wait_for(proc.close(), 1)

    try:
        seen, status = run(scenario())
    finally:
        with contextlib.suppress(OSError):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
    assert seen == []
    assert status == -1


def test_close_can_time_out():
    async def scenario():
        proc = AgentProcess(["sleep", "30"])  # ignores stdin closing
        proc.start()
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(proc.close(), 1)
            return time.monotonic() - started
        finally:
            proc.kill()

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
        while alive(pid) and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        return elapsed, alive(pid)

    elapsed, still_alive = run(scenario())
    assert 0.9 < elapsed < 2
    assert not still_alive
