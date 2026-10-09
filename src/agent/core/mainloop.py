# SPDX-License-Identifier: GPL-3.0-or-later
"""asyncio on the GLib main loop: installing it, awaiting Gio calls, background tasks.

Everything runs on one thread. Uses GLib/Gio only, never GTK.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import warnings
from collections.abc import Callable, Coroutine

from gi.events import GLibEventLoopPolicy
from gi.repository import Gio, GLib, GObject

_logger = logging.getLogger(__name__)


def install_glib_event_loop() -> None:
    """Make asyncio run on the GLib main loop.

    PyGObject >= 3.55.3 can do this without a policy, but Debian 13 ships
    3.50, which still needs GLibEventLoopPolicy. Python 3.14 deprecates
    policies, hence the warning filter.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # Deprecated, and typeshed's policy type no longer matches; see above.
        asyncio.set_event_loop_policy(GLibEventLoopPolicy())  # pyright: ignore[reportDeprecated, reportArgumentType]


def is_cancelled(error: GLib.Error) -> bool:
    """Whether `error` says a Gio call was cancelled."""
    return error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)


async def gio_call[T](
    start: Callable[..., None],
    finish: Callable[[Gio.AsyncResult], T],
    *args: object,
    cancellable: Gio.Cancellable | None = None,
) -> T:
    """Await the Gio async call `start(*args)`; return `finish(result)`.

    For example `await gio_call(stream.read_bytes_async, stream.read_bytes_finish,
    4096, GLib.PRIORITY_DEFAULT)`.

    The call gets its own Gio.Cancellable, which is cancelled when
    `cancellable` is, or when the awaiting task is cancelled. In that
    case the call is cancelled and waited for before CancelledError is
    re-raised, so it isn't still pending on the stream or process. Its
    outcome is dropped, even if the call finished before the
    cancellation reached it.

    This uses the callback form instead of awaiting PyGObject's Async
    object, because before PyGObject 3.56.3 Async.cancel() rejects the
    argument asyncio passes it, so cancelling the task raises TypeError
    and the await stays pending.
    """
    future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
    call_cancellable = Gio.Cancellable()

    def done(_source: GObject.Object | None, result: Gio.AsyncResult) -> None:
        try:
            future.set_result(finish(result))
        except Exception as error:  # noqa: BLE001  # passed on to the awaiting task
            future.set_exception(error)

    # Gio's Cancellable.connect (not GObject's): runs at once if already
    # cancelled, and then returns 0.
    handler_id = cancellable.connect(call_cancellable.cancel) if cancellable is not None else 0
    try:
        start(*args, call_cancellable, done)
        # asyncio.wait never cancels `future`, and unlike asyncio.shield it
        # doesn't log the CANCELLED error the call ends with.
        try:
            await asyncio.wait([future])
        except asyncio.CancelledError:
            await _cancel_and_wait(future, call_cancellable)
            raise
        return future.result()
    finally:
        if cancellable is not None and handler_id:
            cancellable.disconnect(handler_id)


async def _cancel_and_wait[T](future: asyncio.Future[T], call_cancellable: Gio.Cancellable) -> None:
    """Cancel a pending Gio call and wait for it to end, dropping its outcome."""
    call_cancellable.cancel()
    # A second task.cancel() mustn't cut this wait short: the call would
    # still be pending, and its error never retrieved.
    while not future.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait([future])
    future.exception()  # the outcome is dropped; mark it retrieved


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
            _logger.error("Background task failed", exc_info=error)
