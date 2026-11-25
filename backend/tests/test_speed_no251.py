"""No. 251: the site answers quickly, and a slow call no longer stops it.

1. off_loop runs blocking work beside the server: the result and errors
   come back unchanged, the workspace travels with it, Google calls take
   turns, and - the point of it - other requests keep being answered.
2. The photo lookup reads the photo folder once, not once per CSP, and
   finds exactly what glob("<code>.*") found.
3. has_everything() gives exactly the answer check_missing_data() gives.
"""

import asyncio
import glob
import os
import threading
import time
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import csp_photo_service, csp_photo_store, off_loop
from app.services.missing_data_service import (
    check_missing_data, has_everything, required_by_document,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---- 1. off_loop -----------------------------------------------------------

async def test_the_result_comes_back():
    assert await off_loop.run(lambda a, b=0: a + b, 2, b=3) == 5


async def test_an_error_comes_back_unchanged():
    def boom():
        raise ValueError("sheet said no")
    with pytest.raises(ValueError, match="sheet said no"):
        await off_loop.run(boom)


async def test_it_runs_on_another_thread():
    here = threading.get_ident()
    there = await off_loop.run(threading.get_ident)
    assert there != here


async def test_the_workspace_travels_with_the_call():
    from app.workspace_context import current_workspace_id, workspace
    ws = uuid.uuid4()
    with workspace(ws):
        seen = await off_loop.run(current_workspace_id)
    assert seen == ws


async def test_the_server_keeps_answering_while_a_slow_call_runs():
    """The bug: a 1-second email send stopped every other request for that
    second. Beside the server, others are answered meanwhile."""
    ticks = []

    async def other_people():
        for _ in range(20):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    started = time.monotonic()
    await asyncio.gather(off_loop.run(time.sleep, 0.5), other_people())
    during = [t for t in ticks if t - started < 0.45]
    assert len(during) >= 10, f"only {len(during)} answers while it ran"


async def test_google_calls_take_turns():
    """The shared Sheets client is not safe for two threads at once."""
    inside, most = [0], [0]
    guard = threading.Lock()

    def call():
        with guard:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        time.sleep(0.05)
        with guard:
            inside[0] -= 1

    await asyncio.gather(*(off_loop.google(call) for _ in range(4)))
    assert most[0] == 1


async def test_other_slow_calls_run_side_by_side():
    started = time.monotonic()
    await asyncio.gather(*(off_loop.run(time.sleep, 0.3) for _ in range(4)))
    assert time.monotonic() - started < 1.0


# ---- 2. the photo folder ---------------------------------------------------

NAMES = ["TC01.png", "TC01.white.png", "TC012.png", "A.B.jpg", "A.png",
         ".TC01.png", "TC01-x.png", "ZZ.white.png"]
CODES = ["TC01", "TC012", "A", "A.B", "ZZ", "NOPE", "TC0"]


def _old(path):
    """Make the folder look settled, so its listing may be kept."""
    past = time.time() - 60
    os.utime(path, (past, past))


@pytest.fixture
def photos(tmp_path, monkeypatch):
    for name in NAMES:
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.setattr(csp_photo_service, "photo_directory",
                        lambda: str(tmp_path))
    csp_photo_store._listing.clear()
    return tmp_path


def _by_glob(directory, code):
    for path in sorted(glob.glob(os.path.join(directory, f"{code}.*"))):
        if ".white." not in os.path.basename(path):
            return path
    return None


async def test_the_same_photo_as_glob_found(photos):
    _old(photos)
    for code in CODES:
        found = csp_photo_store.original_path(SimpleNamespace(
            csp_id=code, photo_url=""))
        assert found == _by_glob(str(photos), code), code


async def test_the_folder_is_listed_once_for_many_csps(photos, monkeypatch):
    _old(photos)
    listed = []
    real = os.scandir
    monkeypatch.setattr(os, "scandir",
                        lambda p: listed.append(p) or real(p))
    for _ in range(50):
        for code in CODES:
            csp_photo_store.original_path(SimpleNamespace(
                csp_id=code, photo_url=""))
    assert len(listed) == 1


async def test_a_new_photo_is_seen(photos):
    _old(photos)
    csp = SimpleNamespace(csp_id="NEW1", photo_url="")
    assert csp_photo_store.original_path(csp) is None
    (photos / "NEW1.jpg").write_bytes(b"x")      # changes the folder's time
    assert csp_photo_store.original_path(csp) == str(photos / "NEW1.jpg")


async def test_a_removed_photo_is_gone(photos):
    _old(photos)
    csp = SimpleNamespace(csp_id="TC012", photo_url="")
    assert csp_photo_store.original_path(csp) == str(photos / "TC012.png")
    os.remove(photos / "TC012.png")
    assert csp_photo_store.original_path(csp) is None


async def test_a_missing_folder_is_no_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(csp_photo_service, "photo_directory",
                        lambda: str(tmp_path / "not-there"))
    assert csp_photo_store.original_path(
        SimpleNamespace(csp_id="TC01", photo_url="")) is None


# ---- 3. "details complete", fast and the same --------------------------------

def _records(photo_path):
    complete = dict(
        name="Complete Csp", email="csp@example.com",
        mobile="9876543210", address="1 Test Street", district="Testdistrict",
        state="Teststate", lho="Patna", ao="Test Ao", rbo_name="Test Rbo",
        branch_name="Main", branch_code="00001",
        asm_name="Test Asm", asm_email="asm@eko.co.in",
        asm_contact="9000000000", photo_url=photo_path, rm_name="Rm",
        certificate_date=date(2026, 1, 5),
    )
    out = [
        CSPRecord(csp_id="10000001", csp_code="10000001", **complete),
        CSPRecord(csp_id="100000012", csp_code="100000012", **complete),
        CSPRecord(csp_id="10000002", csp_code="10000002", name="Sparse"),
        CSPRecord(csp_id="X", csp_code=None, name="No code"),
    ]
    for field in complete:   # each field missing on its own
        if field == "name":  # the full report cannot be built without one
            continue
        values = dict(complete, **{field: None})
        out.append(CSPRecord(csp_id=f"1000{len(out):04d}",
                             csp_code=f"1000{len(out):04d}", **values))
    out.append(CSPRecord(csp_id="10009999", csp_code="10009999",
                         **dict(complete, photo_url="C:/nowhere/p.jpg")))
    return out


async def test_has_everything_agrees_with_check_missing_data(tmp_path,
                                                            monkeypatch):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    monkeypatch.setattr(csp_photo_service, "photo_directory",
                        lambda: str(tmp_path / "empty"))
    every = list(DocumentType)
    required = required_by_document(every)
    answers = set()
    for record in _records(str(photo)):
        expected = not check_missing_data(record, every).has_missing_data
        assert has_everything(record, every) == expected, record.csp_id
        assert has_everything(record, every, required) == expected
        answers.add(expected)
    assert answers == {True, False}, "the cases should include both answers"
