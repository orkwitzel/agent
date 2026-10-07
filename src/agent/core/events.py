# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral events.

Every agent backend (Claude today, Codex/ACP later) translates its wire
protocol into these events. The UI and the store only ever see these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SessionStarted:
    session_id: str
    model: str | None = None
    cwd: str | None = None
    tools: list[str] = field(default_factory=list)
    slash_commands: list[str] = field(default_factory=list)
    auth_source: str | None = None
    agent_version: str | None = None


@dataclass(frozen=True)
class AssistantText:
    text: str


@dataclass(frozen=True)
class AssistantThinking:
    text: str


@dataclass(frozen=True)
class ToolCall:
    tool_call_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class PermissionRequest:
    """The agent asks before running a tool. Must be answered."""

    request_id: str
    tool_name: str
    input: dict[str, Any]
    tool_call_id: str | None = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class TurnCompleted:
    session_id: str | None
    is_error: bool
    duration_ms: int | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    result: str | None = None


@dataclass(frozen=True)
class ControlReply:
    """The agent's answer to a control request we sent."""

    request_id: str
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class Unrecognized:
    """A line we don't understand yet. Kept so nothing is silently lost."""

    raw: dict[str, Any]


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
