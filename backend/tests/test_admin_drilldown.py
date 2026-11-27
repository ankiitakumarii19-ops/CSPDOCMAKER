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

    doc = "document_type=csp_id_card&"
    body = (await client.get(f"/api/admin/csp-list?{doc}{q(today, today)}",
                             headers=admin_headers)).json()
    assert [c["csp_id"] for c in body["csps"]] == ["D-NEW-1"],         "only CSPs whose documents were made that day"

    three = today - timedelta(days=3)
    body = (await client.get(f"/api/admin/csp-list?{doc}{q(three, three)}",
                             headers=admin_headers)).json()
    assert [c["csp_id"] for c in body["csps"]] == ["D-OLD-1"]

    body = (await client.get(f"/api/admin/csp-list?{doc}{q(three, today)}",
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
    # No. 272: the cards count what happened that day - without the
    # Calling / Lead sheets, New = added to the app that day (all three
    # population CSPs were), Existing = confirmed their details that day.
    assert (m["totals"]["new"], m["totals"]["existing"]) == (3, 0)
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
        f"/api/admin/csp-list?document_type=csp_id_card&date_from={day}"
        f"&date_to={day}", headers=admin_headers)).json()
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


# ---- No. 271: the cards count from the Calling and Lead raw data sheets -----

async def test_the_cards_count_active_and_go_live_done_each_code_once(
        client, admin_headers, db):
    """The owner, 27 Nov 2026: Existing = Active in the Calling sheet; New =
    Go Live Done in the Lead raw data sheet; a code in both is New and
    counted once; Inactive / no status / a Lead not live / only in CSPDATA
    are not counted."""
    from app.models.source_sheet import SourceSheetState as St
    rows = {
        # code: (in_calling, calling_status, in_lead, lead_live, origin)
        "1A971001": (True, "Active", False, False, "baseline"),
        "1A971002": (True, "Active", True, True, "new"),        # both -> new
        "1A971003": (False, None, True, True, "new"),
        "1A971004": (True, "Inactive", False, False, "baseline"),
        "1A971005": (True, None, False, False, "baseline"),
        "1A971006": (False, None, True, False, "baseline"),     # not live
        "1A971007": (True, " active ", True, False, "baseline"),
    }
    for code, (in_c, status, in_l, live, origin) in rows.items():
        db.add(St(csp_code=code, in_calling=in_c, calling_status=status,
                  in_lead=in_l, lead_live=live,
                  # went live this week: within No. 272's one month
                  went_live_at=(datetime.now(timezone.utc) - timedelta(days=5)
                                if live else None)))
        db.add(CSPRecord(csp_id=code, source_row_identifier=code,
                         origin=origin, name=f"Csp {code}"))
    db.add(CSPRecord(csp_id="1A971008", source_row_identifier="1A971008",
                     origin="baseline", name="Only In Cspdata"))
    await db.commit()

    totals = (await client.get("/api/admin/csp-metrics",
                               headers=admin_headers)).json()["totals"]
    assert (totals["csps"], totals["new"], totals["existing"]) == (4, 2, 2)

    async def client_get(url):
        return (await client.get(url, headers=admin_headers)).json()

    assert {c["csp_id"] for c in (await client_get(
        "/api/admin/csp-list?view=new"))["csps"]} == {"1A971002", "1A971003"}
    assert {c["csp_id"] for c in (await client_get(
        "/api/admin/csp-list?view=existing"))["csps"]} == {"1A971001",
                                                            "1A971007"}
    assert {c["csp_id"] for c in (await client_get(
        "/api/admin/csp-list"))["csps"]} == {"1A971001", "1A971002",
                                             "1A971003", "1A971007"}


# ---- No. 272: one month, and every card follows the day ----------------------

async def _sheet_csp(db, code, *, in_calling=False, status=None, live=False,
                     went_live=None, origin="baseline"):
    from app.models.source_sheet import SourceSheetState as St
    db.add(St(csp_code=code, in_calling=in_calling, calling_status=status,
              in_lead=live, lead_live=live, went_live_at=went_live))
    db.add(CSPRecord(csp_id=code, source_row_identifier=code, origin=origin,
                     name=f"Csp {code}"))


def test_months_before_is_calendar_months():
    from app.routers.admin_router import _months_before
    assert _months_before(datetime(2026, 5, 31), 3) == datetime(2026, 2, 28)
    assert _months_before(datetime(2026, 1, 15), 3) == datetime(2025, 10, 15)


async def test_a_lead_in_the_calling_sheet_is_old_after_3_months(
        client, admin_headers, db):
    now = datetime.now(timezone.utc)
    await _sheet_csp(db, "1A972001", in_calling=True, status="Active",
                     live=True, went_live=now - timedelta(days=80),
                     origin="new")      # under 3 months: still New
    await _sheet_csp(db, "1A972002", in_calling=True, status="Active",
                     live=True, went_live=now - timedelta(days=100),
                     origin="new")
    await _sheet_csp(db, "1A972003", in_calling=True, status="Active",
                     live=True, went_live=None)        # live before 21 Oct
    await _sheet_csp(db, "1A972004", live=True, origin="new",
                     went_live=now - timedelta(days=100))   # Lead only
    await _sheet_csp(db, "1A972005", in_calling=True, status="Inactive",
                     live=True, went_live=now - timedelta(days=100),
                     origin="new")
    await _sheet_csp(db, "1A972006", live=True)    # live before 21 Oct, Lead only
    await db.commit()

    async def ids(view):
        body = (await client.get(f"/api/admin/csp-list?view={view}",
                                 headers=admin_headers)).json()
        return {c["csp_id"] for c in body["csps"]}

    assert await ids("new") == {"1A972001", "1A972004"}
    assert await ids("existing") == {"1A972002", "1A972003", "1A972006"}, \
        "3 months after going live it is old; Inactive old ones not counted"
    totals = (await client.get("/api/admin/csp-metrics",
                               headers=admin_headers)).json()["totals"]
    assert (totals["new"], totals["existing"]) == (2, 3)

    # No. 273: the TYPE in the list is the dashboard's, not the record's.
    body = (await client.get("/api/admin/csp-list?view=existing",
                             headers=admin_headers)).json()
    assert {c["origin"] for c in body["csps"]} == {"baseline"}
    body = (await client.get("/api/admin/csp-list?view=new",
                             headers=admin_headers)).json()
    assert {c["origin"] for c in body["csps"]} == {"new"}


async def test_every_card_follows_the_day(client, admin_headers, db):
    from app.models.data_request import DataRequest
    now = datetime.now(timezone.utc)
    today = datetime.now(IST).date().isoformat()
    await _sheet_csp(db, "1A972011", live=True, went_live=now, origin="new")
    await _sheet_csp(db, "1A972012", live=True, origin="new",
                     went_live=now - timedelta(days=3))
    await _sheet_csp(db, "1A972013", in_calling=True, status="Active")
    await _sheet_csp(db, "1A972014", in_calling=True, status="Active")
    await db.flush()
    db.add(DataRequest(csp_id="1A972013", token_hash="t-272-a",
                       fields=["address"], status="answered",
                       expires_at=now + timedelta(days=3), answered_at=now,
                       answered_values={"address": "x"}))
    db.add(DataRequest(csp_id="1A972014", token_hash="t-272-b",
                       fields=["address"], status="answered",
                       expires_at=now + timedelta(days=3),
                       answered_at=now - timedelta(days=3),
                       answered_values={"address": "x"}))
    db.add(RMAlert(csp_id="1A972011", kind=MISSING_DATA, status=OPEN,
                   message="No photo", created_at=now))
    db.add(RMAlert(csp_id="1A972012", kind=MISSING_DATA, status=OPEN,
                   message="No photo", created_at=now - timedelta(days=3)))
    await db.commit()
    try:
        day = f"date_from={today}&date_to={today}"
        totals = (await client.get(f"/api/admin/csp-metrics?{day}",
                                   headers=admin_headers)).json()["totals"]
        assert (totals["csps"], totals["new"], totals["existing"],
                totals["awaiting_rm"]) == (2, 1, 1, 1)

        async def ids(view):
            body = (await client.get(f"/api/admin/csp-list?view={view}&{day}",
                                     headers=admin_headers)).json()
            return {c["csp_id"] for c in body["csps"]}
        assert await ids("new") == {"1A972011"}
        assert await ids("existing") == {"1A972013"}
        assert await ids("awaiting_rm") == {"1A972011"}

        all_days = (await client.get("/api/admin/csp-metrics",
                                     headers=admin_headers)).json()["totals"]
        assert (all_days["csps"], all_days["awaiting_rm"]) == (4, 2)
    finally:
        from sqlalchemy import text
        await db.execute(text("DELETE FROM data_requests WHERE token_hash "
                              "IN ('t-272-a', 't-272-b')"))
        await db.commit()
