# Agent

Native GNOME (GTK4 + libadwaita) client for AI coding agents. v1 drives the
user's own, unmodified `claude` CLI over its stream-json protocol. App ID
`io.github.orkwitzel.Agent`, GPL-3.0-or-later. Design decisions and their
reasons are in `docs/design.md`; read it before changing architecture.

## Commands

```sh
python3 -m venv --system-site-packages .venv
PYGOBJECT_STUB_CONFIG=Gtk4,Gdk4 .venv/bin/pip install --group dev

PATH=$PWD/.venv/bin:$PATH meson setup build -Ddev=true --prefix=$PWD/_install
PATH=$PWD/.venv/bin:$PATH meson test -C build    # lint, types and tests; no real claude needed
PATH=$PWD/.venv/bin:$PATH meson compile -C build fix    # apply formatters and safe fixes
PATH=$PWD/.venv/bin:$PATH meson install -C build
GSETTINGS_SCHEMA_DIR=_install/share/glib-2.0/schemas _install/bin/agent
```

Native builds need `glib2-devel` (for `glib-compile-resources`);
blueprint-compiler falls back to a Meson subproject if not installed.

## Rules

- `src/agent/core/` must never import Gtk, Adw or `agent.ui`
  (`tests/test_layering.py` enforces this). GLib/Gio is fine.
- Providers translate their wire protocol into `agent.core.events`; the UI
  and the SQLite store only see those events.
- Every external command goes through `agent.core.hostspawn.host_argv` so it
  works inside Flatpak (`flatpak-spawn --host`) and runs agent threads in
  their own systemd user scope.
- Never read, store or refresh Claude credentials, and never modify or
  patch the `claude` binary. Only `claude auth status` / `claude auth login`.
- Async: Gio async APIs awaited on the GLib main loop
  (`install_glib_event_loop`). Hold strong references to tasks. Use
  `asyncio.to_thread` only for CPU-heavy work.
- Minimum platform: GNOME 48 (libadwaita 1.7, GTK 4.18, PyGObject 3.50).
  Don't use newer API without a version check.
- UI layouts are Blueprint (`.blp`); all user-visible strings go through
  gettext (`_()`, `_("...")` in Blueprint) and their files in `po/POTFILES.in`.
- Protocol changes are caught by fixtures in `tests/support/fixtures/`,
  replayed by `tests/support/fake_claude.py`. Add a fixture for every new
  message shape.

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
