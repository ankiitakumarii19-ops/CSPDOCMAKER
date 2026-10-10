# -*- coding: utf-8 -*-
"""An RM can hand an existing CSP to the automation.

Baseline CSPs are kept out of automatic processing so a first sync cannot
email an entire organisation at once. That protection is against doing it
in BULK BY ACCIDENT, not against doing it deliberately — so an RM who has
searched for one CSP and chosen it can enrol that one, and the automation
finishes it exactly as it would a new CSP.

The two things this pins hardest:

  * a baseline CSP nobody enrolled is still never touched;
  * enrolling needs nothing else from the RM. A certificate carries the
    day it is made, so an existing CSP does not have to be asked when they
    were onboarded before anything can be issued.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.workspace_context import workspace
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"))
    yield engine
    engine.dispose()


@pytest.fixture
def db(_engine):
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE data_requests, rm_alerts, stored_documents, "
            "processing_jobs, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        with workspace(DEFAULT_WORKSPACE_ID):
            yield session


def _csp(session, csp_id="OLD1", origin="baseline", **fields):
    record = CSPRecord(csp_id=csp_id, csp_code=csp_id, name="Old Csp",
                       origin=origin, **fields)
    session.add(record)
    session.commit()
    return record


def _pending(session):
    """Exactly what the worker selects."""
    from sqlalchemy import or_

    return session.execute(
        select(CSPRecord).where(
            or_(CSPRecord.origin == "new",
                CSPRecord.auto_enrolled_at.is_not(None)),
            CSPRecord.new_csp_processed_at.is_(None),
        )
    ).scalars().all()


# ---- what the automation picks up ---------------------------------------

async def test_a_baseline_csp_is_left_alone(db):
    """The protection that stops a first sync emailing everybody."""
    _csp(db, "OLD1")
    assert _pending(db) == []


async def test_a_new_csp_is_picked_up_without_being_enrolled(db):
    _csp(db, "NEW1", origin="new")
    assert [c.csp_id for c in _pending(db)] == ["NEW1"]


async def test_an_enrolled_baseline_csp_is_picked_up(db):
    record = _csp(db, "OLD1")
    record.auto_enrolled_at = datetime.now(timezone.utc)
    db.commit()
    assert [c.csp_id for c in _pending(db)] == ["OLD1"]


async def test_enrolling_does_not_rewrite_history(db):
    """origin records whether they predated the system. That stays true."""
    record = _csp(db, "OLD1")
    record.auto_enrolled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    assert record.origin == "baseline"


async def test_an_already_issued_csp_is_not_picked_up_again(db):
    record = _csp(db, "OLD1")
    record.auto_enrolled_at = datetime.now(timezone.utc)
    record.new_csp_processed_at = datetime.now(timezone.utc)
    db.commit()
    assert _pending(db) == []


# ---- the date, which no longer has to be asked for ----------------------

async def test_an_existing_csp_is_dated_the_day_it_is_made(db):
    """So enrolling one needs nothing more from the RM than the decision."""
    from app.services import csp_mapping

    assert csp_mapping.effective_certificate_date(
        _csp(db, "OLD1")) == date.today()


async def test_a_new_csp_is_dated_the_same_way(db):
    from app.services import csp_mapping

    assert csp_mapping.effective_certificate_date(
        _csp(db, "NEW1", origin="new")) == date.today()


async def test_a_saved_date_is_not_used(db):
    """Tracker No. 56: always the day the document is made."""
    from app.services import csp_mapping

    record = _csp(db, "OLD1", certificate_date=date(2026, 3, 14))
    assert csp_mapping.effective_certificate_date(record) == date.today()


# ---- through the API, as an RM would -----------------------------------

def _rm_auth() -> dict:
    from app.services import jwt_service

    token = jwt_service.create_access_token({
        "sub": "rm@eko.co.in", "email": "rm@eko.co.in", "role": "rm",
        "name": "An RM",
    })
    return {"Authorization": f"Bearer {token}"}


async def test_an_rm_can_enrol_a_csp_they_own(client, db):
    _csp(db, "OLD1", rm_email="rm@eko.co.in", rm_resolution="sheet")

    response = await client.post(
        "/api/csps/OLD1/auto-issue",
        headers=_rm_auth(), json={"certificate_date": "2026-03-14"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enrolled"] is True
    assert body["already_enrolled"] is False

    db.expire_all()
    record = db.execute(
        select(CSPRecord).where(CSPRecord.csp_id == "OLD1")
    ).scalars().one()
    assert record.auto_enrolled_at is not None
    assert record.auto_enrolled_by == "rm@eko.co.in"
    assert record.certificate_date == date(2026, 3, 14)


async def test_enrolling_says_plainly_what_is_still_missing(client, db):
    """Better now than discovered three minutes later."""
    _csp(db, "OLD1", rm_email="rm@eko.co.in", rm_resolution="sheet")

    body = (await client.post(
        "/api/csps/OLD1/auto-issue", headers=_rm_auth(), json={},
    )).json()
    assert body["has_missing_data"] is True
    assert body["missing_fields"]
    assert "as soon as the missing details arrive" in body["message"]


async def test_enrolling_twice_is_harmless(client, db):
    _csp(db, "OLD1", rm_email="rm@eko.co.in", rm_resolution="sheet")
    await client.post("/api/csps/OLD1/auto-issue", headers=_rm_auth(),
                      json={})
    second = (await client.post("/api/csps/OLD1/auto-issue",
                                headers=_rm_auth(), json={})).json()
    assert second["already_enrolled"] is True


async def test_an_already_issued_csp_is_refused(client, db):
    record = _csp(db, "OLD1", rm_email="rm@eko.co.in", rm_resolution="sheet")
    record.new_csp_processed_at = datetime.now(timezone.utc)
    db.commit()

    response = await client.post("/api/csps/OLD1/auto-issue",
                                 headers=_rm_auth(), json={})
    assert response.status_code == 409
    assert "already been issued" in response.json()["detail"]


async def test_an_rm_cannot_enrol_another_rms_csp(client, db):
    """Reported as missing, so IDs cannot be probed."""
    _csp(db, "OLD1", rm_email="someone.else@eko.co.in", rm_resolution="sheet")

    response = await client.post("/api/csps/OLD1/auto-issue",
                                 headers=_rm_auth(), json={})
    assert response.status_code == 404


@pytest.mark.parametrize("role", ["admin", "super_admin"])
async def test_a_monitor_role_cannot_enrol(client, db, role):
    """Issuing documents is the RM's job, not an Admin's."""
    from app.services import jwt_service

    _csp(db, "OLD1")
    token = jwt_service.create_access_token({
        "sub": f"{role}@eko.co.in", "role": role, "name": role})
    response = await client.post(
        "/api/csps/OLD1/auto-issue",
        headers={"Authorization": f"Bearer {token}"}, json={})
    assert response.status_code == 403
