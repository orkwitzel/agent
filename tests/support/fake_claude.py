#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for `claude` that replays a fixture.

Usage: fake_claude.py FIXTURE.jsonl [RECORD.jsonl]

For each user message read on stdin, writes the fixture's lines to
stdout. When it writes a control_request (e.g. can_use_tool) it waits for
the matching control_response, like the real CLI. Everything received on
stdin is appended to RECORD.jsonl so tests can assert on it.

If FAKE_CLAUDE_STDERR_BYTES is set, each turn first writes at least that
many bytes to stderr, as numbered lines.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    fixture = [
        line for line in Path(sys.argv[1]).read_text().splitlines(keepends=True) if line.strip()
    ]
    record = Path(sys.argv[2]).open("a") if len(sys.argv) > 2 else None
    stderr_bytes = int(os.environ.get("FAKE_CLAUDE_STDERR_BYTES", "0"))
    while (message := read_message(record)) is not None:
        if message.get("type") != "user":
            continue
        if stderr_bytes:
            write_stderr(stderr_bytes)
        if not replay(fixture, record):
            return 1
    return 0


def replay(fixture, record):
    """Write the fixture's lines, waiting for our reply after each control request.

    False if stdin closed while waiting.
    """
    for line in fixture:
        sys.stdout.write(line)
        sys.stdout.flush()
        out = json.loads(line)
        if out.get("type") == "control_request" and not wait_for_reply(out["request_id"], record):
            return False
    return True


def wait_for_reply(request_id, record):
    while (reply := read_message(record)) is not None:
        response = reply.get("response") or {}
        if reply.get("type") == "control_response" and response.get("request_id") == request_id:
            return True
    return False


def read_message(record):
    line = sys.stdin.readline()
    if not line:
        return None
    if record:
        record.write(line)
        record.flush()
    return json.loads(line)


def write_stderr(size):
    written = 0
    number = 0
    while written < size:
        line = f"fake_claude stderr line {number}\n"
        sys.stderr.write(line)
        written += len(line)
        number += 1
    sys.stderr.flush()


if __name__ == "__main__":
    sys.exit(main())
