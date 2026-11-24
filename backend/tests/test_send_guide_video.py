"""Who gets the form guide video (No. 209): KOs sent a form link who have not
submitted it and have no documents yet — never on hold, never twice."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.models.email_message import EmailMessage
from app.models.whatsapp_message import WhatsAppMessage
from tests.test_field_quality import _engine, qdb  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import send_guide_video as g  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture
def vdb(qdb):
    qdb.execute(text("TRUNCATE whatsapp_messages, email_messages "
                     "RESTART IDENTITY CASCADE"))
    qdb.commit()
    return qdb


def _csp(db, code, *, mobile="9800000001", hold=None, link=True,
         status="open", sent_via="whatsapp"):
    db.add(CSPRecord(csp_id=code, csp_code=code, name=f"Csp {code}",
                     mobile=mobile, send_hold=hold))
    if link:
        db.add(DataRequest(csp_id=code, token_hash=f"t-{code}", fields=["name"],
                           status=status, sent_via=sent_via,
                           expires_at=NOW + timedelta(days=3)))
    db.commit()


def _codes(db):
    chosen, left_out = g.recipients(db)
    return [r.csp_id for r, _, _ in chosen], left_out


def test_only_kos_with_an_unfilled_link_and_no_documents(vdb):
    _csp(vdb, "1A900001")                                  # gets it
    _csp(vdb, "1A9000021")                                 # Sub-KO
    _csp(vdb, "1A900003", status="answered")               # filled the form
    _csp(vdb, "1A900004", hold="not live")                 # on hold
    _csp(vdb, "1A900005", link=False)                      # never sent a link
    _csp(vdb, "1A900006", mobile="")                       # no number
    _csp(vdb, "1A900007", sent_via=None)                   # link never went out
    _csp(vdb, "1A900008", status="expired")                # expired, not filled: gets it
    _csp(vdb, "1A900009")
    vdb.add(EmailMessage(csp_id="1A900009", to_email="d@example.com",
                         kind="documents", subject="s", track_token="t-g9",
                         send_status="sent", sent_at=NOW))  # documents emailed
    vdb.commit()

    codes, left_out = _codes(vdb)
    assert codes == ["1A900001", "1A900008"]
    assert left_out == {"Sub-KO (not a KO)": 1, "already submitted the form": 1,
                        "on hold": 1, "no usable mobile number": 1,
                        "documents already emailed": 1}


def test_nobody_gets_it_twice(vdb):
    _csp(vdb, "1A900011")
    vdb.add(WhatsAppMessage(csp_id="1A900011", phone="919800000001",
                            kind="other", send_status="sent",
                            sent_because="guide_video"))
    vdb.commit()
    codes, left_out = _codes(vdb)
    assert codes == [] and left_out == {"already got this video": 1}


def test_a_failed_earlier_try_is_tried_again(vdb):
    _csp(vdb, "1A900012")
    vdb.add(WhatsAppMessage(csp_id="1A900012", phone="919800000001",
                            kind="other", send_status="failed",
                            sent_because="guide_video"))
    vdb.commit()
    assert _codes(vdb)[0] == ["1A900012"]


def test_template_list_is_read_from_the_platforms_text():
    raw = ('{"name": "other", "status": "APPROVED"}\n'
           '{"name": "%s", "status": "PENDING", "components": [{"text": "x {{1}} y"}]}'
           % g.TEMPLATE_NAME)
    assert [t["status"] for t in g._templates(raw)] == ["APPROVED", "PENDING"]


def test_the_video_fits_whatsapp():
    assert os.path.getsize(g.VIDEO) < 16 * 1024 * 1024
