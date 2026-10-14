# -*- coding: utf-8 -*-
"""Putting a message on the wire.

This is the piece that reaches real people, so what it refuses to do
matters more than what it does:

  * it does not ask the same CSP twice while they are still being waited on;
  * it does not count an undelivered message as having been asked;
  * it does not silently skip someone it cannot reach;
  * and the Communication Agent does not message a large group without
    somebody saying so.
"""

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.models.messaging import (
    EMAIL, PURPOSE_DATA_REQUEST, WHATSAPP, MessageChannel, MessageTemplate,
)
from app.services import message_sender as sender
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
            "TRUNCATE data_requests, message_campaigns, message_channels, "
            "message_templates, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        with workspace(DEFAULT_WORKSPACE_ID):
            session.add(MessageChannel(
                name="Email", kind=EMAIL, provider="smtp", is_default=True))
            session.add(MessageTemplate(
                purpose=PURPOSE_DATA_REQUEST, name="Ask", channel_kind=EMAIL,
                subject="Please confirm your details",
                body="Namaste {name}, please open {link}. Needed: {fields}."))
            session.commit()
            yield session


@pytest.fixture(autouse=True)
def _email_allowed_for_these_tests(monkeypatch):
    """These tests exercise the sending machinery through an email channel.
    In production email is OFF for CSP requests (tracker No. 53) — see
    test_by_default_a_csp_is_not_asked_by_email."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "csp_data_requests_by_email", True)


@pytest.fixture(autouse=True)
def _reachable(monkeypatch):
    """A link nobody can open is refused, and the default is localhost.

    These tests are about what the sender does, not about that guard, so
    they run against a reachable address. The guard has its own tests at
    the bottom of this file, which override this.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_app_url",
                        "https://csp.example.test")


@pytest.fixture
def sent(monkeypatch):
    """Capture instead of actually emailing anybody."""
    outbox = []

    def capture(to, subject, html, plain):
        outbox.append({"to": to, "subject": subject, "body": plain})
        return True

    from app.services import email_service
    monkeypatch.setattr(email_service, "_send_via_smtp", capture)
    return outbox


def _csp(session, csp_id="C1", **fields):
    defaults = {"name": "Test Csp", "origin": "new",
                "mobile": "9812345670", "email": "csp@example.com"}
    defaults.update(fields)
    record = CSPRecord(csp_id=csp_id, csp_code=csp_id, **defaults)
    session.add(record)
    session.commit()
    return record


# ---- filling the wording -------------------------------------------------

async def test_the_three_placeholders_are_filled():
    out = sender.render("Hi {name}, open {link}. Needed: {fields}.",
                        name="Nitasha", link="https://x/abc",
                        fields=["gender", "address"])
    assert "Hi Nitasha" in out
    assert "https://x/abc" in out
    assert "Gender, Address" in out


async def test_an_unrecognised_brace_is_left_alone():
    """A stray brace in a customer's wording must not blank their message."""
    out = sender.render("Hello {name}, re {invoice_no}",
                        name="X", link="L", fields=[])
    assert "{invoice_no}" in out


# ---- where to reach somebody --------------------------------------------

async def test_whatsapp_prefers_the_mobile(db):
    record = _csp(db)
    assert sender.address_for(record, WHATSAPP)[0] == "919812345670"


async def test_it_falls_back_to_email_when_there_is_no_mobile(db):
    record = _csp(db, mobile="")
    to, via = sender.address_for(record, WHATSAPP)
    assert to == "csp@example.com" and via == "email"


async def test_somebody_unreachable_is_reported_not_guessed(db):
    record = _csp(db, mobile="", email="")
    assert sender.address_for(record, EMAIL) == ("", "")


# ---- sending -------------------------------------------------------------

async def test_a_csp_is_asked_and_the_link_is_in_the_message(db, sent):
    record = _csp(db, name="Nitasha")
    result = sender.ask_for_details(db, record)

    assert result["sent"] is True
    assert len(sent) == 1
    assert sent[0]["to"] == "csp@example.com"
    assert "Namaste Nitasha" in sent[0]["body"]
    assert "/csp/details/" in sent[0]["body"]


async def test_the_request_records_where_it_went(db, sent):
    record = _csp(db)
    sender.ask_for_details(db, record)

    request = db.execute(select(DataRequest)).scalars().one()
    assert request.sent_to == "csp@example.com"
    assert request.sent_via == "email"
    assert request.delivery_error is None


async def test_nobody_is_asked_twice_while_being_waited_on(db, sent):
    record = _csp(db)
    sender.ask_for_details(db, record)
    second = sender.ask_for_details(db, record)

    assert second["sent"] is False
    assert "already asked" in second["reason"]
    assert len(sent) == 1, "they were messaged twice"


async def test_a_csp_missing_nothing_is_not_asked(db, sent, tmp_path):
    # Every field the CSP owns, including the branch name and code — and,
    # since 11 Oct 2026 (tracker No. 53), the bank/organisation details too,
    # because the CSP is now asked for those when INFO cannot fill them.
    # The photo is a real file: a path with nothing behind it is no photo
    # (No. 99).
    photo = tmp_path / "p.png"
    photo.write_bytes(b"photo")
    record = _csp(db, gender="Female", address="A", district="D", state="S",
                  branch_name="B", branch_code="BR01", photo_url=str(photo),
                  ao="AO", dc="DC", dc_email="dc@eko.co.in",
                  dc_contact="9000000000", lho="Patna", rm_name="RM",
                  asm_name="ASM", asm_email="asm@eko.co.in",
                  asm_contact="9000000001", rbo_name="RBO")
    result = sender.ask_for_details(db, record)
    assert result["sent"] is False
    assert "nothing is missing" in result["reason"]
    assert sent == []


async def test_someone_unreachable_is_said_so_not_skipped(db, sent):
    record = _csp(db, mobile="", email="")
    result = sender.ask_for_details(db, record)
    assert result["sent"] is False
    assert "no usable mobile" in result["reason"]
    assert sent == []


# ---- a failed send is not an ask ----------------------------------------

async def test_a_failed_send_does_not_leave_a_dead_link(db, monkeypatch):
    """Otherwise the CSP is 'asked' and the next attempt is refused."""
    from app.services import email_service
    monkeypatch.setattr(email_service, "_send_via_smtp",
                        lambda *a, **k: False)

    record = _csp(db)
    result = sender.ask_for_details(db, record)
    assert result["sent"] is False

    open_requests = db.execute(
        select(DataRequest).where(DataRequest.status == "open")
    ).scalars().all()
    assert open_requests == [], "an undelivered ask was left looking sent"


async def test_the_failure_reason_is_kept_on_the_channel(db, monkeypatch):
    from app.services import email_service
    monkeypatch.setattr(email_service, "_send_via_smtp",
                        lambda *a, **k: False)
    sender.ask_for_details(db, _csp(db))

    channel = db.execute(select(MessageChannel)).scalars().one()
    assert channel.last_error


# ---- a channel with no sender says so -----------------------------------

async def test_free_text_whatsapp_is_refused_plainly(db):
    """Changed 12 Oct 2026 (No. 78): WhatsApp now sends, but only as a
    Meta-approved template through whatsapp_platform — never free text."""
    channel = MessageChannel(name="WA", kind=WHATSAPP,
                             provider="eko_wabs")
    sent, why = sender.send_via(channel, "919812345670", "s", "b")
    assert sent is False
    assert "whatsapp_platform" in why


# ---- nothing configured --------------------------------------------------

async def test_no_channel_is_an_explicit_refusal(db):
    db.execute(text("DELETE FROM message_channels"))
    db.commit()
    with pytest.raises(sender.NoChannel):
        sender.choose_channel(db)


async def test_no_template_is_an_explicit_refusal(db):
    db.execute(text("DELETE FROM message_templates"))
    db.commit()
    with pytest.raises(sender.NoTemplate):
        sender.choose_template(db)


# ---- the agent does not message a crowd on its own ----------------------

async def test_a_large_group_is_proposed_not_sent(db, sent):
    from app.services import agents
    from app.services.agent_runner import Outcome

    for n in range(agents.BULK_THRESHOLD + 2):
        _csp(db, csp_id=f"BULK{n}")

    outcome = agents.communication_agent(db)
    assert isinstance(outcome, Outcome)
    assert outcome.detail["sent"] == 0
    assert sent == [], "a crowd was messaged without anyone approving it"
    assert any(f.proposal for f in outcome.findings)


async def test_a_small_group_is_simply_asked(db, sent):
    for n in range(3):
        _csp(db, csp_id=f"SMALL{n}")

    from app.services import agents
    outcome = agents.communication_agent(db)
    assert outcome.detail["sent"] == 3
    assert len(sent) == 3


# ---- a link nobody can open is not sent ---------------------------------

@pytest.mark.parametrize("link,sendable", [
    ("http://localhost:3000/csp/details/x", False),
    ("http://127.0.0.1:3000/csp/details/x", False),
    ("http://0.0.0.0:3000/x", False),
    ("https://csp.eko.co.in/csp/details/x", True),
    ("https://10.0.0.5/x", True),
    ("", False),
])
async def test_only_a_reachable_link_may_be_sent(link, sendable):
    assert sender.link_is_reachable(link) is sendable


async def test_a_localhost_link_is_refused_rather_than_emailed(db, sent,
                                                               monkeypatch):
    """Worse than not sending: an official-looking message they cannot act
    on, and the request marked as asked."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "public_app_url",
                        "http://localhost:3000")

    result = sender.ask_for_details(db, _csp(db))
    assert result["sent"] is False
    assert "nobody outside this machine" in result["reason"]
    assert "/csp/details/" not in result["reason"], "the private link leaked"
    assert sent == [], "a dead link was emailed to somebody"


async def test_the_request_is_closed_so_the_next_try_is_fresh(db, monkeypatch):
    """Otherwise they are 'asked' and can never be asked again."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "public_app_url",
                        "http://localhost:3000")

    sender.ask_for_details(db, _csp(db))
    assert db.execute(
        select(DataRequest).where(DataRequest.status == "open")
    ).scalars().all() == []


async def test_a_real_address_sends_normally(db, sent, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "public_app_url",
                        "https://csp.eko.co.in")

    result = sender.ask_for_details(db, _csp(db))
    assert result["sent"] is True
    assert "https://csp.eko.co.in/csp/details/" in sent[0]["body"]



def test_by_default_a_csp_is_not_asked_by_email(db, monkeypatch):
    """Tracker No. 53: CSPs wait for WhatsApp rather than being emailed."""
    from app.config import get_settings
    from app.models.csp_record import CSPRecord
    from app.services import message_sender

    monkeypatch.setattr(get_settings(), "csp_data_requests_by_email", False)
    record = CSPRecord(csp_id="1A-WAIT-1", name="Waiting", origin="new",
                       email="csp@example.com", mobile="")
    db.add(record)
    db.commit()
    result = message_sender.ask_for_details(db, record)
    assert result["sent"] is False
    assert "WhatsApp" in result["reason"]
