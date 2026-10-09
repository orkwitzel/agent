# Contributing to Agent

Agent is written by people and coding agents together, and this guide is for
both. It holds the rules that need judgment. Everything a tool can check runs
in `meson test` instead: `pyproject.toml` configures ruff and basedpyright
(each banned API's message names what to use instead), and
`tests/test_standards.py` and `tests/test_layering.py` check the rest. Design
decisions and their reasons are in `docs/design.md`; read it before changing
architecture.

## Setup and checks

```sh
python3 -m venv --system-site-packages .venv
PYGOBJECT_STUB_CONFIG=Gtk4,Gdk4 .venv/bin/pip install --group dev
export PATH=$PWD/.venv/bin:$PATH

meson setup build -Ddev=true --prefix=$PWD/_install
meson test -C build            # lint, types and tests; no real claude needed
meson compile -C build fix     # formatters and ruff's safe fixes
meson install -C build
GSETTINGS_SCHEMA_DIR=_install/share/glib-2.0/schemas _install/bin/agent
```

Native builds need `glib2-devel` (for `glib-compile-resources`);
blueprint-compiler falls back to a Meson subproject if it isn't installed.
Run with `G_MESSAGES_DEBUG=all` for debug logs.

## Project rules

- `agent.core` imports GLib, GObject and Gio but never Gtk, Adw or
  `agent.ui`, so it runs and is tested headless.
- Providers translate their wire protocol into `agent.core.events`; the UI and
  the store only see those events.
- Every external command goes through `agent.core.hostspawn.host_argv`, so it
  works inside Flatpak and agent threads run in their own systemd scope.
- Agent runs only `claude auth status` and `claude auth login` for sign-in. It
  never reads, stores or refreshes Claude credentials, and never modifies the
  `claude` binary.
- Minimum platform: GNOME 48 (libadwaita 1.7, GTK 4.18, PyGObject 3.50),
  Python 3.12 and pydantic 2.10. Newer API needs a version check.
- Every new protocol message shape gets a fixture in `tests/support/fixtures/`,
  replayed by `tests/support/fake_claude.py`.

## Writing code

### Shape

- Write functions. A class is for state that changes over time, a lifecycle
  (open/close, start/stop), or a framework that requires one; pydantic models
  and GObjects are their own kinds.
- Inherit only from framework classes and the two model bases. An interface is
  a `typing.Protocol`, defined once a second implementation exists or for an
  extension point listed in `docs/design.md`.
- Extract a helper when it's reused, or when its name explains a hard chunk;
  otherwise keep the code inline.
- Branch over a union such as `Event` with `match` and `assert_never`, so a new
  member flags every place that must handle it.
- Use `:=` only in `if` and `while` conditions.
- Module order: license line, docstring, `from __future__ import annotations`,
  imports, constants (including `_logger`), type aliases, models, public
  functions and classes, then private helpers below their callers. A long
  module may use one-line `# Section` headers; the order then holds within
  each section.
- Split a module when it has two responsibilities, whatever its length.

### Data

- Every data class is a frozen, strict pydantic model: `agent.core.model.Model`
  for our own data, `WireModel` for protocols we don't own (it ignores unknown
  fields). Change one with `model_copy(update=...)`.
- A fixed set of values is a named `Literal` type. JSON we pass through is
  `pydantic.JsonValue`.
- Validate at the boundary (wire, disk, user input) and trust the types inside
  it: check for `None` only where the type allows `None`, and wrap in `try`
  only what can raise.

### Names

- Name things for what they are or do: `Store`, `AgentProcess`, never a
  `Manager`, `Helper` or `utils`.
- Spell words out (`message`, `block_type`). The allowed short forms are
  `argv`, `cwd`, `id`, `db`, `url`, `json`, `ui`, and Python's `self`, `cls`,
  `args` and `kwargs`.
- Booleans read as yes/no questions: `is_error`, `has_session`, `auto_allow`.
- Prefix everything not used outside its module with `_`. Dropping the `_`
  makes it part of the module's API.
- Domain words come from `CONTEXT.md` once it exists: use the glossary's word,
  not a synonym.

### Comments and docstrings

- Docstrings are prose, on every module and every public function and class
  (methods marked `@override` excepted). Say what the signature can't: purpose,
  constraints, why. The types already say what `Args:`/`Returns:` sections
  would.
- Comments explain why. Git holds the history, so code that's gone is deleted
  rather than commented out, and comments describe the code as it is now.
- A TODO names its issue: `# TODO: #12 resume sessions`.

### Errors and logging

- Catch the narrowest error. `except Exception` belongs at boundaries only
  (task runners, callbacks from code we don't control, signal handlers) and
  logs with `_logger.exception`.
- Every `except` re-raises (`raise ... from error`), logs, or turns the error
  into a visible result. Ignoring one takes a comment saying why.
- Define an exception class only when a caller catches it specifically;
  otherwise raise a built-in.
- A lookup that can miss returns `X | None`; a failure raises.
- Each module logs through `_logger = logging.getLogger(__name__)`: `debug` for
  protocol traffic, `info` for lifecycle, `warning` for surprises we recovered
  from, `error` and `exception` for failures.
- User content (prompts, replies, tool input and output, file contents) is
  logged at `debug` only, and credentials never.

### Every fact once

- Each fact lives in one place: constants, protocol field names, paths,
  formats, rules such as how a thread is titled. Search for an existing helper
  before writing one.
- Code that merely looks alike may stay separate until a third copy shows a
  real pattern.
- Build what's needed now; options, parameters and hooks arrive with the code
  that uses them.
- Rename freely and update every caller: nothing outside the repo calls this
  code. Stored user data (SQLite, GSettings) is the exception and always gets
  a migration.
- Delete dead code and wrappers that only pass their arguments on.

### The main loop

- Everything runs on the GLib main loop, so every wait is async:
  `Gio.Subprocess` through `hostspawn`, `asyncio.sleep`, Gio or libsoup for
  the network, `Gio.File` for files of unknown size. Small local files and the
  SQLite store may be read directly.
- Await Gio calls with `agent.core.mainloop.gio_call`, and start background
  work with a `TaskSet`, which keeps tasks alive and logs their failures.
- Commands are argv lists, never shell strings.

### UI

- State lives in `agent.core` as GObjects with properties and
  `Gio.ListStore` lists, wrapping pydantic models rather than copying them.
  Widgets bind to that state and forward actions to core methods; the
  decisions happen in core.
- Expose state as properties. A custom signal is for an event that isn't state.
- All layout is Blueprint: one template class and one `.blp` per widget, and
  list rows from Blueprint templates. Declare template children with
  `agent.ui.template.child(Type)`.
- Commands are actions, registered with `agent.ui.actions.add_action`. Signal
  handlers are named `_on_<source>_<signal>`.
- On GTK objects use `get_x()` and `set_x()`; on our own, plain attributes.
- Use existing Adw and Gtk widgets and libadwaita style classes first. Custom
  CSS goes in one `style.css` resource.
- Follow the GNOME HIG: Title Case for titles, buttons and menu items, sentence
  case for descriptions, `…` on actions that ask for more input, typographic
  quotes. Every icon-only button has `tooltip-text`. Everything works from the
  keyboard and at 360 px wide.
- Every user-visible string goes through gettext as a whole sentence with
  named placeholders, `_("Delete “{name}”?").format(name=name)`, with
  `ngettext` for plurals and a `# Translators:` comment where the meaning is
  ambiguous. List its file in `po/POTFILES.in`.

### Tests

- Every behaviour change in `agent.core` comes with a test, and every bug fix
  with one that fails without it. The UI stays thin enough to need none.
- Tests mirror `src/agent/`: `src/agent/core/store.py` is tested in
  `tests/core/test_store.py`. Shared helpers, the fake claude and its fixtures
  live in `tests/support/`.
- Plain pytest functions named for the behaviour, such as
  `test_unknown_message_type_is_kept`.
- Use real objects: SQLite and files in `tmp_path`, the fake claude for the
  CLI. Patch only what we don't control, such as the environment or time.
- Compare whole objects: `assert events == [AssistantText(text="hi")]`.
- Run async code with `support.run`.
- A test may repeat setup to read on its own. Move setup into a fixture once
  several files need it.

### Dependencies

- Reach for the standard library, then GLib and Gio, then a package. A package
  earns its place by replacing real code or something hard to get right, and
  must be packaged in Fedora and Debian 13 and buildable in the Flatpak.
- Proposals for libraries and tools that make the code cleaner or development
  easier are welcome. Check that the source is reputable, the project is
  maintained and its licence is GPL-3.0-compatible, then propose it. A
  maintainer approves and adds it: runtime dependencies in `docs/design.md`,
  dev tools in `pyproject.toml`.

## Working on a change

- Stay in scope: change what the task needs. Note anything else worth fixing
  in your summary, or open an issue labelled `needs-triage` if it matters.
- Done means `meson test -C build` passes with every check at full strength,
  the docs describing what changed are updated in the same commit
  (`docs/design.md`, `CONTEXT.md`, this file, `po/POTFILES.in`), and the
  summary or PR description says honestly what failed or went unchecked,
  including a UI change nobody looked at.
- Where these rules are silent, match the surrounding code. A new pattern
  others will copy goes in the summary, with a suggested addition here.
- To break a rule where it's wrong for one spot, leave a comment there saying
  why and mention it in the summary. Suppressions name their rule:
  `# noqa: BLE001  # why`, `# pyright: ignore[reportAny]  # why`. To change a
  rule for everyone, propose an edit to this file.
- Commits follow Conventional Commits, `type(scope): summary`. The type is one
  of `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`
  or `style`; the optional scope is the area's name in the code (`store`,
  `claude-stream`, `flatpak`). The body says why, and `Closes #12` links the
  issue. One logical change per commit, each passing the checks. `!` marks a
  change users notice: a database migration, renamed settings, a removed
  feature.
