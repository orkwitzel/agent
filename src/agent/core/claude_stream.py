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
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

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
from agent.core.model import WireModel

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def claude_argv(
    claude_path: str,
    *,
    model: str | None = None,
    resume_session_id: str | None = None,
) -> list[str]:
    """The command line for one long-lived, headless claude."""
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


class _SystemInit(WireModel):
    session_id: str
    model: str
    cwd: str
    tools: list[str]
    slash_commands: list[str]
    api_key_source: str = Field(alias="apiKeySource")
    claude_code_version: str


class _AssistantContent(WireModel):
    content: list[dict[str, JsonValue]]


class _AssistantMessage(WireModel):
    message: _AssistantContent


class _UserContent(WireModel):
    content: str | list[dict[str, JsonValue]]


class _UserMessage(WireModel):
    message: _UserContent


class _TextBlock(WireModel):
    text: str


class _ThinkingBlock(WireModel):
    thinking: str


class _ToolUseBlock(WireModel):
    id: str
    name: str
    input: dict[str, JsonValue]


class _ToolResultBlock(WireModel):
    tool_use_id: str
    content: str | list[dict[str, JsonValue]] | None = None
    is_error: bool = False


class _Usage(WireModel):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


class _Result(WireModel):
    session_id: str
    is_error: bool
    duration_ms: int
    usage: _Usage
    result: str | None = None


class _ControlRequest(WireModel):
    request_id: str
    request: dict[str, JsonValue]


class _CanUseTool(WireModel):
    tool_name: str
    input: dict[str, JsonValue]
    tool_use_id: str | None = None


class _ControlResponseBody(WireModel):
    subtype: Literal["success", "error"]
    request_id: str
    response: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None


class _ControlResponse(WireModel):
    response: _ControlResponseBody


def parse_line(line: str) -> list[Event]:
    """Parse one stdout line. Blank lines yield nothing."""
    line = line.strip()
    if not line:
        return []
    try:
        message = _JSON.validate_json(line)
    except ValidationError:
        return [Unrecognized(raw={"unparsable": line})]
    if not isinstance(message, dict):
        return [Unrecognized(raw={"value": message})]
    return _parse_message(message)


def _parse_message(message: dict[str, JsonValue]) -> list[Event]:
    """Turn one message into events.

    A message we don't handle, or whose shape doesn't match what we expect,
    becomes `Unrecognized` as a whole.
    """
    try:
        match message.get("type"):
            case "system" if message.get("subtype") == "init":
                return [_session_started(_SystemInit.model_validate(message))]
            case "assistant":
                content = _AssistantMessage.model_validate(message).message.content
                return [_assistant_block(block) for block in content]
            case "user":
                return _tool_results(_UserMessage.model_validate(message).message.content)
            case "result":
                return [_turn_completed(_Result.model_validate(message))]
            case "control_request":
                return [_control_request(message)]
            case "control_response":
                return [_control_reply(_ControlResponse.model_validate(message).response)]
            case _:
                return [Unrecognized(raw=message)]
    except ValidationError:
        return [Unrecognized(raw=message)]


def _session_started(init: _SystemInit) -> SessionStarted:
    return SessionStarted(
        session_id=init.session_id,
        model=init.model,
        cwd=init.cwd,
        tools=tuple(init.tools),
        slash_commands=tuple(init.slash_commands),
        auth_source=init.api_key_source,
        agent_version=init.claude_code_version,
    )


def _assistant_block(block: dict[str, JsonValue]) -> Event:
    match block.get("type"):
        case "text":
            return AssistantText(text=_TextBlock.model_validate(block).text)
        case "thinking":
            return AssistantThinking(text=_ThinkingBlock.model_validate(block).thinking)
        case "tool_use":
            tool_use = _ToolUseBlock.model_validate(block)
            return ToolCall(tool_call_id=tool_use.id, name=tool_use.name, input=tool_use.input)
        case _:
            return Unrecognized(raw=block)


def _tool_results(content: str | list[dict[str, JsonValue]]) -> list[Event]:
    if isinstance(content, str):
        # A plain user echo, not a tool result.
        return []
    results = [
        _ToolResultBlock.model_validate(block)
        for block in content
        if block.get("type") == "tool_result"
    ]
    return [
        ToolResult(
            tool_call_id=result.tool_use_id,
            content=_flatten_content(result.content),
            is_error=result.is_error,
        )
        for result in results
    ]


def _flatten_content(content: str | list[dict[str, JsonValue]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for part in content:
        match part:
            case {"type": "text", "text": str(text)}:
                parts.append(text)
            case {"type": "image"}:
                parts.append("[image]")
            case _:
                pass
    return "\n".join(parts)


def _turn_completed(result: _Result) -> TurnCompleted:
    return TurnCompleted(
        session_id=result.session_id,
        is_error=result.is_error,
        duration_ms=result.duration_ms,
        usage=TokenUsage(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_input_tokens,
            cache_creation_tokens=result.usage.cache_creation_input_tokens,
        ),
        result=result.result,
    )


def _control_request(message: dict[str, JsonValue]) -> Event:
    control = _ControlRequest.model_validate(message)
    if control.request.get("subtype") != "can_use_tool":
        return Unrecognized(raw=message)
    request = _CanUseTool.model_validate(control.request)
    return PermissionRequest(
        request_id=control.request_id,
        tool_name=request.tool_name,
        input=request.input,
        tool_call_id=request.tool_use_id,
    )


def _control_reply(body: _ControlResponseBody) -> ControlReply:
    ok = body.subtype == "success"
    return ControlReply(
        request_id=body.request_id,
        ok=ok,
        payload=body.response,
        error=None if ok else body.error,
    )


# Building (us -> claude)


def encode(message: dict[str, JsonValue]) -> bytes:
    """One stdin line: compact JSON and a newline."""
    return (json.dumps(message, separators=(",", ":")) + "\n").encode()


def user_message(text: str, *, images: Sequence[tuple[str, str]] = ()) -> dict[str, JsonValue]:
    """A user turn. `images` holds (media_type, base64_data) pairs."""
    content: list[JsonValue] = [{"type": "text", "text": text}]
    for media_type, data in images:
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


def control_request(request_id: str, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """A control request we send; claude answers with a `ControlReply`."""
    return {"type": "control_request", "request_id": request_id, "request": request}


def interrupt(request_id: str) -> dict[str, JsonValue]:
    """Ask claude to stop the running turn."""
    return control_request(request_id, {"subtype": "interrupt"})


def set_model(request_id: str, model: str | None) -> dict[str, JsonValue]:
    """Switch the model for the next turns; None means claude's default."""
    return control_request(request_id, {"subtype": "set_model", "model": model})


def get_context_usage(request_id: str) -> dict[str, JsonValue]:
    """Ask how full the context window is."""
    return control_request(request_id, {"subtype": "get_context_usage"})


def allow_tool(request: PermissionRequest) -> dict[str, JsonValue]:
    """Let the tool run with the input it asked for."""
    return _control_success(
        request.request_id, {"behavior": "allow", "updatedInput": request.input}
    )


def deny_tool(request: PermissionRequest, message: str) -> dict[str, JsonValue]:
    """Refuse the tool call; `message` tells the model why."""
    return _control_success(
        request.request_id, {"behavior": "deny", "message": message, "interrupt": False}
    )


def unsupported_control_request(message: dict[str, JsonValue]) -> dict[str, JsonValue] | None:
    """An error reply to a control request we don't handle.

    The CLI waits for a reply to every control request, so one left
    unanswered can stall the turn. Returns None if `message` isn't a
    control request we could reply to.
    """
    if message.get("type") != "control_request":
        return None
    try:
        control = _ControlRequest.model_validate(message)
    except ValidationError:
        # Without a request id there is nothing to reply to.
        return None
    subtype = control.request.get("subtype")
    return _control_error(control.request_id, f"Agent does not support {subtype}")


def _control_success(request_id: str, response: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "type": "control_response",
        "response": {"subtype": "success", "request_id": request_id, "response": response},
    }


def _control_error(request_id: str, error: str) -> dict[str, JsonValue]:
    return {
        "type": "control_response",
        "response": {"subtype": "error", "request_id": request_id, "error": error},
    }
