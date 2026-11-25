"""Slow, blocking work run beside the server instead of inside it (No. 251).

The API is one process with one event loop. A plain (non-async) call made
straight from a request handler - sending an email over SMTP, writing to
Google Sheets, turning documents into PDFs - stops that loop until it
returns, and for those seconds EVERY other request on the site waits: a
CSP opening their verification link, an RM loading the dashboard, someone
signing in. That is the lag people saw.

``await off_loop.run(fn, *args)`` runs ``fn`` on a worker thread and lets
the loop keep answering everyone else meanwhile. The caller still waits for
the result, so what the handler does next is unchanged.

Google: the Sheets clients are built once and shared, and the HTTP library
under them (httplib2) is not safe for two threads at once. ``google=True``
makes Google calls take turns - exactly as they did when they all ran on
the loop - so the only change is that nobody else waits for them.

The request's workspace and trace IDs (context variables) travel with the
call, because ``asyncio.to_thread`` copies the context.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# One Google call at a time in this process (see the module docstring).
GOOGLE_LOCK = threading.Lock()

# A call slower than this is logged, so slow outside services show up in
# the logs with their name instead of as an unexplained wait.
SLOW_SECONDS = 5.0


def _name(fn: Callable) -> str:
    module = getattr(fn, "__module__", "") or ""
    return f"{module.rsplit('.', 1)[-1]}.{getattr(fn, '__qualname__', repr(fn))}"


async def run(fn: Callable[..., T], *args: Any, google: bool = False,
              **kwargs: Any) -> T:
    """Run a blocking ``fn(*args, **kwargs)`` on a worker thread and return
    its result (or raise its exception, unchanged)."""

    def call() -> T:
        started = time.monotonic()
        try:
            if google:
                with GOOGLE_LOCK:
                    return fn(*args, **kwargs)
            return fn(*args, **kwargs)
        finally:
            took = time.monotonic() - started
            if took >= SLOW_SECONDS:
                logger.warning("off_loop: %s took %.1fs (the site kept "
                               "answering others meanwhile)", _name(fn), took)

    return await asyncio.to_thread(call)


async def google(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """``run(fn, ..., google=True)``: a call that uses a Google Sheets client."""
    return await run(fn, *args, google=True, **kwargs)
