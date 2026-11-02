# -*- coding: utf-8 -*-
"""One way of matching a search, everywhere (No. 175): part of a word, any
capitals, extra spaces, phone by its digits; an RM finds every CSP but acts
only on their own; the header's search comes back grouped."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.csp_record import CSPRecord
from app.models.csp_reply import CspReply
from app.models.enums import DocumentFormat, DocumentType
from app.models.rm_alert import MISSING_DATA, OPEN, RMAlert
from app.models.stored_document import StoredDocument
from app.services import jwt_service, search_match
from tests.conftest import MINIMAL_PDF

pytestmark = pytest.mark.asyncio(loop_scope="session")

RM = "rm.search@eko.co.in"


def _auth(email=RM, role="rm"):
    token = jwt_service.create_access_token({"sub": email, "role": role, "name": "x"})
    return {"Authorization": f"Bearer {token}"}


def test_normalize():
    assert search_match.normalize("  Kaushar   JAHAN ") == "kaushar jahan"


@pytest.fixture
async def csps(db):
    db.add(CSPRecord(csp_id="1A850725", csp_code="1A850725", name="Kaushar  Jahan",
                     mobile="+91 98123-45670", email="kaushar@example.com",
                     district="Ghaziabad", state="Uttar Pradesh", rm_name="Shiwani",
                     rm_email=RM, rm_resolution="sheet"))
    db.add(CSPRecord(csp_id="1A850799", csp_code="1A850799", name="Ajit Kumar",
                     mobile="9000000099", district="Patna", state="Bihar",
                     rm_name="Vandana", rm_email="vandana@eko.co.in",
                     rm_resolution="sheet"))
    await db.commit()


@pytest.mark.parametrize("q,expected", [
    ("1A8507", {"1A850725", "1A850799"}),
    ("1a850725", {"1A850725"}),
    ("kaushar jahan", {"1A850725"}),         # two spaces in the record
    ("  KAUSHAR   ", {"1A850725"}),
    ("98123 456", {"1A850725"}),             # phone by its digits
    ("kaushar@EXAMPLE", {"1A850725"}),
    ("ghaziabad", {"1A850725"}),
    ("bihar", {"1A850799"}),
    ("vandana", {"1A850799"}),               # RM name
    ("zzz-nobody", set()),
])
async def test_the_documents_search_matches_part_of_anything(client, csps, q, expected):
    body = (await client.get("/api/csps/search", params={"q": q},
                             headers=_auth())).json()
    assert {r["csp_id"] for r in body["results"]} == expected


async def test_an_rm_finds_every_csp_but_acts_only_on_their_own(client, csps):
    body = (await client.get("/api/csps/search", params={"q": "1A8507"},
                             headers=_auth())).json()
    can = {r["csp_id"]: r["can_act"] for r in body["results"]}
    assert can == {"1A850725": True, "1A850799": False}


async def test_the_exact_code_comes_first(client, csps):
    body = (await client.get("/api/csps/search", params={"q": "1A850799"},
                             headers=_auth())).json()
    assert body["results"][0]["csp_id"] == "1A850799"


async def test_the_database_list_matches_the_same_way(client, csps):
    body = (await client.get("/api/admin/database", params={"q": "98123 45"},
                             headers=_auth())).json()
    assert [i["csp_id"] for i in body["items"]] == ["1A850725"]


async def test_the_header_search_comes_back_grouped(client, db, csps):
    db.add(StoredDocument(csp_id="1A850725", document_type=DocumentType.CSP_ID_CARD,
                          file_format=DocumentFormat.PDF, version=1, filename="id.pdf",
                          content_type="application/pdf", file_data=MINIMAL_PDF,
                          file_size=len(MINIMAL_PDF), checksum="s-1"))
    db.add(RMAlert(csp_id="1A850725", rm_email=RM, kind=MISSING_DATA, status=OPEN,
                   message="m", details={"csp_name": "Kaushar Jahan",
                                         "fields": [{"field": "photo", "label": "Photograph"}]}))
    db.add(CspReply(csp_id="1A850799", phone="919000000099", status="draft",
                    messages=[{"at": datetime.now(timezone.utc).isoformat(),
                               "text": "Ghaziabad wala link nahi khula", "type": "text"}],
                    last_in_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    await db.commit()

    body = (await client.get("/api/search", params={"q": "ghaziabad"},
                             headers=_auth("boss@eko.co.in", "admin"))).json()
    assert [c["csp_id"] for c in body["csps"]] == ["1A850725"]
    assert body["documents"][0]["label"] and body["documents"][0]["csp_id"] == "1A850725"
    assert body["action_items"][0]["missing"] == ["Photograph"]
    assert {c["csp_id"] for c in body["chats"]} == {"1A850799"}, \
        "a chat whose words match is found too"

    rm = (await client.get("/api/search", params={"q": "ghaziabad"},
                           headers=_auth())).json()
    assert rm["chats"] == [], "an RM does not see another RM's chat"
    assert rm["csps"][0]["can_act"] is True


async def test_an_empty_search_finds_nothing(client, csps):
    body = (await client.get("/api/search", params={"q": "   "}, headers=_auth())).json()
    assert body["csps"] == []


async def test_the_whatsapp_page_search_matches_the_same_way(client, db, csps):
    from app.models.whatsapp_message import WhatsAppMessage

    db.add(WhatsAppMessage(csp_id="1A850725", csp_name="Kaushar  Jahan",
                           phone="919812345670", kind="other", send_status="sent",
                           body_text="Please send your photo"))
    await db.commit()
    for q in ("KAUSHAR   jahan", "98123 45", "send your PHOTO"):
        body = (await client.get("/api/admin/whatsapp-messages", params={"q": q},
                                 headers=_auth("boss@eko.co.in", "admin"))).json()
        assert [m["csp_id"] for m in body["rows"]] == ["1A850725"], q
