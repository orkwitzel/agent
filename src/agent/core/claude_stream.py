# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude Code's stream-json protocol.

Agent drives the user's own, unmodified `claude` binary in headless mode:

    claude -p --input-format stream-json --output-format stream-json \
        --verbose --permission-prompt-tool stdio

Each stdout line is one JSON object. This module turns those lines into
neutral events and builds the JSON lines we write to stdin. It does no I/O.

Message shapes follow the control protocol defined in
@anthropic-ai/claude-agent-sdk (sdk.d.ts).
"""

from __future__ import annotations

import json
from typing import Any

from agent.core.events import (
    AssistantText,
    AssistantThinking,
    ControlReply,
    Event,
    PermissionRequest,
    SessionStarted,
    TokenUsage,
    ToolCall,
    ToolResult,
    TurnCompleted,
    Unrecognized,
)


def claude_argv(
    claude_path: str,
    *,
    model: str | None = None,
    resume_session_id: str | None = None,
) -> list[str]:
    argv = [
        claude_path,
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-prompt-tool",
        "stdio",
    ]
    if model:
        argv += ["--model", model]
    if resume_session_id:
        argv += ["--resume", resume_session_id]
    return argv


# Parsing (claude -> us)


def parse_line(line: str | bytes) -> list[Event]:
    """Parse one stdout line. Blank lines yield nothing."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    line = line.strip()
    if not line:
        return []
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return [Unrecognized({"unparsable": line})]
    if not isinstance(msg, dict):
        return [Unrecognized({"value": msg})]
    return parse_message(msg)


def parse_message(msg: dict[str, Any]) -> list[Event]:
    kind = msg.get("type")
    if kind == "system" and msg.get("subtype") == "init":
        return [_session_started(msg)]
    if kind == "assistant":
        return _assistant_blocks(msg)
    if kind == "user":
        return _tool_results(msg)
    if kind == "result":
        return [_turn_completed(msg)]
    if kind == "control_request":
        return _control_request(msg)
    if kind == "control_response":
        return [_control_reply(msg)]
    return [Unrecognized(msg)]


def _session_started(msg: dict[str, Any]) -> SessionStarted:
    return SessionStarted(
        session_id=msg.get("session_id", ""),
        model=msg.get("model"),
        cwd=msg.get("cwd"),
        tools=list(msg.get("tools") or []),
        slash_commands=list(msg.get("slash_commands") or []),
        auth_source=msg.get("apiKeySource"),
        agent_version=msg.get("claude_code_version"),
    )


def _assistant_blocks(msg: dict[str, Any]) -> list[Event]:
    events: list[Event] = []
    for block in (msg.get("message") or {}).get("content") or []:
        btype = block.get("type")
        if btype == "text":
            events.append(AssistantText(block.get("text", "")))
        elif btype == "thinking":
            events.append(AssistantThinking(block.get("thinking", "")))
        elif btype == "tool_use":
            events.append(
                ToolCall(
                    tool_call_id=block.get("id", ""),
                    name=block.get("name", ""),
                    input=block.get("input") or {},
                )
            )
        else:
            events.append(Unrecognized(block))
    return events


def _tool_results(msg: dict[str, Any]) -> list[Event]:
    content = (msg.get("message") or {}).get("content")
    if not isinstance(content, list):
        # A plain user echo, not a tool result.
        return []
    events: list[Event] = []
    for block in content:
        if block.get("type") != "tool_result":
            continue
        events.append(
            ToolResult(
                tool_call_id=block.get("tool_use_id", ""),
                content=_flatten_content(block.get("content")),
                is_error=bool(block.get("is_error", False)),
            )
        )
    return events


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, dict) and part.get("type") == "image":
                parts.append("[image]")
        return "\n".join(parts)
    return json.dumps(content)


def _turn_completed(msg: dict[str, Any]) -> TurnCompleted:
    usage = msg.get("usage") or {}
    return TurnCompleted(
        session_id=msg.get("session_id"),
        is_error=bool(msg.get("is_error", False)),
        duration_ms=msg.get("duration_ms"),
        usage=TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        ),
        result=msg.get("result"),
    )


def _control_request(msg: dict[str, Any]) -> list[Event]:
    request = msg.get("request") or {}
    if request.get("subtype") == "can_use_tool":
        return [
            PermissionRequest(
                request_id=msg.get("request_id", ""),
                tool_name=request.get("tool_name", ""),
                input=request.get("input") or {},
                tool_call_id=request.get("tool_use_id"),
            )
        ]
    return [Unrecognized(msg)]


def _control_reply(msg: dict[str, Any]) -> ControlReply:
    response = msg.get("response") or {}
    ok = response.get("subtype") == "success"
    return ControlReply(
        request_id=response.get("request_id", ""),
        ok=ok,
        payload=response.get("response") or {},
        error=None if ok else response.get("error"),
    )


# Building (us -> claude)


def encode(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


def user_message(text: str, images: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """A user turn. `images` is a list of (media_type, base64_data)."""
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for media_type, data in images or []:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": data},
            }
        )
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


def control_request(request_id: str, request: dict[str, Any]) -> dict[str, Any]:
    return {"type": "control_request", "request_id": request_id, "request": request}


def interrupt(request_id: str) -> dict[str, Any]:
    return control_request(request_id, {"subtype": "interrupt"})


def set_model(request_id: str, model: str | None) -> dict[str, Any]:
    return control_request(request_id, {"subtype": "set_model", "model": model})


def get_context_usage(request_id: str) -> dict[str, Any]:
    return control_request(request_id, {"subtype": "get_context_usage"})


def allow_tool(request: PermissionRequest) -> dict[str, Any]:
    return _control_success(
        request.request_id, {"behavior": "allow", "updatedInput": request.input}
    )


def deny_tool(request: PermissionRequest, message: str) -> dict[str, Any]:
    return _control_success(
        request.request_id, {"behavior": "deny", "message": message, "interrupt": False}
    )


def _control_success(request_id: str, response: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "control_response",
        "response": {"subtype": "success", "request_id": request_id, "response": response},
    }
