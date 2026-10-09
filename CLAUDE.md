# Agent

Native GNOME (GTK4 + libadwaita) client for AI coding agents. v1 drives the
user's own, unmodified `claude` CLI over its stream-json protocol. App ID
`io.github.orkwitzel.Agent`, GPL-3.0-or-later.

The setup, the checks, the project rules and the code standards are in
CONTRIBUTING.md, loaded here:

@CONTRIBUTING.md

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
