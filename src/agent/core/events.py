# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral events.

Every agent backend (Claude today, Codex/ACP later) translates its wire
protocol into these events. The UI and the store only ever see these.
"""

from __future__ import annotations

from pydantic import Field, JsonValue

from agent.core.model import Model


class SessionStarted(Model):
    """The agent is running and reports its session and capabilities."""

    session_id: str
    model: str | None = None
    cwd: str | None = None
    tools: tuple[str, ...] = ()
    slash_commands: tuple[str, ...] = ()
    auth_source: str | None = None
    agent_version: str | None = None


class AssistantText(Model):
    """Text the assistant wrote."""

    text: str


class AssistantThinking(Model):
    """The assistant's visible reasoning."""

    text: str


class ToolCall(Model):
    """The assistant calls a tool. `input` is whatever that tool takes."""

    tool_call_id: str
    name: str
    input: dict[str, JsonValue]


class ToolResult(Model):
    """What a tool call returned, flattened to text."""

    tool_call_id: str
    content: str
    is_error: bool = False


class PermissionRequest(Model):
    """The agent asks before running a tool. Must be answered."""

    request_id: str
    tool_name: str
    input: dict[str, JsonValue]
    tool_call_id: str | None = None


class TokenUsage(Model):
    """Tokens one turn used."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class TurnCompleted(Model):
    """The agent finished a turn, successfully or not."""

    session_id: str | None
    is_error: bool
    duration_ms: int | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    result: str | None = None


class ControlReply(Model):
    """The agent's answer to a control request we sent."""

    request_id: str
    ok: bool
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None


class Unrecognized(Model):
    """A message we don't understand yet. Kept so nothing is silently lost."""

    raw: dict[str, JsonValue]


Event = (
    SessionStarted
    | AssistantText
    | AssistantThinking
    | ToolCall
    | ToolResult
    | PermissionRequest
    | TurnCompleted
    | ControlReply
    | Unrecognized
)
