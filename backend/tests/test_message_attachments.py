# -*- coding: utf-8 -*-
"""Messaging → Ask CSPs with a photo, video or file (No. 257): what may be
attached, it goes on WhatsApp inside the wording for its kind and by email
as an attachment, uploaded to the platform once; never with the details
form; the new filters (RM, DC, LHO, AO, documents sent)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.models.email_document import EmailDocument
from app.models.email_job import EmailJob
from app.models.enums import DocumentType, EmailStatus, JobState, WorkflowType
from app.models.message_attachment import MessageAttachment
from app.models.messaging import MessageCampaign
from app.models.processing_job import ProcessingJob
from app.models.whatsapp_message import WhatsAppMessage
from app.services import message_attachments as ma
from tests.test_ask_csps import _auth, csps  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


# ---- what may be attached (no database) ------------------------------------

@pytest.mark.parametrize("name, kind", [
    ("photo.JPG", ma.IMAGE), ("p.png", ma.IMAGE), ("clip.mp4", ma.VIDEO),
    ("notice.pdf", ma.DOCUMENT), ("list.xlsx", ma.DOCUMENT), ("a.docx", ma.DOCUMENT),
])
async def test_what_whatsapp_carries_is_accepted(name, kind):
    assert ma.check(name, b"x")[0] == kind


@pytest.mark.parametrize("name, size, says", [
    ("virus.exe", 1, "cannot be sent"),
    ("noext", 1, "cannot be sent"),
    ("photo.jpg", 0, "is empty"),
    ("photo.jpg", 5 * ma.MB + 1, "at most 5 MB"),
    ("clip.mp4", 16 * ma.MB + 1, "at most 16 MB"),
])
async def test_anything_else_is_refused_with_the_reason(name, size, says):
    with pytest.raises(ma.AttachmentRefused, match=says):
        ma.check(name, b"0" * size)


async def test_each_kind_has_its_own_wording():
    words = set(ma.WHATSAPP_WORDING.values())
    assert len(words) == 3
    assert "here is a photo from" in ma.WHATSAPP_WORDING[ma.IMAGE]
    assert "here is a video from" in ma.WHATSAPP_WORDING[ma.VIDEO]
    assert "here is a file from" in ma.WHATSAPP_WORDING[ma.DOCUMENT]


async def test_the_platform_gets_the_header_for_the_kind(monkeypatch):
    from types import SimpleNamespace

    from app.services import whatsapp_platform as wa

    calls = {}

    def platform(name, arguments):
        calls[name] = arguments
        return {"job_id": "j"} if name == "upload_contacts" else {"action": "sent", "sent": 1}
    monkeypatch.setattr(wa, "call_tool", platform)
    monkeypatch.setattr(wa, "_settings", lambda: SimpleNamespace(
        test_copy=False, whatsapp_language="en_US"))
    out = wa.send("9812345678", ma.WHATSAPP_WORDING[ma.VIDEO],
                  {"name": "Csp", "message": "hello"}, source_name="t",
                  force=True, media_type="video", media_url="wamedia://abc")
    assert out["status"] == wa.SENT, out
    sent = calls["smart_send_template"]
    assert (sent["header_type"], sent["header_media_url"]) == ("video", "wamedia://abc")
    assert "here is a video from" in sent["body"]


# ---- through the screen's API ----------------------------------------------

@pytest.fixture
async def clean(db):
    await db.execute(text("TRUNCATE message_attachments, email_messages "
                          "RESTART IDENTITY CASCADE"))
    await db.commit()


@pytest.fixture
def server(monkeypatch):
    """The server, with WhatsApp and email caught instead of sent."""
    from app.services import message_sender, whatsapp_platform

    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")
    monkeypatch.setattr(get_settings(), "whatsapp_platform_url", "https://wa.example/mcp")
    monkeypatch.setattr(get_settings(), "test_copy", False)
    out = {"wa": [], "uploads": [], "email": []}

    def fake_send(phone, body, values, source_name, **kw):
        out["wa"].append({"phone": phone, "body": body, "message": values["message"], **kw})
        return {"status": whatsapp_platform.SENT, "reason": "",
                "job_id": f"att{len(out['wa'])}", "template_name": "t"}

    def fake_upload(path):
        with open(path, "rb") as fh:
            out["uploads"].append(fh.read())
        return f"wamedia://{len(out['uploads'])}"

    def fake_email(to, subject, body, **kw):
        out["email"].append({"to": to, "body": body, **kw})
        return True, ""

    monkeypatch.setattr(whatsapp_platform, "send", fake_send)
    monkeypatch.setattr(whatsapp_platform, "upload_media", fake_upload)
    monkeypatch.setattr(message_sender, "_send_email", fake_email)
    from app.services import manual_messages
    monkeypatch.setattr(manual_messages, "channels", lambda settings=None: [
        {"kind": "whatsapp", "can_send": True, "label": "WhatsApp", "why_not": ""},
        {"kind": "email", "can_send": True, "label": "Email", "why_not": ""}])
    return out


async def _upload(client, name, data, role="admin"):
    return await client.post("/api/admin/messaging/attachments", headers=_auth(role),
                             files={"file": (name, data, "application/octet-stream")})


async def test_upload_keeps_the_file_and_says_its_kind(client, db, clean):
    r = await _upload(client, "Notice.PNG", PNG)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["media_kind"], body["filename"], body["file_size"]) == ("image", "Notice.PNG", len(PNG))
    row = (await db.execute(select(MessageAttachment))).scalar_one()
    assert row.data == PNG and row.content_type == "image/png"


async def test_upload_refuses_what_whatsapp_cannot_carry(client, clean):
    r = await _upload(client, "setup.exe", b"MZ")
    assert r.status_code == 400 and "cannot be sent" in r.json()["detail"]


async def test_an_rm_cannot_upload(client, clean):
    r = await _upload(client, "a.png", PNG, role="rm")
    assert r.status_code == 403


async def test_photo_goes_on_whatsapp_to_many_uploaded_once(client, db, csps, clean, server):  # noqa: F811
    att = (await _upload(client, "notice.png", PNG)).json()
    for ids in (["1A870001"], ["1A870002", "1A870003"]):      # two parts, like the screen
        r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
            "csp_ids": ids, "kind": "custom", "channel": "whatsapp",
            "text": "Namaste {name}, see the new rules.", "attachment_id": att["id"]})
        assert r.status_code == 200, r.text
        assert all(x["sent"] for x in r.json()["results"]), r.json()
    assert len(server["wa"]) == 3
    assert server["uploads"] == [PNG]                       # once, not per CSP
    first = server["wa"][0]
    assert first["media_type"] == "image" and first["media_url"] == "wamedia://1"
    assert "here is a photo from" in first["body"]
    logged = (await db.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.csp_id == "1A870001"))).scalar_one()
    assert logged.body_text.startswith("[image: notice.png]")
    campaign = (await db.execute(select(MessageCampaign).order_by(
        MessageCampaign.created_at.desc()))).scalars().first()
    assert campaign.outcome["attachment"]["filename"] == "notice.png"


async def test_no_words_with_a_file_gets_a_short_line(client, csps, clean, server):  # noqa: F811
    att = (await _upload(client, "guide.pdf", b"%PDF-1.4")).json()
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "custom", "channel": "whatsapp",
        "text": "", "attachment_id": att["id"]})
    assert r.status_code == 200 and r.json()["sent"] == 1, r.text
    assert server["wa"][0]["message"] == "please see the file with this message."
    assert server["wa"][0]["media_type"] == "document"


async def test_by_email_the_file_is_attached(client, csps, clean, server):  # noqa: F811
    att = (await _upload(client, "clip.mp4", b"\x00\x00\x00\x18ftypmp42")).json()
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "custom", "channel": "email",
        "text": "Please watch this.", "attachment_id": att["id"]})
    assert r.status_code == 200 and r.json()["sent"] == 1, r.text
    mail = server["email"][0]
    assert mail["to"] == "asha@example.com"
    assert mail["attachments"] == [("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")]
    assert server["uploads"] == []                          # WhatsApp not used


async def test_a_platform_upload_failure_is_said_per_csp(client, csps, clean, server, monkeypatch):  # noqa: F811
    from app.services import whatsapp_platform

    def refuse(path):
        raise whatsapp_platform.WhatsAppPlatformError("media too large for Meta")
    monkeypatch.setattr(whatsapp_platform, "upload_media", refuse)
    att = (await _upload(client, "a.png", PNG)).json()
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "custom", "channel": "whatsapp",
        "text": "hi", "attachment_id": att["id"]})
    res = r.json()["results"][0]
    assert not res["sent"] and "media too large for Meta" in res["reason"]
    assert server["wa"] == []


async def test_never_with_the_details_form_and_unknown_file_refused(client, csps, clean, server):  # noqa: F811
    att = (await _upload(client, "a.png", PNG)).json()
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "details_form", "channel": "whatsapp",
        "attachment_id": att["id"]})
    assert r.status_code == 400 and "not with the details form" in r.json()["detail"]
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "custom", "channel": "whatsapp",
        "text": "hi", "attachment_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 400 and "attach it again" in r.json()["detail"]
    assert server["wa"] == []


async def test_on_hold_still_never_gets_it(client, csps, clean, server):  # noqa: F811
    att = (await _upload(client, "a.png", PNG)).json()
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870004"], "kind": "custom", "channel": "whatsapp",
        "text": "hi", "attachment_id": att["id"]})
    assert not r.json()["results"][0]["sent"] and server["wa"] == []


async def test_the_platform_ref_is_uploaded_again_after_a_day(db, clean):
    uploads = []

    class Wa:
        @staticmethod
        def upload_media(path):
            uploads.append(path)
            return f"wamedia://{len(uploads)}"

    def run(sync):
        row = ma.save(sync, "a.png", PNG, "me")
        first = ma.platform_ref(sync, row, Wa)
        again = ma.platform_ref(sync, row, Wa)
        row.platform_ref_at = datetime.now(timezone.utc) - timedelta(hours=25)
        later = ma.platform_ref(sync, row, Wa)
        return first, again, later
    assert await db.run_sync(run) == ("wamedia://1", "wamedia://1", "wamedia://2")
    await db.rollback()


# ---- the new filters -------------------------------------------------------

async def test_candidates_carry_rm_dc_lho_ao_and_documents_sent(client, db, csps):  # noqa: F811
    rec = {"1A870001": dict(rm_name="Ravi  Kumar", dc="DC One", lho="Patna", ao="AO Gaya")}
    from app.models.csp_record import CSPRecord
    row = (await db.execute(select(CSPRecord).where(CSPRecord.csp_id == "1A870001"))).scalar_one()
    for k, v in rec["1A870001"].items():
        setattr(row, k, v)
    job = ProcessingJob(job_id="JOB-ATT-1", csp_id="1A870001",
                        workflow_type=WorkflowType.NEW_CSP, current_state=JobState.COMPLETED)
    db.add(job)
    await db.flush()
    mail = EmailJob(processing_job_id=job.id, recipient="asha@example.com",
                    subject="docs", status=EmailStatus.SENT)
    db.add(mail)
    await db.flush()
    for d in DocumentType:                                  # a KO gets all four
        db.add(EmailDocument(email_job_id=mail.id, document_type=d))
    await db.commit()

    body = (await client.get("/api/admin/messaging/candidates", headers=_auth())).json()
    rows = {c["csp_id"]: c for c in body["candidates"]}
    a = rows["1A870001"]
    assert (a["rm"], a["dc"], a["lho"], a["ao"]) == ("Ravi Kumar", "DC One", "Patna", "AO Gaya")
    assert a["documents_sent"] is True
    assert rows["1A870002"]["documents_sent"] is False
