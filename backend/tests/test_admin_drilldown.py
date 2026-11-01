"""The dashboard drill-downs: views, date filter, pagination and CSV export.

These back the numbers an admin clicks on, so the rule they must keep is that
a drill-down returns exactly the CSPs its number counted — the filtering lives
in one place (_drill_rows) for that reason.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.csp_record import CSPRecord
from app.models.enums import AccountStatus, UserRole
from app.models.rm_alert import MISSING_DATA, OPEN, RMAlert
from app.models.user import User
from app.services import jwt_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN = "admin.drill@eko.co.in"
RM = "rm.drill@eko.co.in"


def _headers(email: str, role: UserRole) -> dict:
    token = jwt_service.create_access_token(
        {"sub": email, "role": role.value, "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(db):
    db.add(User(email=ADMIN, name="Admin", mobile="9876543210",
                role=UserRole.ADMIN, account_status=AccountStatus.ACTIVE,
                password_hash="x"))
    await db.commit()
    return _headers(ADMIN, UserRole.ADMIN)


@pytest.fixture
async def population(db):
    """Five CSPs: three new (one alerted, one complete), two existing."""
    old = datetime.now(timezone.utc) - timedelta(days=10)
    # Every field required_fields() names, so this CSP counts as complete.
    complete = dict(
        csp_code="TC", name="Complete Csp", email="csp@example.com",
        mobile="9876543210", address="1 Test Street", district="Testdistrict",
        state="Teststate", lho="Patna", ao="Test Ao", rbo_name="Test Rbo",
        branch_name="Main", branch_code="00001",
        asm_name="Test Asm", asm_email="asm@eko.co.in", asm_contact="9000000000",
        photo_url="C:/nowhere/photo.jpg", rm_name="Drill Rm",
        certificate_date=old.date(),
    )
    db.add(CSPRecord(csp_id="D-NEW-1", source_row_identifier="D-NEW-1",
                     origin="new", circle_head="Asha Rao", **complete))
    db.add(CSPRecord(csp_id="D-NEW-2", source_row_identifier="D-NEW-2",
                     origin="new", name="Sparse One", district="Testdistrict"))
    db.add(CSPRecord(csp_id="D-NEW-3", source_row_identifier="D-NEW-3",
                     origin="new", name="Alerted One"))
    db.add(CSPRecord(csp_id="D-OLD-1", source_row_identifier="D-OLD-1",
                     origin="baseline", name="Old One"))
    db.add(CSPRecord(csp_id="D-OLD-2", source_row_identifier="D-OLD-2",
                     origin="baseline", name="Old Two"))
    db.add(RMAlert(csp_id="D-NEW-3", kind=MISSING_DATA, status=OPEN,
                   message="No photo"))
    await db.commit()


async def test_a_view_returns_only_that_tile(client, admin_headers, population):
    body = (await client.get("/api/admin/csp-list?view=new",
                             headers=admin_headers)).json()
    assert {c["csp_id"] for c in body["csps"]} == {"D-NEW-1", "D-NEW-2", "D-NEW-3"}

    body = (await client.get("/api/admin/csp-list?view=existing",
                             headers=admin_headers)).json()
    assert {c["csp_id"] for c in body["csps"]} == {"D-OLD-1", "D-OLD-2"}


async def test_awaiting_rm_lists_the_alerted_csps(client, admin_headers, population):
    body = (await client.get("/api/admin/csp-list?view=awaiting_rm",
                             headers=admin_headers)).json()
    assert [c["csp_id"] for c in body["csps"]] == ["D-NEW-3"]


async def test_details_views_split_the_population(client, admin_headers, population):
    fetched = (await client.get("/api/admin/csp-list?view=details_fetched",
                                headers=admin_headers)).json()
    missing = (await client.get("/api/admin/csp-list?view=details_missing",
                                headers=admin_headers)).json()
    assert fetched["total"] + missing["total"] == 5
    assert "D-NEW-2" in {c["csp_id"] for c in missing["csps"]}
    # The two halves never overlap.
    assert not ({c["csp_id"] for c in fetched["csps"]}
                & {c["csp_id"] for c in missing["csps"]})


async def test_the_tile_and_its_drilldown_agree(client, admin_headers, population):
    metrics = (await client.get("/api/admin/csp-metrics",
                                headers=admin_headers)).json()
    for tile, view in (("details_fetched", "details_fetched"),
                       ("details_missing", "details_missing"),
                       ("awaiting_rm", "awaiting_rm")):
        drill = (await client.get(f"/api/admin/csp-list?view={view}",
                                  headers=admin_headers)).json()
        assert metrics["totals"][tile] == drill["total"], tile


async def test_an_unknown_view_is_rejected(client, admin_headers):
    r = await client.get("/api/admin/csp-list?view=whatever",
                         headers=admin_headers)
    assert r.status_code == 400
    assert "Unknown view" in r.json()["detail"]


async def test_pagination_walks_the_whole_set(client, admin_headers, population):
    seen, page = [], 1
    while True:
        body = (await client.get(
            f"/api/admin/csp-list?page={page}&page_size=2",
            headers=admin_headers)).json()
        assert body["total"] == 5 and body["pages"] == 3
        seen += [c["csp_id"] for c in body["csps"]]
        if page >= body["pages"]:
            break
        page += 1
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_page_zero_is_rejected(client, admin_headers):
    r = await client.get("/api/admin/csp-list?page=0", headers=admin_headers)
    assert r.status_code == 400


IST = timezone(timedelta(hours=5, minutes=30))


async def _made(db, csp_id, when, doc="csp_id_card"):
    """A stored PDF made at `when` (No. 171: the date filter is the day the
    documents were made)."""
    import hashlib

    from app.models.enums import DocumentFormat, DocumentType
    from app.models.stored_document import StoredDocument
    from tests.conftest import MINIMAL_PDF

    db.add(StoredDocument(
        csp_id=csp_id, document_type=DocumentType(doc),
        file_format=DocumentFormat.PDF, version=1, filename=f"{doc}.pdf",
        content_type="application/pdf", file_data=MINIMAL_PDF,
        file_size=len(MINIMAL_PDF),
        checksum=hashlib.sha256(MINIMAL_PDF + csp_id.encode() + doc.encode()).hexdigest(),
        created_at=when))
    await db.commit()


async def test_the_date_filter_is_the_day_documents_were_made(
        client, admin_headers, population, db):
    today = datetime.now(IST).date()
    await _made(db, "D-NEW-1", datetime.now(timezone.utc))
    await _made(db, "D-OLD-1", datetime.now(timezone.utc) - timedelta(days=3))

    def q(a, b):
        return f"date_from={a.isoformat()}&date_to={b.isoformat()}"

    body = (await client.get(f"/api/admin/csp-list?{q(today, today)}",
                             headers=admin_headers)).json()
    assert [c["csp_id"] for c in body["csps"]] == ["D-NEW-1"],         "only CSPs whose documents were made that day"

    three = today - timedelta(days=3)
    body = (await client.get(f"/api/admin/csp-list?{q(three, three)}",
                             headers=admin_headers)).json()
    assert [c["csp_id"] for c in body["csps"]] == ["D-OLD-1"]

    body = (await client.get(f"/api/admin/csp-list?{q(three, today)}",
                             headers=admin_headers)).json()
    assert body["total"] == 2, "a From-To range covers both ends"

    body = (await client.get("/api/admin/csp-list", headers=admin_headers)).json()
    assert body["total"] == 5, "no dates: every CSP"


async def test_the_counts_follow_the_same_days(client, admin_headers, population, db):
    today = datetime.now(IST).date().isoformat()
    await _made(db, "D-NEW-1", datetime.now(timezone.utc))
    await _made(db, "D-NEW-1", datetime.now(timezone.utc) - timedelta(days=5), "bcp")
    m = (await client.get(f"/api/admin/csp-metrics?date_from={today}&date_to={today}",
                          headers=admin_headers)).json()
    assert m["totals"]["csps"] == 1
    made = {d["document_type"]: d["generated"] for d in m["documents"]}
    assert made["csp_id_card"] == 1 and made["bcp"] == 0,         "a document made on another day is not counted"
    # The tile and the list behind it agree.
    drill = (await client.get(
        f"/api/admin/csp-list?document_type=csp_id_card&date_from={today}&date_to={today}",
        headers=admin_headers)).json()
    assert drill["total"] == 1


async def test_a_day_is_counted_in_india_time(client, admin_headers, population, db):
    """00:30 in India is still the previous day in UTC."""
    day = datetime(2026, 10, 20, tzinfo=IST).date()
    await _made(db, "D-NEW-2", datetime(2026, 10, 20, 0, 30, tzinfo=IST))
    body = (await client.get(
        f"/api/admin/csp-list?date_from={day}&date_to={day}",
        headers=admin_headers)).json()
    assert [c["csp_id"] for c in body["csps"]] == ["D-NEW-2"]


async def test_a_malformed_date_is_rejected(client, admin_headers):
    r = await client.get("/api/admin/csp-list?date_from=28-09-2026",
                         headers=admin_headers)
    assert r.status_code == 400
    r = await client.get(
        "/api/admin/csp-list?date_from=2026-09-28&date_to=2026-09-01",
        headers=admin_headers)
    assert r.status_code == 400


async def test_the_csv_export_matches_the_view(client, admin_headers, population):
    r = await client.get("/api/admin/csp-list.csv?view=existing",
                         headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in r.headers["content-disposition"]

    lines = [line for line in r.text.splitlines() if line.strip()]
    assert lines[0].startswith("csp_id,name,origin")
    assert len(lines) == 3          # header + the two baseline CSPs
    assert "D-OLD-1" in r.text and "D-NEW-1" not in r.text


async def test_the_csv_is_not_paged(client, admin_headers, population):
    """Export means every matching row, not the page on screen."""
    r = await client.get("/api/admin/csp-list.csv?page_size=2",
                         headers=admin_headers)
    assert len([line for line in r.text.splitlines() if line.strip()]) == 6


async def test_an_rm_cannot_reach_the_drilldown(client, db, population):
    db.add(User(email=RM, name="Rm", mobile="9876543211", role=UserRole.RM,
                account_status=AccountStatus.ACTIVE, password_hash="x"))
    await db.commit()
    for path in ("/api/admin/csp-list", "/api/admin/csp-list.csv",
                 "/api/admin/csp-metrics"):
        r = await client.get(path, headers=_headers(RM, UserRole.RM))
        assert r.status_code == 403, path


# ---- per-document delivery drill-downs ---------------------------------

async def test_every_delivery_number_matches_its_list(client, admin_headers,
                                                      population):
    """Each Mailed / Pending / Failed count opens exactly those CSPs."""
    metrics = (await client.get("/api/admin/csp-metrics",
                                headers=admin_headers)).json()
    for row in metrics["documents"]:
        doc = row["document_type"]
        for bucket in ("mailed", "pending", "failed"):
            drill = (await client.get(
                f"/api/admin/csp-list?document_type={doc}&delivery={bucket}",
                headers=admin_headers)).json()
            assert drill["total"] == row[bucket], f"{doc}/{bucket}"


async def test_the_delivery_buckets_do_not_overlap(client, admin_headers,
                                                   population):
    seen = []
    for bucket in ("mailed", "pending", "failed"):
        body = (await client.get(
            f"/api/admin/csp-list?document_type=csp_id_card&delivery={bucket}",
            headers=admin_headers)).json()
        seen += [c["csp_id"] for c in body["csps"]]
    assert len(seen) == len(set(seen))


async def test_an_unknown_delivery_is_rejected(client, admin_headers):
    r = await client.get(
        "/api/admin/csp-list?document_type=csp_id_card&delivery=posted",
        headers=admin_headers)
    assert r.status_code == 400
    assert "Unknown delivery" in r.json()["detail"]


async def test_delivery_needs_a_document_type(client, admin_headers):
    r = await client.get("/api/admin/csp-list?delivery=mailed",
                         headers=admin_headers)
    assert r.status_code == 400
