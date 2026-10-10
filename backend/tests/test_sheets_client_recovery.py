"""The Google Sheets client must not be reused after it fails.

The API client is httplib2-based and holds a live socket. The logs show the
remote end resetting connections regularly; that leaves a broken socket
inside the cached client, and every later call reuses it. The worker
segfaulted four times, each one during a sheet read.

The rule pinned here: any failure throws the cached client away, so the next
call builds a fresh one.
"""

import pytest

from app.services import csp_gsheet_service as csp_sheets
from app.services import google_sheets_service as auth_sheets

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _Boom(Exception):
    """Stands in for a ConnectionReset from the socket layer."""


@pytest.fixture(autouse=True)
def _clean_clients():
    csp_sheets.reset_sheets_service()
    auth_sheets.reset_sheets_service()
    yield
    csp_sheets.reset_sheets_service()
    auth_sheets.reset_sheets_service()


# ---- the CSP sheet -----------------------------------------------------

async def test_a_failed_csp_read_discards_the_client(monkeypatch):
    csp_sheets._csp_sheets_service = object()      # a "live" cached client

    def explode():
        raise _Boom("connection reset")

    monkeypatch.setattr(csp_sheets, "_get_sheets_service", explode)
    with pytest.raises(RuntimeError):
        csp_sheets.read_csp_sheet()

    assert csp_sheets._csp_sheets_service is None, (
        "the broken client was kept and would be reused")


async def test_a_failed_info_read_discards_the_client(monkeypatch):
    csp_sheets._csp_sheets_service = object()

    def explode():
        raise _Boom("connection reset")

    monkeypatch.setattr(csp_sheets, "_get_sheets_service", explode)
    # The INFO tab is enrichment: it swallows the error and returns nothing.
    assert csp_sheets.read_info_sheet() == []
    assert csp_sheets._csp_sheets_service is None


async def test_the_next_read_builds_a_fresh_client(monkeypatch):
    """Recovery, not just cleanup: the call after a failure must work."""
    built = []

    class _Values:
        def get(self, **kwargs):
            return self

        def execute(self):
            return {"values": [["CSP Code"], ["1A000001"]]}

    class _Service:
        def spreadsheets(self):
            return self

        def values(self):
            return _Values()

    def build():
        built.append(1)
        if len(built) == 1:
            raise _Boom("connection reset")
        return _Service()

    monkeypatch.setattr(csp_sheets, "_get_sheets_service", build)

    with pytest.raises(RuntimeError):
        csp_sheets.read_csp_sheet()
    assert csp_sheets._csp_sheets_service is None

    csp_sheets.read_csp_sheet()          # must not raise
    assert len(built) == 2, "the client was not rebuilt"


# ---- the authorization sheet -------------------------------------------

async def test_a_failed_auth_read_discards_the_client(monkeypatch):
    auth_sheets._sheets_service = object()

    def explode():
        raise _Boom("connection reset")

    monkeypatch.setattr(auth_sheets, "_get_sheets_service", explode)
    # Unlike the INFO tab, the authorization sheet is not optional: it
    # raises so the sync retries rather than quietly seeing no one.
    with pytest.raises(RuntimeError):
        auth_sheets._read_sheet_tab("RMs")
    assert auth_sheets._sheets_service is None


async def test_resetting_an_empty_cache_is_harmless():
    csp_sheets.reset_sheets_service()
    csp_sheets.reset_sheets_service()
    assert csp_sheets._csp_sheets_service is None


# ---- periodic tasks must not pile up -----------------------------------

async def test_every_periodic_task_expires():
    """A stale sync achieves nothing the next tick will not do.

    Without this a worker outage left 255 queued syncs, and draining them
    hammered Google Sheets into the resets that caused the crashes.
    """
    from app.celery_app import celery_app

    for name, cfg in celery_app.conf.beat_schedule.items():
        expires = cfg.get("options", {}).get("expires")
        assert expires, f"{name} has no expires and will accumulate"
        assert expires < cfg["schedule"], (
            f"{name} expires after its own interval, so copies still overlap")
