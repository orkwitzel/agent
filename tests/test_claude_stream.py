# SPDX-License-Identifier: GPL-3.0-or-later
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
from conftest import FIXTURES


def parse_fixture(name):
    events = []
    for line in (FIXTURES / name).read_text().splitlines():
        events.extend(claude_stream.parse_line(line))
    return events


def test_simple_turn_event_sequence():
    kinds = [type(e) for e in parse_fixture("simple_turn.jsonl")]
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
    assert started.slash_commands == ["compact", "review"]
    assert started.agent_version == "2.1.293"


def test_tool_result_flattens_text_blocks():
    result = parse_fixture("simple_turn.jsonl")[4]
    assert result == ToolResult("toolu_01", "# Project\nHello", is_error=False)


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
    assert event == Unrecognized({"type": "stream_event", "x": 1})


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
    assert claude_stream.parse_line(line) == [ControlReply("agent-1", True, {"percentage": 12})]


def test_allow_tool_echoes_input():
    request = PermissionRequest("cli-req-1", "Read", {"file_path": "/x"}, "toolu_01")
    assert claude_stream.allow_tool(request) == {
        "type": "control_response",
        "response": {
            "subtype": "success",
            "request_id": "cli-req-1",
            "response": {"behavior": "allow", "updatedInput": {"file_path": "/x"}},
        },
    }


def test_user_message_with_image():
    msg = claude_stream.user_message("look", [("image/png", "AAAA")])
    assert msg["message"]["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
    }


def test_argv():
    argv = claude_stream.claude_argv("claude", model="opus", resume_session_id="abc")
    assert argv[:2] == ["claude", "-p"]
    assert "--permission-prompt-tool" in argv
    assert argv[-4:] == ["--model", "opus", "--resume", "abc"]
