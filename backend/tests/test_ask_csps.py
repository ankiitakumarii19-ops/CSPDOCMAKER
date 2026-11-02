# -*- coding: utf-8 -*-
"""Messaging → Ask CSPs (No. 174): anyone can be messaged, with a saved or
own message, through a channel that can send; on hold never; the details
form never to an existing CSP; every send logged."""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.models.messaging import MessageCampaign, MessageTemplate
from app.models.source_sheet import SourceSheetState
from app.models.whatsapp_message import WhatsAppMessage
from app.services import jwt_service

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _auth(role="admin"):
    token = jwt_service.create_access_token(
        {"sub": f"{role}.ask@eko.co.in", "role": role, "name": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def csps(db):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    # Not emptied by the shared fixture.
    await db.execute(text("TRUNCATE source_sheet_states, whatsapp_messages, "
                          "message_campaigns RESTART IDENTITY CASCADE"))
    await db.execute(text("DELETE FROM message_templates WHERE name IN "
                          "('Photo reminder', 'Supplied')"))
    await db.commit()

    # Complete, never asked, new.
    db.add(CSPRecord(csp_id="1A870001", csp_code="1A870001", name="Asha Devi",
                     mobile="9812345671", email="asha@example.com", origin="new",
                     address="1 Road", gender="Female"))
    # Already asked, missing their email, a Calling-sheet copy (not existing).
    db.add(CSPRecord(csp_id="1A870002", csp_code="1A870002", name="Bina Rai",
                     mobile="9812345672", origin="baseline"))
    db.add(SourceSheetState(csp_code="1A870002", imported_as="baseline"))
    db.add(DataRequest(csp_id="1A870002", token_hash="t-ask-1", fields=["email"],
                       status="open",
                       expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    # Existing (in CSPDATA before the import).
    db.add(CSPRecord(csp_id="1A870003", csp_code="1A870003", name="Chandan Old",
                     mobile="9812345673", origin="baseline"))
    # On hold.
    db.add(CSPRecord(csp_id="1A870004", csp_code="1A870004", name="Dev Hold",
                     mobile="9812345674", origin="new", send_hold="Not live yet"))
    await db.commit()


@pytest.fixture
def server(monkeypatch):
    from app.services import whatsapp_platform

    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")
    monkeypatch.setattr(get_settings(), "whatsapp_platform_url", "https://wa.example/mcp")
    monkeypatch.setattr(get_settings(), "test_copy", False)
    sent = []

    def fake(phone, body, values, source_name, **kw):
        sent.append((phone, values["message"]))
        return {"status": whatsapp_platform.SENT, "reason": "",
                "job_id": f"ask{len(sent)}", "template_name": "chat"}
    monkeypatch.setattr(whatsapp_platform, "send", fake)
    return sent


async def test_everyone_is_listed_with_why_they_might_not_get_it(client, csps):
    body = (await client.get("/api/admin/messaging/candidates", headers=_auth())).json()
    rows = {c["csp_id"]: c for c in body["candidates"]}
    assert set(rows) >= {"1A870001", "1A870002", "1A870003", "1A870004"}, \
        "not only the ones missing something"
    assert rows["1A870002"]["already_asked"] and rows["1A870002"]["asked_at"]
    assert rows["1A870003"]["existing"] and not rows["1A870002"]["existing"]
    assert rows["1A870004"]["on_hold"] == "Not live yet"


async def test_the_send_channels_are_listed_with_reasons(client, csps, server):
    body = (await client.get("/api/admin/messaging", headers=_auth())).json()
    by = {c["kind"]: c for c in body["send_channels"]}
    assert by["whatsapp"]["can_send"] is True
    assert by["sms"]["can_send"] is False and by["sms"]["why_not"]
    assert by["in_app"]["can_send"] is False


async def test_a_custom_message_to_many_with_placeholders(client, db, csps, server):
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001", "1A870002", "1A870003", "1A870004"],
        "kind": "custom", "channel": "whatsapp",
        "text": "Hi {name} ({csp_id}): {missing_items}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] == 3 and body["failed"] == 1, "the one on hold is refused"
    texts = dict(server)
    assert texts["919812345671"].startswith("Hi Asha Devi (1A870001): ")
    assert "Photograph" in texts["919812345671"], "{missing_items} filled in"
    assert texts["919812345673"].startswith("Hi Chandan Old"), \
        "an existing CSP may get a custom message"
    refused = next(x for x in body["results"] if x["csp_id"] == "1A870004")
    assert "on hold" in refused["reason"]
    assert (await db.execute(select(MessageCampaign))).scalars().one().sent_count == 3
    logged = (await db.execute(select(AuditLog).where(
        AuditLog.action == "csp_message"))).scalars().all()
    assert len(logged) == 4
    row = (await db.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.csp_id == "1A870001"))).scalars().one()
    assert row.body_text.startswith("Hi Asha Devi") and row.sent_by == "admin.ask@eko.co.in"


async def test_the_details_form_never_goes_to_an_existing_csp(client, csps, server, monkeypatch):
    from app.services import message_sender
    asked = []
    monkeypatch.setattr(message_sender, "choose_channel", lambda s, kind=None: object())
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: asked.append(r.csp_id) or {"sent": True})
    body = (await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870002", "1A870003"], "kind": "details_form",
        "channel": "whatsapp"})).json()
    assert asked == ["1A870002"]
    no = next(x for x in body["results"] if x["csp_id"] == "1A870003")
    assert no["sent"] is False and "existing CSP" in no["reason"]


async def test_an_empty_or_unknown_message_is_refused(client, csps, server):
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "custom", "channel": "whatsapp", "text": " "})
    assert r.status_code == 400
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": ["1A870001"], "kind": "broadcast", "channel": "whatsapp", "text": "x"})
    assert r.status_code == 400


async def test_at_most_fifty_in_one_request(client, csps, server):
    r = await client.post("/api/admin/messaging/send-message", headers=_auth(), json={
        "csp_ids": [f"X{i}" for i in range(51)], "kind": "custom",
        "channel": "whatsapp", "text": "hi"})
    assert r.status_code == 422


async def test_an_rm_cannot_send_to_many(client, csps, server):
    r = await client.post("/api/admin/messaging/send-message", headers=_auth("rm"), json={
        "csp_ids": ["1A870001"], "kind": "custom", "channel": "whatsapp", "text": "hi"})
    assert r.status_code == 403


async def test_saved_messages_are_added_edited_and_deleted(client, db, csps):
    r = await client.post("/api/admin/messaging/templates", headers=_auth(), json={
        "name": "Photo reminder", "purpose": "custom", "channel_kind": "whatsapp",
        "body": "Namaste {name}, please send your photo."})
    tid = r.json()["id"]
    r = await client.patch(f"/api/admin/messaging/templates/{tid}", headers=_auth(), json={
        "name": "Photo reminder", "purpose": "custom", "channel_kind": "whatsapp",
        "body": "Namaste {name}, your photo please."})
    assert r.status_code == 200
    assert (await client.delete(f"/api/admin/messaging/templates/{tid}",
                                headers=_auth())).json()["deleted"] is True
    db.expire_all()
    assert (await db.execute(select(MessageTemplate).where(
        MessageTemplate.name == "Photo reminder"))).first() is None


async def test_a_supplied_wording_cannot_be_deleted(client, db, csps):
    t = MessageTemplate(name="Supplied", purpose="data_request", channel_kind="whatsapp",
                        body="x", is_builtin=True, active=True)
    db.add(t)
    await db.commit()
    r = await client.delete(f"/api/admin/messaging/templates/{t.id}", headers=_auth())
    assert r.status_code == 400
