# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from agent.core.logs import debug_enabled


@pytest.mark.parametrize(
    "messages_debug",
    ["all", "io.github.orkwitzel.Agent", "Gtk io.github.orkwitzel.Agent", "Gtk,all"],
)
def test_debug_logs_follow_g_messages_debug(messages_debug):
    assert debug_enabled(messages_debug)


@pytest.mark.parametrize("messages_debug", ["", "Gtk", "io.github.orkwitzel"])
def test_debug_logs_stay_off_for_other_domains(messages_debug):
    assert not debug_enabled(messages_debug)
