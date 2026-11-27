"""The day filter on every list (No. 272).

The Admin dashboard's "Today / Yesterday / On a date / From - To" (No. 171)
now also filters the WhatsApp messages and Emails screens (the day a message
was sent) and the RM dashboard (the day a CSP was last contacted). Days are
India days; date_from and date_to are inclusive; a malformed date, or a "to"
before the "from", is a 400 in plain words.
"""

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import delete, text

from app.models import CSPRecord
from app.models.email_message import EmailMessage
from app.models.whatsapp_message import WhatsAppMessage
from app.services import india_days, jwt_service
from app.services import pending_documents as pd
from app.services.rm_resolution import BY_SHEET

pytestmark = pytest.mark.asyncio(loop_scope="session")

UTC = timezone.utc
# Around the start and end of 20 Nov 2026 in India (UTC+5:30).
TIMES = {
    "19th, 23:59 IST": datetime(2026, 11, 19, 18, 29, tzinfo=UTC),
    "20th, 00:00 IST": datetime(2026, 11, 19, 18, 30, tzinfo=UTC),
    "20th, 23:59 IST": datetime(2026, 11, 20, 18, 29, tzinfo=UTC),
    "21st, 00:00 IST": datetime(2026, 11, 20, 18, 30, tzinfo=UTC),
}
# Long before any "last N days" window: dates replace that window.
OLD = datetime(2025, 1, 10, 6, 0, tzinfo=UTC)


def _auth(email, role):
    token = jwt_service.create_access_token(
        {"sub": email, "role": role, "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


ADMIN = _auth("admin.days@eko.co.in", "admin")
RM = _auth("rm.days@eko.co.in", "rm")


# ---- the rule, without a database ------------------------------------------

def test_india_days_and_bad_dates():
    days = india_days.bounds("2026-11-20", "2026-11-20")
    kept = [k for k, t in TIMES.items() if india_days.within(t, days)]
    assert kept == ["20th, 00:00 IST", "20th, 23:59 IST"]
    # ISO strings (as the RM dashboard rows carry) work the same.
    assert india_days.within(TIMES["20th, 00:00 IST"].isoformat(), days)
    assert not india_days.within(TIMES["21st, 00:00 IST"].isoformat(), days)
    # Only one end given.
    after = india_days.bounds("2026-11-20", None)
    assert [k for k, t in TIMES.items() if india_days.within(t, after)] == [
        "20th, 00:00 IST", "20th, 23:59 IST", "21st, 00:00 IST"]
    upto = india_days.bounds(None, "2026-11-19")
    assert [k for k, t in TIMES.items() if india_days.within(t, upto)] == [
        "19th, 23:59 IST"]
    # Nothing asked: everything, even no date at all; asked: no date = out.
    assert india_days.within(None, india_days.bounds(None, None))
    assert not india_days.within(None, days)
    with pytest.raises(ValueError, match="date_from must be a date"):
        india_days.bounds("20-11-2026", None)
    with pytest.raises(ValueError, match="before date_from"):
        india_days.bounds("2026-11-20", "2026-11-19")


def test_rm_rows_by_the_day_last_contacted():
    rows = [{"csp_id": "a", "last_contacted": TIMES["19th, 23:59 IST"].isoformat()},
            {"csp_id": "b", "last_contacted": TIMES["20th, 23:59 IST"].isoformat()},
            {"csp_id": "never", "last_contacted": None}]
    assert pd.last_contacted_in(rows, (None, None)) == rows
    got = pd.last_contacted_in(rows, india_days.bounds("2026-11-20", "2026-11-20"))
    assert [r["csp_id"] for r in got] == ["b"]


# ---- WhatsApp messages ------------------------------------------------------

@pytest.fixture
async def whatsapps(db):
    await db.execute(text("TRUNCATE whatsapp_messages, email_messages"))
    for label, at in list(TIMES.items()) + [("old", OLD)]:
        db.add(WhatsAppMessage(
            csp_id="1A720001", csp_name="Day Filter", phone="919800000072",
            kind="data_request", send_status="sent", job_id=label,
            sent_at=at))
        db.add(EmailMessage(
            csp_id="1A720001", csp_name="Day Filter", to_email="d@example.com",
            kind="details_request", subject=label, send_status="sent",
            track_token=uuid.uuid4().hex, sent_at=at))
    await db.commit()
    yield
    await db.execute(text("TRUNCATE whatsapp_messages, email_messages"))
    await db.commit()


async def test_whatsapp_messages_by_the_day_sent(client, whatsapps):
    url = "/api/admin/whatsapp-messages"
    body = (await client.get(f"{url}?date_from=2026-11-20&date_to=2026-11-20",
                             headers=ADMIN)).json()
    assert {r["job_id"] for r in body["rows"]} == {
        "20th, 00:00 IST", "20th, 23:59 IST"}
    assert body["summary"]["data_request"]["total"] == 2, "the counts follow"

    body = (await client.get(f"{url}?date_from=2026-11-20", headers=ADMIN)).json()
    assert {r["job_id"] for r in body["rows"]} == {
        "20th, 00:00 IST", "20th, 23:59 IST", "21st, 00:00 IST"}

    # A day long ago: the dates take the place of the default 30 days.
    body = (await client.get(f"{url}?date_from=2025-01-10&date_to=2025-01-10",
                             headers=ADMIN)).json()
    assert [r["job_id"] for r in body["rows"]] == ["old"]

    r = await client.get(f"{url}?date_from=yesterday", headers=ADMIN)
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"]
    r = await client.get(f"{url}?date_from=2026-11-21&date_to=2026-11-20",
                         headers=ADMIN)
    assert r.status_code == 400 and "before" in r.json()["detail"]


async def test_emails_by_the_day_sent(client, whatsapps):
    url = "/api/admin/email-messages"
    body = (await client.get(f"{url}?date_from=2026-11-20&date_to=2026-11-20",
                             headers=ADMIN)).json()
    assert {m["subject"] for m in body["messages"]} == {
        "20th, 00:00 IST", "20th, 23:59 IST"}
    assert body["total"] == 2
    assert body["counts"]["details_request"]["sent"] == 2, "the counts follow"

    body = (await client.get(f"{url}?date_to=2026-11-19", headers=ADMIN)).json()
    assert {m["subject"] for m in body["messages"]} == {"19th, 23:59 IST", "old"}

    body = (await client.get(url, headers=ADMIN)).json()
    assert body["total"] == 5, "no day asked: every email"

    r = await client.get(f"{url}?date_to=2026-13-01", headers=ADMIN)
    assert r.status_code == 400 and "date_to" in r.json()["detail"]


# ---- the RM dashboard: the day last contacted -------------------------------

CODES = ("1A720011", "1A720012", "1A720013")


@pytest.fixture
async def rm_world(db):
    for model in (WhatsAppMessage, EmailMessage):
        await db.execute(delete(model).where(model.csp_id.in_(CODES)))
    common = dict(email="csp@example.com", address="1 Street",
                  rm_resolution=BY_SHEET, rm_email="rm.days@eko.co.in",
                  rm_name="Rm Days", dc="Dc Days", state="Bihar",
                  district="Patna", origin="new")
    for code, name in zip(CODES, ("Late On 19th", "Early On 20th", "Never")):
        db.add(CSPRecord(csp_id=code, csp_code=code, name=name, **common))
    # The first: an email late on the 19th. The second: a WhatsApp on the
    # 19th, then an email just after midnight on the 20th (its last contact).
    db.add(EmailMessage(csp_id=CODES[0], to_email="csp@example.com",
                        kind="details_request", send_status="sent",
                        track_token=uuid.uuid4().hex,
                        sent_at=TIMES["19th, 23:59 IST"]))
    db.add(WhatsAppMessage(csp_id=CODES[1], phone="919800000073",
                           kind="data_request", send_status="sent",
                           sent_at=TIMES["19th, 23:59 IST"]))
    db.add(EmailMessage(csp_id=CODES[1], to_email="csp@example.com",
                        kind="details_request", send_status="sent",
                        track_token=uuid.uuid4().hex,
                        sent_at=TIMES["20th, 00:00 IST"]))
    await db.commit()
    yield
    for model in (WhatsAppMessage, EmailMessage):
        await db.execute(delete(model).where(model.csp_id.in_(CODES)))
    await db.commit()


async def test_rm_dashboard_by_the_day_last_contacted(client, rm_world):
    async def ids(query):
        r = await client.get(f"/api/rm-dashboard/pending?rm=Rm%20Days&{query}",
                             headers=RM)
        assert r.status_code == 200, r.text
        return sorted(c["csp_id"] for c in r.json()["csps"]), r.json()

    got, _ = await ids("")
    assert got == list(CODES), "no day asked: every CSP, never contacted too"
    got, body = await ids("date_from=2026-11-20&date_to=2026-11-20")
    assert got == [CODES[1]]
    assert body["summary"]["left"] == 1, "the counts follow"
    got, _ = await ids("date_from=2026-11-19&date_to=2026-11-19")
    assert got == [CODES[0]], "the second was contacted later, on the 20th"
    got, _ = await ids("date_to=2026-11-20")
    assert got == [CODES[0], CODES[1]], "never contacted has no day"

    r = await client.get("/api/rm-dashboard/pending.csv?rm=Rm%20Days"
                         "&date_from=2026-11-20&date_to=2026-11-20", headers=RM)
    assert r.status_code == 200
    assert "Early On 20th" in r.text and "Late On 19th" not in r.text

    r = await client.get("/api/rm-dashboard/pending?date_from=2026/11/20",
                         headers=RM)
    assert r.status_code == 400 and "date_from" in r.json()["detail"]
    r = await client.get("/api/rm-dashboard/pending.csv?date_from=2026-11-21"
                         "&date_to=2026-11-20", headers=RM)
    assert r.status_code == 400
