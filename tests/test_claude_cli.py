# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

from agent.core.claude_cli import find_claude, parse_auth_status


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
    assert find_claude("/opt/claude", flatpak=True) == "/opt/claude"
    assert find_claude("/opt/claude", flatpak=False) == "/opt/claude"


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

# Keys as printed by Claude Code 2.1.295 when signed in; values made up.
SIGNED_IN = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "email": "user@example.com",
    "subscriptionType": "max",
}

# Not recorded: shaped from the CLI reference, which says the command
# prints JSON, exits 1 when signed out, and lists "none" as an authMethod.
SIGNED_OUT = {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}


def test_auth_signed_in():
    status = parse_auth_status(json.dumps(SIGNED_IN))
    assert status is not None
    assert status.logged_in
    assert status.method == "claude.ai"
    assert status.subscription == "max"


def test_auth_signed_out():
    status = parse_auth_status(json.dumps(SIGNED_OUT))
    assert status is not None
    assert not status.logged_in


@pytest.mark.parametrize(
    "output",
    [
        "",  # flatpak-spawn --host when claude isn't on the host's PATH
        "not json\n",
        "[]",
        "null",
    ],
)
def test_auth_no_status(output):
    assert parse_auth_status(output) is None
