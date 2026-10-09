# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging

from agent.core.tasks import TaskSet
from conftest import run


def test_spawned_task_runs_to_completion():
    done = []

    async def work():
        await asyncio.sleep(0)
        done.append(True)

    async def scenario():
        TaskSet().spawn(work())  # nothing else holds the task
        await asyncio.sleep(0.05)

    run(scenario())
    assert done == [True]


def test_failing_task_is_logged(caplog):
    async def fail():
        raise ValueError("boom")

    async def scenario():
        TaskSet().spawn(fail())
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.ERROR, logger="agent.core.tasks"):
        run(scenario())
    [record] = caplog.records
    assert record.message == "Background task failed"
    assert isinstance(record.exc_info[1], ValueError)
