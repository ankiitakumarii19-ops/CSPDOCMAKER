# -*- coding: utf-8 -*-
"""Action Required (No. 174): only what is still pending is counted; a card
whose details are filled goes to History with when and how; one card opens
in full; an RM may message and open the chat of their own CSPs only."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.models.rm_alert import MISSING_DATA, OPEN, RESOLVED, RMAlert
from app.models.whatsapp_message import WhatsAppMessage
from app.services import jwt_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

RM = "rm.one@eko.co.in"
OTHER_RM = "rm.two@eko.co.in"
FIELDS = [{"field": "email", "label": "CSP Email Id", "type": "email",
           "blocks": ["ID Card"]},
          {"field": "photo", "label": "Photograph", "type": "file",
           "blocks": ["ID Card"]}]


def _auth(email, role="rm"):
    token = jwt_service.create_access_token({"sub": email, "role": role, "name": "x"})
    return {"Authorization": f"Bearer {token}"}


async def _card(db, code="1A880001", rm=RM, hold=None, origin="new"):
    db.add(CSPRecord(csp_id=code, csp_code=code, name="Rishi Raj",
                     mobile="9812345601", email="rishi@example.com",
                     rm_email=rm, rm_resolution="sheet", origin=origin,
                     send_hold=hold))
    await db.flush()
    alert = RMAlert(csp_id=code, rm_email=rm, kind=MISSING_DATA, status=OPEN,
                    message="needs things",
                    details={"csp_id": code, "csp_name": "Rishi Raj",
                             "fields": FIELDS})
    db.add(alert)
    await db.commit()
    return alert


def _complete(monkeypatch, missing=None):
    """What check_missing_data answers: nothing missing, or these fields."""
    from app.services import missing_data_service

    def check(csp, types):
        if not missing:
            return SimpleNamespace(has_missing_data=False, documents=[])
        doc = SimpleNamespace(document_label="ID Card", missing_fields=[
            SimpleNamespace(field_name=f, field_label=l, field_type="text")
            for f, l in missing])
        return SimpleNamespace(has_missing_data=True, documents=[doc],
                               csp_id=csp.csp_id, csp_name=csp.name)
    monkeypatch.setattr(missing_data_service, "check_missing_data", check)


async def test_the_card_lists_what_is_missing(client, db, monkeypatch):
    await _card(db)
    _complete(monkeypatch, missing=[("email", "CSP Email Id"),
                                    ("photo", "Photograph")])
    body = (await client.get("/api/alerts", headers=_auth(RM))).json()
    labels = [f["label"] for f in body["alerts"][0]["details"]["fields"]]
    assert labels == ["CSP Email Id", "Photograph"]


async def test_a_partly_filled_card_shows_only_what_is_left(client, db, monkeypatch):
    await _card(db)
    _complete(monkeypatch, missing=[("photo", "Photograph")])
    body = (await client.get("/api/alerts", headers=_auth(RM))).json()
    assert [f["label"] for f in body["alerts"][0]["details"]["fields"]] == ["Photograph"]
    assert body["total"] == 1


async def test_a_filled_card_moves_to_history_with_who_filled_it(client, db, monkeypatch):
    alert = await _card(db)
    db.add(DataRequest(csp_id=alert.csp_id, token_hash="t-ar-1",
                       fields=["email"], status="answered",
                       expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                       answered_at=datetime.now(timezone.utc) + timedelta(seconds=5),
                       answered_values={"email": "new@example.com"}))
    await db.commit()
    _complete(monkeypatch)

    body = (await client.get("/api/alerts", headers=_auth(RM))).json()
    assert body["total"] == 0, "the count is only what is still pending"

    history = (await client.get("/api/alerts/history?show=fixed",
                                headers=_auth(RM))).json()["items"]
    assert len(history) == 1
    item = history[0]
    assert item["status"] == "fixed" and item["fixed_at"]
    assert item["fixed_via"] == "csp_form"
    assert item["fixed_via_label"] == "CSP's reply (details form)"
    assert item["missing"] == ["CSP Email Id", "Photograph"], "what it was"


async def test_without_a_record_of_who_it_says_the_sheet(client, db, monkeypatch):
    await _card(db)
    _complete(monkeypatch)
    await client.get("/api/alerts", headers=_auth(RM))
    db.expire_all()
    alert = (await db.execute(select(RMAlert))).scalars().one()
    assert alert.status == RESOLVED and alert.resolved_via == "sheet"


async def test_history_filters_and_search(client, db, monkeypatch):
    await _card(db, "1A880001")
    await _card(db, "1A880002")
    _complete(monkeypatch, missing=[("photo", "Photograph")])
    pending = (await client.get("/api/alerts/history?show=pending",
                                headers=_auth(RM))).json()
    assert pending["total"] == 2
    found = (await client.get("/api/alerts/history?q=880002",
                              headers=_auth(RM))).json()["items"]
    assert [i["csp_id"] for i in found] == ["1A880002"]
    by_mail = (await client.get("/api/alerts/history?q=rishi@example",
                                headers=_auth(RM))).json()
    assert by_mail["total"] == 2


async def test_one_card_opens_in_full(client, db, monkeypatch):
    alert = await _card(db)
    db.add(DataRequest(csp_id=alert.csp_id, token_hash="t-ar-2",
                       fields=["email", "photo_url"], status="open",
                       sent_via="whatsapp", sent_to="919812345601",
                       expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    await db.commit()
    _complete(monkeypatch, missing=[("photo", "Photograph")])
    body = (await client.get(f"/api/alerts/{alert.id}", headers=_auth(RM))).json()
    assert body["name"] == "Rishi Raj" and body["csp_id"] == alert.csp_id
    assert body["flagged_at"]
    assert body["asked"][0]["channel"] == "whatsapp"
    assert "Photograph" in body["asked"][0]["fields"]
    assert {c["kind"] for c in body["channels"]} >= {"whatsapp", "email"}


async def test_another_rms_card_does_not_open(client, db):
    alert = await _card(db)
    r = await client.get(f"/api/alerts/{alert.id}", headers=_auth(OTHER_RM))
    assert r.status_code == 404


# ---- messaging from the card ------------------------------------------------

@pytest.fixture
def server(monkeypatch):
    """On the server, with a fake WhatsApp platform."""
    from app.services import whatsapp_platform

    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")
    monkeypatch.setattr(get_settings(), "whatsapp_platform_url", "https://wa.example/mcp")
    monkeypatch.setattr(get_settings(), "test_copy", False)
    sent = []

    def fake_send(phone, body, values, source_name, **kw):
        sent.append((phone, values["message"]))
        return {"status": whatsapp_platform.SENT, "reason": "", "job_id": f"j{len(sent)}",
                "template_name": "chat"}
    monkeypatch.setattr(whatsapp_platform, "send", fake_send)
    return sent


async def test_an_rm_messages_their_csp_and_it_is_logged(client, db, server):
    alert = await _card(db)
    r = await client.post(f"/api/csps/{alert.csp_id}/message", headers=_auth(RM),
                          json={"kind": "custom", "channel": "whatsapp",
                                "text": "Namaskar {name} ({csp_id}), please send: {missing_items}"})
    assert r.status_code == 200, r.text
    assert r.json()["sent"] is True
    assert server[0][1].startswith("Namaskar Rishi Raj (1A880001), please send:")
    row = (await db.execute(select(WhatsAppMessage))).scalars().one()
    assert row.body_text.startswith("Namaskar Rishi Raj") and row.sent_by == RM
    assert row.sent_because == "sent_by_a_person"
    log = (await db.execute(select(AuditLog).where(
        AuditLog.action == "csp_message"))).scalars().one()
    assert log.metadata_json["by"] == RM and log.metadata_json["channel"] == "whatsapp"


async def test_not_someone_elses_csp(client, db, server):
    alert = await _card(db)
    r = await client.post(f"/api/csps/{alert.csp_id}/message", headers=_auth(OTHER_RM),
                          json={"kind": "custom", "channel": "whatsapp", "text": "hi"})
    assert r.status_code == 404 and server == []


async def test_nothing_to_a_csp_on_hold(client, db, server):
    alert = await _card(db, hold="Not live yet")
    r = (await client.post(f"/api/csps/{alert.csp_id}/message", headers=_auth(RM),
                           json={"kind": "custom", "channel": "whatsapp",
                                 "text": "hi"})).json()
    assert r["sent"] is False and "on hold" in r["reason"] and server == []


async def test_an_existing_csp_never_gets_the_details_form(client, db, server):
    alert = await _card(db, origin="baseline")      # no import record = existing
    r = (await client.post(f"/api/csps/{alert.csp_id}/message", headers=_auth(RM),
                           json={"kind": "details_form", "channel": "whatsapp"})).json()
    assert r["sent"] is False and "existing CSP" in r["reason"]
    ok = (await client.post(f"/api/csps/{alert.csp_id}/message", headers=_auth(RM),
                            json={"kind": "custom", "channel": "whatsapp",
                                  "text": "Hello"})).json()
    assert ok["sent"] is True, "a custom message is allowed"


async def test_the_laptop_never_sends(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_app_url", "http://localhost:3000")
    alert = await _card(db)
    r = (await client.post(f"/api/csps/{alert.csp_id}/message", headers=_auth(RM),
                           json={"kind": "custom", "channel": "whatsapp",
                                 "text": "hi"})).json()
    assert r["sent"] is False and "Only the server sends" in r["reason"]


async def test_the_chat_opens_for_the_rm(client, db, monkeypatch):
    from app.services import message_log
    alert = await _card(db)
    monkeypatch.setattr(message_log, "replies_from", lambda wa, phone: [])
    db.add(WhatsAppMessage(csp_id=alert.csp_id, phone="919812345601", kind="other",
                           send_status="sent", body_text="Hello there", sent_by=RM))
    await db.commit()
    body = (await client.get(f"/api/csps/{alert.csp_id}/conversation",
                             headers=_auth(RM))).json()
    assert body["items"][0]["text"] == "Hello there"
    assert (await client.get(f"/api/csps/{alert.csp_id}/conversation",
                             headers=_auth(OTHER_RM))).status_code == 404
