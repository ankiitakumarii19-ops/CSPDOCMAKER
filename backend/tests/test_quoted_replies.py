# -*- coding: utf-8 -*-
"""Reply to one CSP message, quoted; open a CSP's chat from their name
(No. 171).

Eko's WhatsApp platform sends approved wordings only, so the quote goes
into the text: 'Aapne likha: "…" — <reply>'. The agent's learning still
compares the person's own words with its draft.
"""

import pytest
from sqlalchemy import select

from app.models.csp_reply import CspReply
from app.services import csp_replies as cr
from tests.test_csp_replies import (PHONE, FakeWhatsApp, _draft, rdb)  # noqa: F401
from tests.test_field_quality import _auth, _engine, qdb  # noqa: F401

on_loop = pytest.mark.asyncio(loop_scope="session")


def test_the_quote_goes_in_front_on_one_line():
    assert cr.with_quote("Ye link\nnahi open hota hai", "Naya link bhej rahe hain.") == \
        'Aapne likha: "Ye link nahi open hota hai" — Naya link bhej rahe hain.'
    assert cr.with_quote("", "Body") == "Body"
    assert cr.with_quote(None, "Body") == "Body"


def test_a_long_quote_is_shortened():
    text = cr.with_quote("x" * 300, "Ok.")
    quoted = text.split('"')[1]
    assert len(quoted) == cr.QUOTE_CHARS and quoted.endswith("…")


def test_too_long_together_is_refused_not_cut():
    with pytest.raises(ValueError, match="too long"):
        cr.with_quote("Ye link nahi open hota hai", "y" * (cr.MAX_CHARS - 10))


def test_a_quoted_reply_is_sent_with_the_quote(rdb, monkeypatch):
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: {"sent": True})
    reply = _draft(rdb)
    wa = FakeWhatsApp()
    cr.send(rdb, reply, "a@eko.co.in", reply.draft_text, wa=wa,
            quote="Ye link nahi open hota hai")
    rdb.commit()
    assert wa.sent == [(PHONE, f'Aapne likha: "Ye link nahi open hota hai" — '
                               f'{reply.draft_text}')]
    assert reply.reply_text.startswith("Aapne likha:")
    assert reply.edited is False, "quoting is not an edit of the draft"


@on_loop
async def test_the_send_endpoint_takes_a_quote(client, rdb, monkeypatch):
    from app.services import message_sender, whatsapp_platform
    fake = FakeWhatsApp()
    monkeypatch.setattr(whatsapp_platform, "send", fake.send)
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: {"sent": True})
    reply = _draft(rdb)
    r = await client.post(f"/api/admin/csp-replies/{reply.id}/send",
                          headers=_auth("admin"),
                          json={"text": "Theek hai.", "quote": "Kitni baar krne hai"})
    assert r.status_code == 200, r.text
    assert fake.sent[-1][1] == 'Aapne likha: "Kitni baar krne hai" — Theek hai.'


# ---- the CSP's whole chat, by code ----------------------------------------

@on_loop
async def test_a_csps_chat_opens_by_their_code(client, rdb, monkeypatch):
    from app.services import message_log
    reply = _draft(rdb)
    monkeypatch.setattr(message_log, "replies_from", lambda wa, phone: [
        {"from_phone": phone, "body": "Ye link nahi open hota hai",
         "msg_type": "text", "sent_at": "2026-10-31T13:06:00+00:00"}])
    r = await client.get(
        f"/api/admin/whatsapp-messages/csp/{reply.csp_id}/conversation",
        headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["csp_id"] == reply.csp_id and body["csp_name"] == "Reply Csp"
    assert body["phones"] == [PHONE]
    assert any(i["from"] == "csp" and "link" in i["text"] for i in body["items"])
    assert any(i["from"] == "us" for i in body["items"])


@on_loop
async def test_an_unreadable_inbox_is_said_not_hidden(client, rdb, monkeypatch):
    from app.services import message_log

    def broken(wa, phone):
        raise ConnectionError("platform down")

    reply = _draft(rdb)
    monkeypatch.setattr(message_log, "replies_from", broken)
    body = (await client.get(
        f"/api/admin/whatsapp-messages/csp/{reply.csp_id}/conversation",
        headers=_auth("admin"))).json()
    assert "could not be read" in body["error"]


@on_loop
async def test_an_unknown_csp_is_404(client, rdb):
    r = await client.get("/api/admin/whatsapp-messages/csp/NOPE0000/conversation",
                         headers=_auth("admin"))
    assert r.status_code == 404


@on_loop
async def test_an_rm_cannot_open_the_chat(client, rdb):
    r = await client.get("/api/admin/whatsapp-messages/csp/1A997001/conversation",
                         headers=_auth("rm"))
    assert r.status_code == 403
    assert rdb.execute(select(CspReply)).first() is None
