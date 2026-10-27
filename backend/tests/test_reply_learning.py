"""No. 154: what the reply agent learns, technical issues, and people's
email / phone corrected in INFO by the app.
"""

import copy

import pytest
from sqlalchemy import select

from app.models.csp_reply import CspReply
from app.models.knowledge import KnowledgeEntry
from app.services import csp_replies as cr
from app.services import info_writer as iw
from app.services.info_directory import InfoDirectory
from tests.test_csp_replies import (CONVERSATION, FakeWhatsApp, _csp, _in,  # noqa: F401
                                    _ours, rdb)
from tests.test_field_quality import _auth, _engine, qdb  # noqa: F401
from tests.test_info_auto_fix import _apply
from tests.test_info_directory import INFO_ROWS

on_loop = pytest.mark.asyncio(loop_scope="session")


# ---- people's email / phone in INFO -------------------------------------

def test_a_dcs_email_is_corrected_in_their_row():
    ops = iw.plan(INFO_ROWS, "dc_email", "ashutosh.pathak@eko.co.in",
                  "ashutosh.p@eko.co.in", [])
    (op,) = ops
    after = InfoDirectory.from_rows(_apply(INFO_ROWS, ops))
    dc = after.find_by_district("dc", "Patna")
    assert (dc.name, dc.email) == ("Ashutosh Pathak", "ashutosh.p@eko.co.in")
    assert after.find_by_district("dc", "Banka").email == "kumarbalram.0055@gmail.com"


def test_an_asms_phone_is_corrected():
    ops = iw.plan(INFO_ROWS, "asm_contact", "9306252773", "9306252700", [])
    after = InfoDirectory.from_rows(_apply(INFO_ROWS, ops))
    assert after.find_by_territory("asm", "Chandigarh", "Haryana").mobile == "9306252700"


def test_two_people_with_the_same_value_are_left_for_a_person():
    rows = copy.deepcopy(INFO_ROWS)
    rows[7] = list(rows[7])
    rows[7][1] = "anil.sharma@eko.co.in"          # Munna now shares Anil's email
    with pytest.raises(iw.CannotFix, match="2 ASMs"):
        iw.plan(rows, "asm_email", "anil.sharma@eko.co.in", "x@eko.co.in", [])


def test_a_value_already_changed_is_left_alone():
    with pytest.raises(iw.CannotFix, match="no DC in INFO has"):
        iw.plan(INFO_ROWS, "dc_contact", "9000000000", "9000000001", [])


def test_names_are_not_changed_by_the_app():
    with pytest.raises(iw.CannotFix, match="does not change dc"):
        iw.plan(INFO_ROWS, "dc", "Balram", "Someone", [])


# ---- technical issues ---------------------------------------------------

@pytest.mark.parametrize("message", [
    "biometric machine kaam nahi kar raha", "net nahi chal raha",
    "transaction fail ho gaya paisa kat gaya", "portal login nahi ho raha",
    "server down hai", "AEPS mein error aa raha hai",
])
def test_technical_issues_get_no_reply(rdb, message):
    assert cr.compose(rdb, _csp(rdb), [message]) == (["technical"], "", None)


def test_a_project_question_beside_a_technical_one_is_still_answered(rdb):
    intents, reply, _ = cr.compose(rdb, _csp(rdb), [
        "link open nahi hota", "printer bhi kharab hai"])
    assert intents == ["link"] and reply.startswith("Link ki pareshani")


def test_anything_else_still_goes_to_the_rm(rdb):
    intents, _, _ = cr.compose(rdb, _csp(rdb), ["mera commission kab aayega"])
    assert intents == ["else"]


def test_a_technical_message_is_skipped_with_the_reason(rdb):
    _csp(rdb)
    _ours(rdb)
    cr.collect(rdb, FakeWhatsApp([_in("biometric scanner kaam nahi kar raha", 10)]))
    rdb.commit()
    reply = rdb.execute(select(CspReply)).scalar_one()
    assert reply.status == "skipped" and "technical" in reply.note


# ---- the draft and what was sent ----------------------------------------

def _draft(db, messages=("link open nahi hota",)):
    _csp(db)
    _ours(db)
    cr.collect(db, FakeWhatsApp([_in(m, 30 - i) for i, m in enumerate(messages)]))
    db.commit()
    return db.execute(select(CspReply)).scalars().all()[-1]


def test_a_draft_sent_as_it_was_is_counted_unchanged(rdb, monkeypatch):
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: {"sent": True})
    reply = _draft(rdb)
    assert reply.draft_text == reply.reply_text
    cr.send(rdb, reply, "admin@eko.co.in", wa=FakeWhatsApp())
    assert (reply.edited, reply.edit_distance) == (False, 0)


def test_an_edited_reply_is_counted_and_offered_as_the_new_wording(rdb, monkeypatch):
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: {"sent": True})
    _csp(rdb)
    _ours(rdb)
    for minutes_ago in (40, 10):        # two conversations, one after the other
        cr.collect(rdb, FakeWhatsApp([_in("mera commission kab aayega", minutes_ago)]))
        rdb.commit()
        reply = rdb.execute(select(CspReply).where(
            CspReply.status == "draft")).scalar_one()
        cr.send(rdb, reply, "admin@eko.co.in",
                "Commission ke liye apne RM Rm Reply (9812345699) ko call karein.",
                wa=FakeWhatsApp())
        rdb.commit()
        # The next message from the same CSP starts a new conversation.
    assert reply.edited is True and reply.edit_distance > 0
    learned = cr.learning(rdb)
    (kind,) = [k for k in learned["kinds"] if k["key"] == "else"]
    assert (kind["sent"], kind["edited"], kind["unchanged_rate"]) == (2, 2, 0.0)
    assert kind["suggested"][0] == {
        "text": "Commission ke liye apne RM{rm} ko call karein.", "times": 2}
    assert kind["can_use"] is True


def test_using_a_wording_changes_what_the_agent_drafts(rdb):
    cr.use_wording(rdb, "else", "Apne RM{rm} ko call karein.", "admin@eko.co.in")
    rdb.commit()
    entry = rdb.execute(select(KnowledgeEntry).where(
        KnowledgeEntry.question == cr.ELSE)).scalars().first()
    assert entry.answer == "Apne RM{rm} ko call karein."
    assert cr.compose(rdb, _csp(rdb, rm=False), ["mera commission kab aayega"])[1] \
        == "Apne RM ko call karein."
    with pytest.raises(ValueError):
        cr.use_wording(rdb, "documents", "x", "a")


@on_loop
async def test_the_learning_endpoints_are_for_admins(client, rdb):
    r = await client.get("/api/admin/csp-replies/learning", headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/csp-replies/learning", headers=_auth("admin"))
    assert r.status_code == 200 and "unchanged_rate" in r.json()
    r = await client.post("/api/admin/csp-replies/learning/use",
                          headers=_auth("admin"),
                          json={"intent": "upload", "text": "RM{rm} se baat karein."})
    assert r.status_code == 200, r.text
