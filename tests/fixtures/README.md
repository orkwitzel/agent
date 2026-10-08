# Fixtures

Each `.jsonl` file is one `claude` stream-json stdout transcript, one JSON
object per line, replayed by `tests/fake_claude.py`.

`simple_turn.jsonl` is hand-written from the shapes in
`@anthropic-ai/claude-agent-sdk`'s `sdk.d.ts`, not recorded. Replace or
supplement it with real recordings (`claude -p --output-format stream-json
--verbose ... > fixture.jsonl`) so protocol changes in new Claude Code
releases show up as test failures.

`unknown_control_request.jsonl` sends a `control_request` with a subtype
Agent doesn't handle. The fake waits for our reply, so it proves we answer
such requests with an error instead of leaving the CLI waiting.
