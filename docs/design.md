# Design

Decisions settled before the first line of code (2026-10-07), with the
reasons for them. Change them deliberately, not by drift.

## Product

- **What:** a public, open-source, native GNOME client for AI coding
  agents, in the spirit of [T3 Code](https://github.com/pingdotgg/t3code).
- **v1 scope:** a chat front-end for Claude Code. Projects (folders) hold
  threads; threads stream Claude's output with rendered tool calls.
- **Long term:** any provider, including raw API providers. That comes from
  agents that speak the [Agent Client Protocol](https://agentclientprotocol.com)
  (OpenCode, Goose, Gemini CLI, …) and `codex app-server`, not from writing
  our own agent loop.

## Talking to Claude

Agent runs the user's own, **unmodified, installed `claude`**:

```
claude -p --input-format stream-json --output-format stream-json \
  --verbose --permission-prompt-tool stdio [--model M] [--resume SESSION]
```

- **Why not the Agent SDK or `claude-agent-acp`:** Anthropic's
  [legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance)
  forbids third-party apps from offering Claude.ai login or routing
  subscription credentials, but explicitly allows "an end user … signing in
  to the unmodified Claude Code binary with their own Claude subscription."
  Driving the real binary is the clearest fit. It is also the dominant
  pattern among similar tools (Opcode, Vibe Kanban, Sculptor, Jean).
- **Credentials:** never read, stored or refreshed. Login state comes from
  `claude auth status` (JSON). Signing in means running `claude auth login`.
- **Finding claude:** PATH, or a path set in Preferences. If it's missing,
  link to the download page.
- **Permissions:** v1 auto-allows every `can_use_tool` request in code and
  warns on first run. Because the permission channel is already wired, adding
  approval cards later is a UI-only change.
- **Processes:** one long-lived `claude` per thread, each in its own systemd
  user scope, so a thread's whole process tree stops as one unit. Freezing
  idle scopes and pushing their memory to zram (`memory.reclaim`) is a
  planned optimisation.

## Stack

- **Python + PyGObject**, GTK4 + libadwaita. Native distro packaging is
  easier for Python than Rust, and the protocol is plain JSON lines, so no
  SDK is needed.
- **Minimum platform GNOME 48** (libadwaita 1.7 for `WrapBox` and
  `ToggleGroup`; PyGObject 3.50). Debian 13 and Fedora 42+ qualify.
- **Meson** build, **Blueprint** UI files, **gettext** from day one.
- **Async:** Gio async APIs awaited through PyGObject's asyncio integration on
  the GLib main loop. One thread. `asyncio.to_thread` for CPU-heavy work.
- **Layering:** `agent.core` (providers, events, store, process helpers)
  never imports GTK, so it is testable headless and future providers plug
  into the same neutral events.
- **Storage:** Agent's own SQLite database of provider-neutral events. Each
  thread keeps Claude's `session_id` for `--resume`. Claude's session files
  are left to Claude.
- **Dependencies:** PyGObject and `markdown-it-py` only.

## UI

- `Adw.NavigationSplitView`: projects with nested threads in the sidebar,
  the thread in the content pane. Collapses on narrow widths.
- The transcript is a `Gtk.ListView` of native rows: Pango labels for text,
  GtkSourceView for code, and collapsible tool-call rows. No webview.
- The message box and thread header have stop, a model picker, image
  attachments, `@file` autocomplete (`git ls-files`, sent as plain `@path`,
  which Claude expands), slash-command autocomplete (from the `init` message),
  message queueing, a context meter (`get_context_usage`) and per-turn token
  counts. There is no cost display, because cost is misleading on
  subscriptions.
- Thread titles are the first message trimmed, and can be renamed. AI titles
  are an opt-in setting (off by default), which runs a one-shot Haiku call.
- Quitting while threads run asks for confirmation. There are no desktop
  notifications.
- Preferences (stored in GSettings): claude path, default model, AI titles,
  token counts, update check.

## Quality and shipping

- pytest on stream-json fixtures replayed by a fake `claude`, plus ruff.
  The UI is tested by hand.
- Flatpak first: `.flatpak` bundles on GitHub Releases with an in-app
  "new version" banner, then Flathub once stable. Permissions are
  `--talk-name=org.freedesktop.Flatpak` (run claude and git on the host) and
  `--filesystem=host`.
- Licensed GPL-3.0-or-later.

## Deferred

Permission approval cards, git worktrees per thread and parallel branches,
a diff/changes panel, an embedded terminal pane, freezing idle processes,
desktop notifications, a cost display, Codex and ACP providers, COPR/AUR
packages, Weblate, and importing sessions started in the terminal.
