# Agent

A native GNOME app for working with AI coding agents.

Agent drives the [Claude Code](https://code.claude.com/docs/en/setup)
command-line tool you already have installed and signed in to, so it uses
your existing Claude subscription or API key. It never sees your
credentials. Support for more agents (Codex, and anything speaking the
[Agent Client Protocol](https://agentclientprotocol.com)) is planned.

> **Status:** early scaffold. Not usable yet.

Agent is not affiliated with or endorsed by Anthropic.

## Requirements

- GNOME 48 or newer (GTK 4.18, libadwaita 1.7, PyGObject 3.50), or Flatpak
- [Claude Code](https://code.claude.com/docs/en/setup), signed in with
  `claude auth login`

## Install

Flatpak bundles are attached to each
[GitHub release](https://github.com/orkwitzel/agent/releases):

```sh
flatpak install agent.flatpak
```

The Flatpak runs `claude`, `git` and your tools on the host (via
`flatpak-spawn --host`) and can read any folder, because an agent working on
your projects needs your real toolchain. It is not meaningfully sandboxed.

## Building from source

```sh
sudo dnf install glib2-devel blueprint-compiler meson python3-markdown-it-py python3-pydantic   # Fedora
meson setup build --prefix=$PWD/_install
meson install -C build
GSETTINGS_SCHEMA_DIR=_install/share/glib-2.0/schemas _install/bin/agent
```

Or open the folder in GNOME Builder and run it with the Flatpak manifest in
`build-aux/flatpak/`.

## Development

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install meson ninja ruff pytest markdown-it-py pydantic
.venv/bin/pytest
.venv/bin/ruff check .
```

The tests replay recorded `claude` output through a fake `claude`
(`tests/fake_claude.py`), so they don't need Claude Code or use any usage.
See `docs/design.md` for the architecture and the reasoning behind it.

## License

GPL-3.0-or-later. See `COPYING`.
