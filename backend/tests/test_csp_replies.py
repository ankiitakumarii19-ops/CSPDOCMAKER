"""The reply agent for CSPs' WhatsApp messages (No. 151).

Rules + Knowledge Base, no AI. The WhatsApp platform is a stand-in: nothing
leaves the test. Starts with the real conversation that asked for it
(25 Oct 2026: the link does not open; police verification and agreement
upload; "plez team help me").
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.authorization_record import AuthorizationRecord
from app.models.csp_record import CSPRecord
from app.models.csp_reply import CspReply
from app.models.enums import UserRole
from app.services import csp_replies as cr
from tests.test_field_quality import _auth, _engine, qdb  # noqa: F401

on_loop = pytest.mark.asyncio(loop_scope="session")

PHONE = "919812345611"
NOW = datetime.now(timezone.utc)
CONVERSATION = ["Sir jab se apne lino bhejna suru kiya h ye link open nahi hota",
                "Mera police verification aur aggriment upload nahi hota",
                "Plez team help me", "Plez"]


def _migration():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions",
                        "d1f3a5c7e9b2_csp_replies.py")
    spec = importlib.util.spec_from_file_location("csp_replies_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rdb(qdb):
    """The reply wordings exactly as the migration writes them — put back
    here, because other tests empty the Knowledge Base."""
    from app.models.knowledge import KnowledgeEntry
    qdb.execute(text("TRUNCATE csp_replies, whatsapp_messages, email_messages, "
                     "authorization_records RESTART IDENTITY CASCADE"))
    qdb.execute(text("DELETE FROM knowledge_entries WHERE category = 'CSP replies'"))
    m = _migration()
    for q, p, k, a in m.START:
        qdb.add(KnowledgeEntry(question=q, phrasings=p, keywords=k, answer=a,
                               category=m.CATEGORY, active=True,
                               updated_by=m.BY))
    qdb.commit()
    return qdb


def _csp(db, code="1A997001", rm=True, **kw):
    values = dict(csp_id=code, csp_code=code, name="Reply Csp",
                  mobile="9812345611", email="reply@example.com",
                  origin="baseline")
    if rm:
        values.update(rm_name="Rm Reply", rm_email="rm.reply@eko.co.in")
        db.add(AuthorizationRecord(email="rm.reply@eko.co.in", name="Rm Reply",
                                   mobile="9812345699", role=UserRole.RM,
                                   active=True, source="google_sheet"))
    values.update(kw)
    record = CSPRecord(**values)
    db.add(record)
    db.commit()
    return record


# ---- understanding ------------------------------------------------------

@pytest.mark.parametrize("message,intents", [
    (CONVERSATION[0], ["link"]),
    (CONVERSATION[1], ["upload"]),
    (CONVERSATION[2], []),
    ("लिंक नहीं खुल रहा", ["link"]),
    ("link nahi mila", ["link"]),
    ("link mil gaya", []),
    ("certificate kab milega", ["documents"]),
    ("ID card kab aayega", ["documents"]),
    ("mera naam galat hai", ["wrong_details"]),
    ("address change karna hai", ["wrong_details"]),
    ("ok thank you", ["thanks"]),
    ("धन्यवाद", ["thanks"]),
    ("ठीक है 🙏", ["thanks"]),
])
def test_the_rules_read_what_csps_write(message, intents):
    assert cr.classify(message) == intents


def test_the_real_conversation_gets_a_new_link_and_the_rm(rdb):
    record = _csp(rdb)
    intents, reply, action = cr.compose(rdb, record, CONVERSATION)
    assert intents == ["link", "upload"]
    assert action == "fresh_link"
    assert reply == (
        "Link ki pareshani ke liye khed hai. Hum aapko abhi ek naya link "
        "bhej rahe hain - use 7 din ke andar ek baar bharein. Police "
        "verification, agreement aur doosre papers ke liye kripya apne RM Rm "
        "Reply (9812345699) se sampark karein.")
    assert "\n" not in reply


def test_a_csp_who_already_answered_is_told_so(rdb):
    from app.services import data_request_service as drs
    record = _csp(rdb)
    request, _ = drs.create(rdb, record.csp_id, ["gender"])
    request.status, request.answered_at = "answered", datetime(
        2026, 10, 24, 6, 0, tzinfo=timezone.utc)
    rdb.commit()
    intents, reply, action = cr.compose(rdb, record, ["link open nahi hota"])
    assert action is None
    assert reply.startswith("Aapki details 24 Oct 2026 ko humein mil chuki hain")


def test_documents_say_where_they_were_emailed(rdb):
    from app.models.email_message import EmailMessage
    record = _csp(rdb)
    assert "details poori hone ke baad" in cr.compose(
        rdb, record, ["certificate kab milega"])[1]
    rdb.add(EmailMessage(csp_id=record.csp_id, to_email="reply@example.com",
                         kind="documents", subject="s", track_token="t-r1",
                         send_status="sent",
                         sent_at=datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)))
    rdb.commit()
    reply = cr.compose(rdb, record, ["certificate kab milega"])[1]
    assert reply.startswith("Aapke documents 22 Oct 2026 ko reply@example.com "
                            "par email kiye gaye the.")


def test_thanks_needs_no_reply(rdb):
    assert cr.compose(rdb, _csp(rdb), ["ok", "thank you ji"]) == (
        ["thanks"], "", None)


def test_what_is_not_understood_goes_to_the_rm(rdb):
    record = _csp(rdb, rm=False)
    intents, reply, action = cr.compose(rdb, record, ["mera commission kab aayega"])
    assert intents == ["else"]
    assert reply == "Is baare mein kripya apne RM se sampark karein."


def test_a_lone_hi_beside_a_question_is_not_a_question(rdb):
    intents, _, _ = cr.compose(rdb, _csp(rdb), ["Hi", "certificate kab milega"])
    assert intents == ["documents"]


def test_the_knowledge_base_answers_what_the_rules_do_not(rdb):
    intents, reply, _ = cr.compose(rdb, _csp(rdb), ["kya yeh message asli hai"])
    assert intents == ["knowledge"]
    assert reply.startswith("Haan, yeh message Eko Bharat Ventures ki taraf se hai")


def test_an_admin_can_change_a_wording_and_a_deleted_one_falls_back(rdb):
    from app.models.knowledge import KnowledgeEntry
    record = _csp(rdb, rm=False)
    entry = rdb.execute(select(KnowledgeEntry).where(
        KnowledgeEntry.question == cr.ELSE)).scalars().first()
    entry.answer = "Apne RM{rm} ko call karein."
    rdb.commit()
    assert cr.compose(rdb, record, ["mera commission kab aayega"])[1] == \
        "Apne RM ko call karein."
    entry.active = False
    rdb.commit()
    assert cr.compose(rdb, record, ["mera commission kab aayega"])[1] == \
        cr.DEFAULTS[cr.ELSE].replace("{rm}", "")
    entry.active, entry.answer = True, cr.DEFAULTS[cr.ELSE]
    rdb.commit()


@on_loop
async def test_the_staff_chat_never_answers_from_csp_replies(rdb):
    from app.database import async_session_factory
    from app.services import knowledge_service
    async with async_session_factory() as session:
        entries = await knowledge_service.active_entries(session)
    assert entries and all(e.category != "CSP replies" for e in entries)


# ---- the inbox ----------------------------------------------------------

def _ours(db, code="1A997001", at=None):
    from app.models.whatsapp_message import WhatsAppMessage
    db.add(WhatsAppMessage(csp_id=code, phone=PHONE, kind="data_request",
                           source="t", send_status="sent",
                           sent_at=at or NOW - timedelta(hours=10)))
    db.commit()


class FakeWhatsApp:
    SENT, PENDING, FAILED = "sent", "pending", "failed"

    def __init__(self, inbox=None, result="sent"):
        self.inbox, self.result, self.sent = list(inbox or []), result, []

    def call_tool(self, name, arguments):
        assert name == "get_incoming_messages"
        return {"messages": self.inbox}

    def send(self, phone, body, values, source_name=None):
        self.sent.append((phone, values["message"]))
        return {"status": self.result, "reason": "test", "job_id": None,
                "template_name": "t"}


def _in(text_, minutes_ago, phone=PHONE):
    return {"from_phone": phone, "body": text_, "msg_type": "text",
            "sent_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


def test_new_messages_become_one_draft_per_csp(rdb):
    _csp(rdb)
    _ours(rdb)
    wa = FakeWhatsApp([_in(t, 30 - i) for i, t in enumerate(CONVERSATION)]
                      + [_in("hello", 5, phone="919800000000")])  # not ours
    assert cr.collect(rdb, wa) == {"new": 1, "updated": 0}
    rdb.commit()
    (draft,) = rdb.execute(select(CspReply)).scalars().all()
    assert (draft.status, draft.intents, draft.action) == (
        "draft", ["link", "upload"], "fresh_link")
    assert [m["text"] for m in draft.messages] == CONVERSATION
    assert cr.collect(rdb, wa) == {"new": 0, "updated": 0}, "seen once"
    wa.inbox.append(_in("mera naam galat hai", 2))
    assert cr.collect(rdb, wa) == {"new": 0, "updated": 1}, "same draft"
    rdb.commit()
    assert len(rdb.execute(select(CspReply)).scalars().all()) == 1


def test_the_phones_automatic_greeting_and_old_messages_are_ignored(rdb):
    _csp(rdb)
    sent = NOW - timedelta(hours=2)
    _ours(rdb, at=sent)
    wa = FakeWhatsApp([
        {"from_phone": PHONE, "body": "Thanks for contacting us!",
         "sent_at": (sent + timedelta(seconds=5)).isoformat()},
        _in("link open nahi hota", 60 * 24 * 4)])        # 4 days old
    assert cr.collect(rdb, wa) == {"new": 0, "updated": 0}


def test_thanks_and_holds_are_not_answered(rdb):
    _csp(rdb)
    _ours(rdb)
    cr.collect(rdb, FakeWhatsApp([_in("ok thank you", 10)]))
    rdb.commit()
    assert rdb.execute(select(CspReply.status)).scalar_one() == "skipped"
    rdb.execute(text("UPDATE csp_records SET send_hold = 'Inactive in the Calling sheet'"))
    rdb.commit()
    cr.collect(rdb, FakeWhatsApp([_in("ok thank you", 10), _in("link nahi khulta", 3)]))
    rdb.commit()
    statuses = rdb.execute(select(CspReply.status, CspReply.note)
                           .order_by(CspReply.created_at)).all()
    assert statuses[-1][0] == "skipped" and "on hold" in statuses[-1][1]


# ---- sending ------------------------------------------------------------

def _draft(db, wa=None):
    _csp(db)
    _ours(db)
    cr.collect(db, wa or FakeWhatsApp([_in(t, 30 - i)
                                       for i, t in enumerate(CONVERSATION)]))
    db.commit()
    return db.execute(select(CspReply)).scalar_one()


def test_sending_sends_the_reply_then_the_new_link(rdb, monkeypatch):
    from app.services import data_request_service as drs
    from app.services import message_sender
    asked, cancelled = [], []
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: asked.append(kw) or {"sent": True})
    monkeypatch.setattr(drs, "cancel", lambda s, c, why="": cancelled.append(why) or 1)
    reply = _draft(rdb)
    wa = FakeWhatsApp()
    cr.send(rdb, reply, "admin@eko.co.in", "Edited: naya link aa raha hai.", wa=wa)
    rdb.commit()
    assert wa.sent == [(PHONE, "Edited: naya link aa raha hai.")]
    assert (reply.status, reply.decided_by, reply.note) == (
        "sent", "admin@eko.co.in", "new link sent")
    assert asked == [{"verify": True, "manual": True}]
    assert cancelled and "link does not work" in cancelled[0]
    from app.models.whatsapp_message import WhatsAppMessage
    assert rdb.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.kind == "other")).scalars().first() is not None, \
        "on the WhatsApp messages screen like any message"


def test_a_reply_waiting_for_meta_stays_a_draft_and_a_failure_is_shown(rdb):
    reply = _draft(rdb)
    cr.send(rdb, reply, "a@eko.co.in", wa=FakeWhatsApp(result="pending"))
    assert reply.status == "draft" and "checking the wording" in reply.note
    cr.send(rdb, reply, "a@eko.co.in", wa=FakeWhatsApp(result="failed"))
    assert reply.status == "failed" and reply.note.startswith("not sent")


def test_nothing_is_sent_to_a_csp_on_hold(rdb):
    reply = _draft(rdb)
    rdb.execute(text("UPDATE csp_records SET send_hold = 'Not live yet'"))
    rdb.commit()
    rdb.expire_all()
    with pytest.raises(ValueError, match="Not live yet"):
        cr.send(rdb, reply, "a@eko.co.in", wa=FakeWhatsApp())


# ---- the switch ---------------------------------------------------------

def test_draft_mode_never_sends_auto_mode_sends_when_quiet(rdb, monkeypatch):
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: {"sent": True})
    _csp(rdb)
    _ours(rdb)
    wa = FakeWhatsApp([_in("certificate kab milega", 30)])
    assert cr.get_mode(rdb) == "draft"
    assert cr.run(rdb, wa=wa)["sent"] == 0 and wa.sent == []
    cr.set_mode(rdb, "auto")
    rdb.commit()
    try:
        assert cr.run(rdb, wa=wa, sending_hours=False)["sent"] == 0
        assert cr.run(rdb, wa=wa)["sent"] == 1
        assert rdb.execute(select(CspReply.decided_by)).scalar_one() == "automatic"
        wa.inbox.append(_in("ID card kab aayega", 1))   # not quiet yet
        assert cr.run(rdb, wa=wa)["sent"] == 0
        cr.set_mode(rdb, "off")
        rdb.commit()
        assert cr.run(rdb, wa=wa) == {"mode": "off"}
    finally:
        cr.set_mode(rdb, "draft")
        rdb.commit()


def test_the_job_never_runs_from_a_laptop(rdb, monkeypatch):
    from app.config import get_settings
    from app.workers import csp_reply_worker
    monkeypatch.setattr(get_settings(), "public_app_url", "http://localhost:3000")
    assert "public address" in csp_reply_worker.run_once(rdb)["skipped"]


# ---- the screen's endpoints ---------------------------------------------

@on_loop
async def test_admins_list_send_and_skip_and_only_the_owner_switches(
        client, rdb, monkeypatch):
    from app.services import whatsapp_platform
    monkeypatch.setattr(whatsapp_platform, "send", FakeWhatsApp().send)
    reply = _draft(rdb)
    r = await client.get("/api/admin/csp-replies", headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/csp-replies", headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["mode"], body["waiting"]) == ("draft", 1)
    assert body["replies"][0]["intents"][0]["label"] == "Link does not open"

    r = await client.post(f"/api/admin/csp-replies/{reply.id}/skip",
                          headers=_auth("admin"))
    assert r.json()["status"] == "skipped"
    r = await client.post(f"/api/admin/csp-replies/{reply.id}/send",
                          headers=_auth("admin"), json={"text": "x"})
    assert r.status_code == 409

    r = await client.put("/api/admin/csp-replies/mode", headers=_auth("admin"),
                         json={"mode": "auto"})
    assert r.status_code == 403
    r = await client.put("/api/admin/csp-replies/mode",
                         headers=_auth("super_admin"), json={"mode": "auto"})
    assert r.json() == {"mode": "auto"}
    r = await client.put("/api/admin/csp-replies/mode",
                         headers=_auth("super_admin"), json={"mode": "draft"})
    assert r.json() == {"mode": "draft"}
