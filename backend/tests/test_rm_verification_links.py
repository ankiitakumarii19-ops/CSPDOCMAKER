"""RM portal → Messages (No. 192): an RM sends a CSP the verification link as
many times as needed; each send is a new link valid 3 days; the earlier one
closes only once the new one reached the CSP. WhatsApp is a stand-in."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.data_request import CANCELLED, OPEN, DataRequest
from app.services import message_sender
from tests.test_verify_old_csps import _old, db  # noqa: F401  (fixture)


def _rows(s):
    return s.execute(select(DataRequest).order_by(DataRequest.created_at)).scalars().all()


def test_every_send_is_a_new_3_day_link(db):
    s = db.session
    _old(s, "1A970001")
    s.commit()
    from app.models.csp_record import CSPRecord
    csp = s.execute(select(CSPRecord).where(CSPRecord.csp_id == "1A970001")).scalar_one()
    for _ in range(3):
        out = message_sender.ask_for_details(s, csp, verify=True, manual=True, fresh=True)
        assert out["sent"] is True, out
    rows = _rows(s)
    assert len(rows) == 3 and len(db.sent) == 3
    assert [r.status for r in rows] == [CANCELLED, CANCELLED, OPEN]
    assert len({r.token_hash for r in rows}) == 3, "a new link each time"
    left = rows[-1].expires_at - datetime.now(timezone.utc)
    assert timedelta(days=3) - timedelta(minutes=5) < left <= timedelta(days=3)


def test_without_fresh_an_open_link_is_not_sent_twice(db):
    s = db.session
    _old(s, "1A970002")
    s.commit()
    from app.models.csp_record import CSPRecord
    csp = s.execute(select(CSPRecord).where(CSPRecord.csp_id == "1A970002")).scalar_one()
    assert message_sender.ask_for_details(s, csp, verify=True)["sent"] is True
    again = message_sender.ask_for_details(s, csp, verify=True)
    assert again["sent"] is False and "already asked" in again["reason"]


def test_a_failed_new_link_keeps_the_old_one_working(db):
    from app.services import whatsapp_platform
    s = db.session
    _old(s, "1A970003")
    s.commit()
    from app.models.csp_record import CSPRecord
    csp = s.execute(select(CSPRecord).where(CSPRecord.csp_id == "1A970003")).scalar_one()
    assert message_sender.ask_for_details(s, csp, verify=True, manual=True,
                                          fresh=True)["sent"] is True
    db.status = whatsapp_platform.FAILED
    out = message_sender.ask_for_details(s, csp, verify=True, manual=True, fresh=True)
    assert out["sent"] is False
    first, second = _rows(s)
    assert first.status == OPEN, "the link they already have still works"
    assert second.status == CANCELLED and second.delivery_error
