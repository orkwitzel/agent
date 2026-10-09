# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json

from agent.core import claude_stream
from agent.core.events import (
    AssistantText,
    AssistantThinking,
    ControlReply,
    PermissionRequest,
    SessionStarted,
    ToolCall,
    ToolResult,
    TurnCompleted,
    Unrecognized,
)
from support import FIXTURES


def parse_fixture(name):
    events = []
    for line in (FIXTURES / name).read_text().splitlines():
        events.extend(claude_stream.parse_line(line))
    return events


def test_simple_turn_event_sequence():
    kinds = [type(event) for event in parse_fixture("simple_turn.jsonl")]
    assert kinds == [
        SessionStarted,
        AssistantText,
        ToolCall,
        PermissionRequest,
        ToolResult,
        AssistantThinking,
        AssistantText,
        TurnCompleted,
    ]


def test_session_started_fields():
    started = parse_fixture("simple_turn.jsonl")[0]
    assert started.session_id == "11111111-2222-3333-4444-555555555555"
    assert started.model == "claude-sonnet-5-5"
    assert started.slash_commands == ("compact", "review")
    assert started.agent_version == "2.1.293"


def test_tool_result_flattens_text_blocks():
    result = parse_fixture("simple_turn.jsonl")[4]
    assert result == ToolResult(tool_call_id="toolu_01", content="# Project\nHello", is_error=False)


def test_turn_completed_usage():
    done = parse_fixture("simple_turn.jsonl")[-1]
    assert not done.is_error
    assert done.usage.input_tokens == 1200
    assert done.usage.output_tokens == 45
    assert done.usage.cache_read_tokens == 800


def test_blank_and_garbage_lines():
    assert claude_stream.parse_line("   \n") == []
    [event] = claude_stream.parse_line("not json")
    assert isinstance(event, Unrecognized)


def test_unknown_message_type_is_kept():
    [event] = claude_stream.parse_line('{"type":"stream_event","x":1}')
    assert event == Unrecognized(raw={"type": "stream_event", "x": 1})


def test_known_message_with_missing_fields_is_kept():
    # Never filled in with defaults: a protocol change must stay visible.
    message = {"type": "result", "subtype": "success", "is_error": False}
    assert claude_stream.parse_line(json.dumps(message)) == [Unrecognized(raw=message)]


def test_unknown_content_block_is_kept():
    block = {"type": "server_tool_use", "id": "srvtoolu_1"}
    message = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}, block]}}
    assert claude_stream.parse_line(json.dumps(message)) == [
        AssistantText(text="Hi"),
        Unrecognized(raw=block),
    ]


def test_control_reply():
    line = json.dumps(
        {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": "agent-1",
                "response": {"percentage": 12},
            },
        }
    )
    assert claude_stream.parse_line(line) == [
        ControlReply(request_id="agent-1", ok=True, payload={"percentage": 12})
    ]


def test_unknown_control_request_is_kept():
    events = parse_fixture("unknown_control_request.jsonl")
    assert [type(event) for event in events] == [
        SessionStarted,
        Unrecognized,
        AssistantText,
        TurnCompleted,
    ]
    assert events[1].raw["request"]["subtype"] == "future_subtype"


def test_unsupported_control_request_reply():
    request = parse_fixture("unknown_control_request.jsonl")[1]
    assert claude_stream.unsupported_control_request(request.raw) == {
        "type": "control_response",
        "response": {
            "subtype": "error",
            "request_id": "cli-req-1",
            "error": "Agent does not support future_subtype",
        },
    }


def test_unsupported_control_request_ignores_other_messages():
    assert claude_stream.unsupported_control_request({"type": "stream_event"}) is None
    assert claude_stream.unsupported_control_request({"type": "mystery_block"}) is None


def test_allow_tool_echoes_input():
    request = PermissionRequest(
        request_id="cli-req-1", tool_name="Read", input={"file_path": "/x"}, tool_call_id="toolu_01"
    )
    assert claude_stream.allow_tool(request) == {
        "type": "control_response",
        "response": {
            "subtype": "success",
            "request_id": "cli-req-1",
            "response": {"behavior": "allow", "updatedInput": {"file_path": "/x"}},
        },
    }


def test_user_message_with_image():
    message = claude_stream.user_message("look", images=[("image/png", "AAAA")])
    assert message["message"]["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
    }


def test_argv():
    argv = claude_stream.claude_argv("claude", model="opus", resume_session_id="abc")
    assert argv[:2] == ["claude", "-p"]
    assert "--permission-prompt-tool" in argv
    assert argv[-4:] == ["--model", "opus", "--resume", "abc"]
