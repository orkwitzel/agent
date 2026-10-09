# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import shlex

import pytest

from agent.core.claude_cli import check_claude, find_claude, parse_auth_status
from agent.core.process import install_glib_event_loop


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty home directory and a PATH with no claude on it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return home


# find_claude


def test_configured_path_wins(home):
    make_executable(home / ".local/bin/claude")
    assert find_claude(configured_path="/opt/claude", flatpak=True) == "/opt/claude"
    assert find_claude(configured_path="/opt/claude", flatpak=False) == "/opt/claude"


def test_flatpak_finds_fallback(home):
    claude = make_executable(home / ".local/bin/claude")
    assert find_claude(flatpak=True) == str(claude)


def test_flatpak_finds_second_fallback(home):
    claude = make_executable(home / ".claude/local/claude")
    assert find_claude(flatpak=True) == str(claude)


def test_flatpak_without_fallback_uses_host_path(home, tmp_path, monkeypatch):
    # The sandbox's PATH isn't the host's, so a claude on it is ignored.
    sandbox_bin = tmp_path / "sandbox-bin"
    make_executable(sandbox_bin / "claude")
    monkeypatch.setenv("PATH", str(sandbox_bin))
    assert find_claude(flatpak=True) == "claude"


def test_fallback_must_be_executable(home):
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/claude").write_text("not executable")
    assert find_claude(flatpak=True) == "claude"
    assert find_claude(flatpak=False) is None


def test_native_prefers_path(home, tmp_path, monkeypatch):
    make_executable(home / ".local/bin/claude")
    on_path = make_executable(tmp_path / "bin/claude")
    monkeypatch.setenv("PATH", str(on_path.parent))
    assert find_claude(flatpak=False) == str(on_path)


def test_native_finds_fallback(home):
    claude = make_executable(home / ".local/bin/claude")
    assert find_claude(flatpak=False) == str(claude)


def test_native_missing(home):
    assert find_claude(flatpak=False) is None


# parse_auth_status

# Claude Code 2.1.295 prints these on stdout, indented by 2, and nothing
# on stderr. Signed in it exits 0; keys as printed, values made up.
SIGNED_IN = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "analyticsDisabled": False,
    "projectsDirectory": "/home/user/.claude/projects",
    "configDirectory": "/home/user/.claude",
    "email": "user@example.com",
    "orgId": "00000000-0000-0000-0000-000000000000",
    "orgName": "Example",
    "subscriptionType": "max",
}

# Signed out it exits 1. Recorded with HOME and CLAUDE_CONFIG_DIR pointing
# at an empty directory; only the paths are changed.
SIGNED_OUT = {
    "loggedIn": False,
    "authMethod": "none",
    "apiProvider": "firstParty",
    "analyticsDisabled": False,
    "projectsDirectory": "/home/user/.claude/projects",
    "configDirectory": "/home/user/.claude",
}


def test_auth_signed_in():
    status = parse_auth_status(json.dumps(SIGNED_IN, indent=2) + "\n")
    assert status is not None
    assert status.logged_in
    assert status.method == "claude.ai"
    assert status.subscription == "max"


def test_auth_signed_out():
    status = parse_auth_status(json.dumps(SIGNED_OUT, indent=2) + "\n")
    assert status is not None
    assert not status.logged_in
    assert status.method == "none"


@pytest.mark.parametrize(
    "output",
    [
        "",  # flatpak-spawn --host when claude isn't on the host's PATH
        "Not logged in. Run claude auth login to authenticate.\n",  # --text
        "[]",
        "null",
        '{"authMethod": "none"}',
        '{"loggedIn": "false"}',
    ],
)
def test_auth_no_status(output):
    assert parse_auth_status(output) is None


# check_claude


def run(coro):
    install_glib_event_loop()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def stub_claude(tmp_path, auth_output="", auth_exit=0, version_exit=0):
    """A claude that prints `auth_output` for `auth status` and exits with
    `version_exit` for `--version`. Only shell builtins, so PATH can be empty."""
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = auth ]; then printf %s {shlex.quote(auth_output)}; exit {auth_exit}; fi\n'
        f"exit {version_exit}\n"
    )
    script.chmod(0o755)
    return str(script)


def test_check_signed_in(tmp_path):
    claude = stub_claude(tmp_path, json.dumps(SIGNED_IN, indent=2) + "\n")
    assert run(check_claude(configured_path=claude, flatpak=False)) == "ready"


def test_check_signed_out(tmp_path):
    # Signed out, claude exits 1; the status still comes from the JSON.
    claude = stub_claude(tmp_path, json.dumps(SIGNED_OUT, indent=2) + "\n", auth_exit=1)
    assert run(check_claude(configured_path=claude, flatpak=False)) == "signed-out"


@pytest.mark.parametrize(("version_exit", "state"), [(0, "signed-out"), (1, "missing")])
def test_check_without_status_asks_version(tmp_path, version_exit, state):
    # No status to read: offer to sign in only if claude runs at all.
    # flatpak-spawn --host prints nothing and exits 1 when claude is missing.
    claude = stub_claude(tmp_path, "", auth_exit=1, version_exit=version_exit)
    assert run(check_claude(configured_path=claude, flatpak=False)) == state


def test_check_not_found(home):
    assert run(check_claude(flatpak=False)) == "missing"


def test_check_cannot_spawn(tmp_path):
    assert (
        run(check_claude(configured_path=str(tmp_path / "no-such-claude"), flatpak=False))
        == "missing"
    )


def test_check_claude_gone_before_version(tmp_path):
    # It ran once without printing a status, then vanished: still MISSING.
    script = tmp_path / "claude"
    script.write_text('#!/bin/sh\nrm -- "$0"\nexit 1\n')
    script.chmod(0o755)
    assert run(check_claude(configured_path=str(script), flatpak=False)) == "missing"
