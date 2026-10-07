#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for `claude` that replays a fixture.

Usage: fake_claude.py FIXTURE.jsonl [RECORD.jsonl]

For each user message read on stdin, writes the fixture's lines to
stdout. When it writes a control_request (e.g. can_use_tool) it waits for
the matching control_response, like the real CLI. Everything received on
stdin is appended to RECORD.jsonl so tests can assert on it.
"""

import json
import sys


def main() -> int:
    fixture = [line for line in open(sys.argv[1]) if line.strip()]
    record = open(sys.argv[2], "a") if len(sys.argv) > 2 else None

    def read_message():
        line = sys.stdin.readline()
        if not line:
            return None
        if record:
            record.write(line)
            record.flush()
        return json.loads(line)

    while (msg := read_message()) is not None:
        if msg.get("type") != "user":
            continue
        for line in fixture:
            sys.stdout.write(line)
            sys.stdout.flush()
            out = json.loads(line)
            if out.get("type") == "control_request":
                while (reply := read_message()) is not None:
                    response = reply.get("response") or {}
                    if (
                        reply.get("type") == "control_response"
                        and response.get("request_id") == out["request_id"]
                    ):
                        break
                else:
                    return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
