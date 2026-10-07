# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end over a real pipe, using the fake claude and the GLib loop."""

import asyncio
import json
import sys

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


def test_turn_with_auto_allow(tmp_path):
    record = tmp_path / "stdin.jsonl"
    argv = [sys.executable, str(FAKE_CLAUDE), str(FIXTURES / "simple_turn.jsonl"), str(record)]

    async def scenario():
        proc = AgentProcess(argv)
        proc.start()
        await proc.send_user_message("what does the README say?")
        seen = []
        async for event in proc.events():
            seen.append(event)
            if isinstance(event, TurnCompleted):
                break
        status = await proc.close()
        return seen, status

    seen, status = run(scenario())
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
