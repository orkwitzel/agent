# SPDX-License-Identifier: GPL-3.0-or-later
"""Running coroutines in the background on the GLib main loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

_log = logging.getLogger(__name__)


class TaskSet:
    """Runs coroutines as tasks and keeps them alive until they finish.

    asyncio only holds weak references to tasks, so a task nobody keeps
    can be garbage-collected mid-await. Nothing awaits these tasks, so a
    failing one is logged here instead of being lost.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coroutine: Coroutine[object, object, None]) -> None:
        """Run `coroutine` as a task."""
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log.error("Background task failed", exc_info=error)
