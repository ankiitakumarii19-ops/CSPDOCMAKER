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
    return [r.csp_id for r, *_ in chosen], left_out


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
    assert [(r.csp_id, at, v) for r, _, at, v in chosen] == [("1A900015", None, True)]


def _video(db, code, at, status="sent"):
    db.add(WhatsAppMessage(csp_id=code, phone="919800000001", kind="other",
                           send_status=status, sent_because="guide_video",
                           sent_at=at))
    db.commit()


def _link(db, code, at):
    db.add(DataRequest(csp_id=code, token_hash=f"t2-{code}-{at.timestamp()}", fields=["name"],
                       status="open", sent_via="whatsapp", created_at=at,
                       expires_at=NOW + timedelta(days=3)))
    db.commit()


def test_nobody_gets_the_video_and_link_twice(vdb):
    _csp(vdb, "1A900011", link=False)
    _video(vdb, "1A900011", NOW - timedelta(minutes=5))
    _link(vdb, "1A900011", NOW - timedelta(minutes=5))      # same moment counts
    codes, left_out = _codes(vdb)
    assert codes == [] and left_out == {"already got the video and its link": 1}


def test_video_went_but_link_did_not_only_the_link_is_left(vdb):
    _csp(vdb, "1A900016", link=False)
    _link(vdb, "1A900016", NOW - timedelta(days=2))          # an older link
    _video(vdb, "1A900016", NOW - timedelta(days=1))
    chosen, _ = g.recipients(vdb)
    assert [(r.csp_id, v) for r, _, _, v in chosen] == [("1A900016", False)]
    assert dict(g.breakdown(vdb, chosen))[
        "got the video earlier - only the link is left"] == 1


def test_a_failed_earlier_try_is_tried_again(vdb):
    _csp(vdb, "1A900012")
    _video(vdb, "1A900012", NOW, status="failed")
    chosen, _ = g.recipients(vdb)
    assert [(r.csp_id, v) for r, _, _, v in chosen] == [("1A900012", True)]


class _Sender:
    """message_sender stand-in: records what was asked."""
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def ask_for_details(self, db, r, **kw):
        from app.services import send_reason
        self.calls.append((r.csp_id, kw, send_reason.current()))
        if self.error:
            raise self.error
        return self.result


def test_link_is_a_fresh_verification_link(vdb):
    from app.services import send_reason
    from app.services.manual_messages import _audit
    _csp(vdb, "1A900017")
    r = vdb.get(CSPRecord, vdb.query(CSPRecord.id).filter_by(csp_id="1A900017").scalar())
    sender = _Sender(result={"sent": True})
    ok, why = g._send_link(vdb, r, "channel", "me@example.com", sender,
                           send_reason, _audit)
    assert ok and why == ""
    code, kw, reason = sender.calls[0]
    assert code == "1A900017" and reason == send_reason.GUIDE_VIDEO_LINK
    assert kw == {"channel": "channel", "manual": True, "verify": True, "fresh": True}


def test_a_link_failure_is_reported_not_raised(vdb):
    from app.services import send_reason
    from app.services.manual_messages import _audit
    _csp(vdb, "1A900018")
    r = vdb.get(CSPRecord, vdb.query(CSPRecord.id).filter_by(csp_id="1A900018").scalar())
    ok, why = g._send_link(vdb, r, "channel", "me@example.com",
                           _Sender(error=RuntimeError("platform down")),
                           send_reason, _audit)
    assert not ok and "platform down" in why
    ok, why = g._send_link(vdb, r, "channel", "me@example.com",
                           _Sender(result={"sent": False, "reason": "on hold"}),
                           send_reason, _audit)
    assert not ok and why == "on hold"


def test_template_list_is_read_from_the_platforms_text():
    raw = ('{"name": "other", "status": "APPROVED"}\n'
           '{"name": "%s", "status": "PENDING", "components": [{"text": "x {{1}} y"}]}'
           % g.TEMPLATE_NAME)
    assert [t["status"] for t in g._templates(raw)] == ["APPROVED", "PENDING"]


def test_the_video_fits_whatsapp():
    assert os.path.getsize(g.VIDEO) < 16 * 1024 * 1024


def test_send_run_video_then_link_and_a_rerun_sends_nothing(vdb, monkeypatch, capsys):
    """--send end to end with WhatsApp faked: each CSP gets the video, then
    the link; a second run finds nobody left."""
    from app.config import get_settings
    from app.services import message_sender
    from app.services import whatsapp_platform as wa

    _csp(vdb, "1A900040", link=False)
    _csp(vdb, "1A900041", link=False)
    order = []

    def call_tool(name, args):
        if name == "upload_contacts":
            order.append(("video", args["contacts"][0]["phone"]))
            return {"job_id": f"j{len(order)}"}
        return {"sent": 1}

    def ask_for_details(db, r, **kw):
        order.append(("link", r.csp_id))
        _link(db, r.csp_id, datetime.now(timezone.utc) + timedelta(seconds=1))
        return {"sent": True}

    monkeypatch.setattr(get_settings(), "test_copy", False)
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: True)
    monkeypatch.setattr(message_sender, "choose_channel", lambda db, kind=None: "wa")
    monkeypatch.setattr(message_sender, "ask_for_details", ask_for_details)
    monkeypatch.setattr(wa, "upload_media", lambda path: "media-ref")
    monkeypatch.setattr(wa, "call_tool", call_tool)
    monkeypatch.setattr(g, "template_status", lambda: "APPROVED")
    monkeypatch.setattr(sys, "argv", ["x", "--send", "--by", "me@example.com",
                                      "--pause", "0"])

    assert g.main() == 0
    out = capsys.readouterr().out
    assert "videos 2 sent, 0 failed; links 2 sent, 0 failed" in out
    assert [k for k, _ in order] == ["video", "link", "video", "link"]
    assert order[1] == ("link", "1A900040") and order[3] == ("link", "1A900041")

    order.clear()
    assert g.main() == 0
    assert order == [] and "Will get the video: 0" in capsys.readouterr().out


def _try_setup(monkeypatch, status="APPROVED", sent=1):
    from app.config import get_settings
    from app.services import message_sender
    from app.services import whatsapp_platform as wa

    calls = []

    def call_tool(name, args):
        calls.append((name, args))
        return {"job_id": "jt"} if name == "upload_contacts" else {"sent": sent}
    monkeypatch.setattr(get_settings(), "test_copy", False)
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: True)
    monkeypatch.setattr(wa, "upload_media", lambda path: "media-ref")
    monkeypatch.setattr(wa, "call_tool", call_tool)
    monkeypatch.setattr(g, "template_status", lambda: status)
    return calls


def test_try_on_one_number_sends_only_there_and_times_it(vdb, monkeypatch, capsys):
    _csp(vdb, "1A900050", link=False)
    calls = _try_setup(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x", "--test-to", "98765 43210"])
    assert g.main() == 0
    out = capsys.readouterr().out
    assert "given to the platform in" in out and "Sent to 9198******10 in" in out
    (n1, up), (n2, send) = calls
    assert up["contacts"][0]["phone"] == "919876543210"
    assert send["header_type"] == "video" and send["template_name"] == g.TEMPLATE_NAME
    vdb.expire_all()
    assert vdb.query(WhatsAppMessage).count() == 0           # nothing per CSP


def test_try_on_one_number_waits_for_meta_and_checks_the_number(vdb, monkeypatch, capsys):
    calls = _try_setup(monkeypatch, status="PENDING")
    monkeypatch.setattr(sys, "argv", ["x", "--test-to", "9876543210"])
    assert g.main() == 1 and calls == []
    assert "Meta has not approved" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["x", "--test-to", "12345"])
    assert g.main() == 1 and "Not a usable mobile number" in capsys.readouterr().out


def test_try_on_one_number_says_when_the_platform_refuses(vdb, monkeypatch, capsys):
    _try_setup(monkeypatch, sent=0)
    monkeypatch.setattr(sys, "argv", ["x", "--test-to", "9876543210"])
    assert g.main() == 1
    assert "FAILED after" in capsys.readouterr().out
