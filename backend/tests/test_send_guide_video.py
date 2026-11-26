"""Who gets the form guide video (No. 209, widened in No. 254): every CSP
that has not received its documents - never an old CSPDATA CSP, never on hold,
never twice."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentFormat, DocumentType
from app.models.source_sheet import SourceSheetState
from app.models.stored_document import StoredDocument
from app.models.data_request import DataRequest
from app.models.email_message import EmailMessage
from app.models.whatsapp_message import WhatsAppMessage
from tests.test_field_quality import _engine, qdb  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import send_guide_video as g  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture
def vdb(qdb):
    qdb.execute(text("TRUNCATE whatsapp_messages, email_messages, "
                     "source_sheet_states RESTART IDENTITY CASCADE"))
    qdb.commit()
    return qdb


def _csp(db, code, *, mobile="9800000001", hold=None, link=True,
         status="open", sent_via="whatsapp", origin="new"):
    db.add(CSPRecord(csp_id=code, csp_code=code, name=f"Csp {code}",
                     mobile=mobile, send_hold=hold, origin=origin))
    if link:
        db.add(DataRequest(csp_id=code, token_hash=f"t-{code}", fields=["name"],
                           status=status, sent_via=sent_via,
                           expires_at=NOW + timedelta(days=3)))
    db.commit()


def _codes(db):
    chosen, left_out = g.recipients(db)
    return [r.csp_id for r, _, _ in chosen], left_out


def _stored(db, code):
    db.add(StoredDocument(csp_id=code, document_type=DocumentType.CSP_ID_CARD,
                          file_format=DocumentFormat.PDF, version=1,
                          filename="id.pdf", content_type="application/pdf",
                          file_data=b"%PDF", file_size=4, checksum="0" * 64))
    db.commit()


def test_every_csp_that_has_not_received_its_documents(vdb):
    _csp(vdb, "1A900001")                                  # gets it
    _csp(vdb, "1A9000021")                                 # Sub-KO: gets it too
    _csp(vdb, "1A900003", status="answered")               # filled the form: gets it
    _csp(vdb, "1A900004", hold="not live")                 # on hold
    _csp(vdb, "1A900005", link=False)                      # no form link: gets it
    _csp(vdb, "1A900006", mobile="")                       # no number
    _csp(vdb, "1A900007", sent_via=None)                   # link never went out: gets it
    _csp(vdb, "1A900008", status="expired")                # expired: gets it
    _csp(vdb, "1A900009")
    vdb.add(EmailMessage(csp_id="1A900009", to_email="d@example.com",
                         kind="documents", subject="s", track_token="t-g9",
                         send_status="sent", sent_at=NOW))  # documents received
    vdb.commit()
    _csp(vdb, "1A900010")
    _stored(vdb, "1A900010")                               # made, not emailed: gets it
    _csp(vdb, "1A900011")
    vdb.add(EmailMessage(csp_id="1A900011", to_email="b@example.com",
                         kind="documents", subject="s", track_token="t-g11",
                         send_status="sent", sent_at=NOW,
                         bounced_at=NOW))                  # bounced: not received, gets it
    vdb.commit()
    _csp(vdb, "1A900013", origin="baseline")               # old CSPDATA CSP
    _csp(vdb, "1A900014", origin="baseline")               # Calling-sheet copy: gets it
    vdb.add(SourceSheetState(csp_code="1A900014", imported_as="baseline"))
    vdb.commit()

    codes, left_out = _codes(vdb)
    assert codes == ["1A900001", "1A9000021", "1A900003", "1A900005",
                     "1A900007", "1A900008", "1A900010", "1A900011", "1A900014"]
    assert left_out == {"on hold": 1, "no usable mobile number": 1,
                        "already received documents": 1,
                        "in CSPDATA before the import (never messaged)": 1}


def test_one_send_per_csp_code(vdb):
    _csp(vdb, "1A900020")
    vdb.add(CSPRecord(csp_id="1a900020 ", csp_code="1a900020 ", name="Same",
                      mobile="9800000002", origin="new"))
    _csp(vdb, "1A900021")
    vdb.add(CSPRecord(csp_id="1A900021-OLD", csp_code="1A900021", name="Same",
                      mobile="9800000003", origin="new"))
    vdb.add(EmailMessage(csp_id="1A900021-OLD", to_email="o@example.com",
                         kind="documents", subject="s", track_token="t-g21",
                         send_status="sent", sent_at=NOW))
    vdb.commit()
    codes, left_out = _codes(vdb)
    assert codes == ["1A900020"]
    assert left_out == {"same CSP code twice (sent once)": 1,
                        "already received documents": 2}


def test_dry_run_breakdown(vdb):
    _csp(vdb, "1A900030")
    _csp(vdb, "1A9000301", link=False)
    _csp(vdb, "1A900032", status="answered")
    chosen, _ = g.recipients(vdb)
    lines = dict(g.breakdown(vdb, chosen))
    assert lines["KOs (8-character code)"] == 2 and lines["Sub-KOs"] == 1
    assert lines["never sent a form link"] == 1 and lines["already filled the form"] == 1
    assert lines["new CSPs (came after the first sync)"] == 3


def test_no_form_link_is_shown_as_none(vdb):
    _csp(vdb, "1A900015", link=False)
    chosen, _ = g.recipients(vdb)
    assert [(r.csp_id, at) for r, _, at in chosen] == [("1A900015", None)]


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
