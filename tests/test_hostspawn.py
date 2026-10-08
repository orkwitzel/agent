# SPDX-License-Identifier: GPL-3.0-or-later
from agent.core.claude_cli import parse_auth_status
from agent.core.hostspawn import host_argv, scope_unit_name


def test_native_passthrough():
    assert host_argv(["claude", "-p"], flatpak=False) == ["claude", "-p"]


def test_flatpak_runs_on_host():
    assert host_argv(["git", "status"], cwd="/src", flatpak=True) == [
        "flatpak-spawn",
        "--host",
        "--watch-bus",
        "--directory=/src",
        "git",
        "status",
    ]


def test_scope_wraps_inside_flatpak_spawn():
    unit = scope_unit_name(7, "abc")
    assert unit == "app-io.github.orkwitzel.Agent-thread7-abc.scope"
    argv = host_argv(["claude"], scope_unit=unit, flatpak=True)
    assert argv[:3] == ["flatpak-spawn", "--host", "--watch-bus"]
    assert argv[3:6] == ["systemd-run", "--user", "--scope"]
    assert f"--unit={unit}" in argv
    assert argv[-2:] == ["--", "claude"]


def test_auth_status_parsing():
    status = parse_auth_status(
        '{"loggedIn":true,"authMethod":"claude.ai","subscriptionType":"max"}'
    )
    assert status.logged_in and status.subscription == "max"
    assert not parse_auth_status("").logged_in
    assert not parse_auth_status('{"loggedIn":false}').logged_in
