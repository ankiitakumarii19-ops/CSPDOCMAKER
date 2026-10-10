"""The link a CSP fills their details through.

The link is the entire credential — there is no account behind it — so what
it is worth when it leaks is the thing these pin down. A link must not be
guessable, must not be recoverable from the database, must reach exactly one
CSP, must write only the fields it was issued for, and must stop working.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.data_request import ANSWERED, CANCELLED, EXPIRED, OPEN
from app.services import data_request_service as svc
from app.services import field_ownership as fo

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="module")
def _engine(migrated_db):
    """One engine for the module — building one per test cost two minutes."""
    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(_engine):
    """A synchronous session — the workers that issue links use one."""
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE data_requests, rm_alerts, csp_records "
            "RESTART IDENTITY CASCADE"))
        session.commit()
        yield session


@pytest.fixture
def csp(db_session):
    record = CSPRecord(csp_id="1A900001", name="Test CSP", origin="new")
    db_session.add(record)
    db_session.flush()
    return record


# ---- what the link is worth --------------------------------------------

async def test_the_token_is_never_stored(db_session, csp):
    """A leaked database must not hand out working links."""
    request, token = svc.create(db_session, csp.csp_id, ["gender"])
    assert token not in str(request.token_hash)
    assert request.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert len(request.token_hash) == 64


async def test_two_links_are_never_the_same(db_session, csp):
    tokens = {svc.create(db_session, csp.csp_id, ["gender"])[1]
              for _ in range(20)}
    assert len(tokens) == 20


async def test_the_token_is_not_derived_from_the_csp_code(db_session, csp):
    """The code is printed on every document; it must not be a key."""
    _, token = svc.create(db_session, csp.csp_id, ["gender"])
    assert csp.csp_id not in token
    assert len(token) >= 40


async def test_a_wrong_token_resolves_to_nothing(db_session, csp):
    svc.create(db_session, csp.csp_id, ["gender"])
    assert svc.resolve(db_session, "not-a-real-token") is None
    assert svc.resolve(db_session, "") is None


# ---- it reaches exactly one CSP, and only its own fields ----------------

async def test_a_link_only_covers_the_fields_it_was_issued_for(db_session, csp):
    request, _ = svc.create(db_session, csp.csp_id, ["gender", "address"])
    with pytest.raises(ValueError, match="not issued for"):
        svc.answer(db_session, request, {"gender": "Female", "ao": "Panchkula"})


async def test_an_unanswerable_field_is_refused_at_issue(db_session, csp):
    """A box that writes nowhere must never be rendered."""
    with pytest.raises(ValueError, match="not a field anyone owns"):
        svc.create(db_session, csp.csp_id, ["certificate_date"])


async def test_a_request_for_nothing_is_refused(db_session, csp):
    with pytest.raises(ValueError):
        svc.create(db_session, csp.csp_id, [])


async def test_only_the_csps_own_details_are_asked_of_them(db_session):
    """The hierarchy is the RM's to supply; a CSP would invent an RBO."""
    blank = CSPRecord(csp_id="1A900002", name="", origin="new")
    asked = svc.fields_to_ask(blank)
    assert set(asked) <= set(fo.CSP_OWNED)
    assert "rbo_name" not in asked and "ao" not in asked


# ---- it answers once, and expires ---------------------------------------

async def test_a_link_works_once(db_session, csp):
    request, token = svc.create(db_session, csp.csp_id, ["gender"])
    assert svc.resolve(db_session, token) is not None

    svc.answer(db_session, request, {"gender": "Female"})
    assert request.status == ANSWERED
    assert svc.resolve(db_session, token) is None, "an answered link still works"


async def test_an_expired_link_is_refused_and_marked(db_session, csp):
    request, token = svc.create(db_session, csp.csp_id, ["gender"])
    request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.flush()

    assert svc.resolve(db_session, token) is None
    assert request.status == EXPIRED


async def test_a_cancelled_link_stops_working(db_session, csp):
    _, token = svc.create(db_session, csp.csp_id, ["gender"])
    assert svc.cancel(db_session, csp.csp_id) == 1
    assert svc.resolve(db_session, token) is None


async def test_cancelling_is_safe_when_there_is_nothing_open(db_session, csp):
    assert svc.cancel(db_session, csp.csp_id) == 0


# ---- what gets recorded --------------------------------------------------

async def test_a_blank_answer_is_not_treated_as_a_value(db_session, csp):
    """Leaving a box empty must not clear anything."""
    request, _ = svc.create(db_session, csp.csp_id, ["gender", "address"])
    accepted = svc.answer(db_session, request,
                          {"gender": "Female", "address": "   "})
    assert accepted == {"gender": "Female"}


async def test_what_came_back_is_kept(db_session, csp):
    """A wrong value must be traceable to the submission that introduced it."""
    request, _ = svc.create(db_session, csp.csp_id, ["gender"])
    svc.answer(db_session, request, {"gender": "Female"})
    assert request.answered_values == {"gender": "Female"}
    assert request.answered_at is not None


# ---- not re-asking every minute -----------------------------------------

async def test_an_open_request_is_reused_not_replaced(db_session, csp):
    """The worker runs every few minutes; it must not send a link each pass."""
    request, _ = svc.create(db_session, csp.csp_id, ["gender"])
    assert svc.open_request_for(db_session, csp.csp_id).id == request.id


async def test_an_expired_open_request_does_not_block_a_new_one(db_session, csp):
    request, _ = svc.create(db_session, csp.csp_id, ["gender"])
    request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.flush()

    assert svc.open_request_for(db_session, csp.csp_id) is None
    assert request.status == EXPIRED


async def test_the_link_carries_the_token(db_session, csp):
    _, token = svc.create(db_session, csp.csp_id, ["gender"])
    assert svc.link_for(token).endswith(f"/csp/details/{token}")
