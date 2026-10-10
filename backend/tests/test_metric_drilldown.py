# -*- coding: utf-8 -*-
"""Clicking a number shows exactly what it counted.

The whole value of a drillable tile rests on one property: the list it
opens has the same length as the number on it. A tile that says 2 and
opens three rows is worse than a tile that does not open at all, because
it makes every other figure on the screen suspect.

So the central test here walks every drillable metric, computes it the way
the dashboard does, opens it the way a click does, and insists the two
agree — on an empty workspace and on one with records in it. A metric
added later without a matching drill-down fails too.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.services import field_ownership as fo
from app.services import metric_compute, metric_drilldown, metric_registry

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _csp(csp_id, **overrides):
    values = dict(
        csp_id=csp_id, csp_code=csp_id, name=f"Name {csp_id}",
        mobile="9876543210", email=f"{csp_id}@example.com", gender="Male",
        address="1 Test Street", district="Testdistrict", state="Teststate",
        photo_url="/tmp/photo.png",
        branch_name="Testbranch", branch_code="BR01", branch_contact="9000000",
        ao="Testao", dc="Testdc", dc_email="dc@example.com",
        dc_contact="9000001", lho="Testlho", rm_name="Testrm",
        asm_name="Testasm", asm_email="asm@example.com",
        asm_contact="9000002", rbo_name="Testrbo", rbo_contact="9000003",
        certificate_date=date(2026, 3, 4),
    )
    values.update(overrides)
    return CSPRecord(**values)


# ---- the property that matters ------------------------------------------

# verification.documents_held is a table of four rows, not one number, so
# it has no single count to compare against. It is drilled per row and is
# checked by its own tests further down.
def _single_number_metrics():
    return sorted(metric_drilldown.drillable_keys()
                  - metric_drilldown._TAKES_A_FIELD)


async def test_every_drillable_number_opens_a_list_of_that_length(db):
    """On an empty workspace every count is zero and every list is empty."""
    for key in _single_number_metrics():
        value = (await metric_compute.compute(key, db))["value"]
        opened = await metric_drilldown.records_for(key, db)
        assert opened["count"] == value, (
            f"{key}: the tile shows {value} but opens {opened['count']} rows")


async def test_the_number_and_the_list_agree_with_records_present(db):
    """The same property, with data that makes the counts non-zero."""
    db.add_all([
        _csp("DRILL001"),                       # complete
        _csp("DRILL002", photo_url=""),         # missing their photo
        _csp("DRILL003", rbo_name=""),          # missing a hierarchy field
    ])
    await db.flush()

    for key in _single_number_metrics():
        value = (await metric_compute.compute(key, db))["value"]
        opened = await metric_drilldown.records_for(key, db)
        assert opened["count"] == value, (
            f"{key}: the tile shows {value} but opens {opened['count']} rows")


async def test_a_metric_that_claims_to_be_drillable_can_be_drilled(db):
    """The registry's promise and the implementation cannot drift apart.

    `drillable=True` on a metric is what makes the dashboard invite a
    click. If nothing here answers that click the card 404s.
    """
    promised = {m["key"] for group in metric_registry.groups()
                for m in group["metrics"] if m.get("drillable")}
    implemented = metric_drilldown.drillable_keys()

    assert promised - implemented == set(), (
        "these metrics say they are drillable but open nothing: "
        f"{sorted(promised - implemented)}")
    assert implemented - promised == set(), (
        "these metrics can be drilled but are not offered as drillable: "
        f"{sorted(implemented - promised)}")


# ---- what the list actually says ----------------------------------------

async def test_a_completeness_list_names_the_blank_fields(db):
    """'Missing own details' is only half an answer without which ones."""
    db.add(_csp("DRILL010", photo_url="", email=""))
    await db.flush()

    opened = await metric_drilldown.records_for(
        "data.missing_csp_details", db)
    row = next(r for r in opened["rows"] if r["csp_code"] == "DRILL010")

    assert "missing" in row, "the row does not say what is missing"
    assert fo.label_of("photo_url") in row["missing"]
    assert fo.label_of("email") in row["missing"]
    # A field that is present must not be listed as missing.
    assert fo.label_of("mobile") not in row["missing"]


async def test_the_columns_describe_the_rows(db):
    """The table is drawn from what the server sends, so they must match."""
    db.add(_csp("DRILL020", photo_url=""))
    await db.flush()

    for key in sorted(metric_drilldown.drillable_keys()):
        field = (fo.DOCUMENTS_HELD[0]
                 if key in metric_drilldown._TAKES_A_FIELD else None)
        opened = await metric_drilldown.records_for(key, db, field)
        keys = {c["key"] for c in opened["columns"]}
        assert keys, f"{key}: no columns"
        for row in opened["rows"]:
            missing = keys - set(row)
            assert not missing, (
                f"{key}: a row is missing the columns {sorted(missing)}")


async def test_an_unknown_metric_does_not_open(db):
    """404, not an empty list: 'nothing matched' and 'this does not open'
    are different answers and must not look the same."""
    with pytest.raises(KeyError):
        await metric_drilldown.records_for("not.a.metric", db)


async def test_a_non_drillable_metric_does_not_open(db):
    """documents.by_type is a breakdown, not a number with records."""
    assert metric_registry.exists("documents.by_type")
    with pytest.raises(KeyError):
        await metric_drilldown.records_for("documents.by_type", db)


# ---- who may look -------------------------------------------------------

async def test_the_drill_down_needs_an_admin(client):
    """A drill-down returns CSP names and branches: it is not public."""
    response = await client.get(
        "/api/admin/dashboards/metrics/data.missing_photo/records")
    assert response.status_code in (401, 403), (
        "an unauthenticated request listed CSP records")


# ---- documents CSPs already hold ----------------------------------------
#
# This one is a table, not a number, so it drills per row. It also has
# three answers rather than two: the tile used to show only the Yes count,
# which read as "nobody has an ID Card" when the truth was "one said they
# do not and two were never asked".

async def test_yes_no_and_unanswered_account_for_everybody(db):
    db.add_all([
        _csp("HELD001", has_id_card="Yes"),
        _csp("HELD002", has_id_card="No"),
        _csp("HELD003"),                      # never asked: None
    ])
    await db.flush()

    table = await metric_compute.compute("verification.documents_held", db)
    row = next(r for r in table["rows"] if r["key"] == "has_id_card")

    assert row["yes"] == 1
    assert row["no"] == 1
    assert row["unanswered"] == 1
    assert row["yes"] + row["no"] + row["unanswered"] == 3, (
        "the three answers must account for every CSP")


async def test_never_asked_is_not_counted_as_no(db):
    """The distinction the old tile lost."""
    db.add(_csp("HELD010"))                   # no answer at all
    await db.flush()

    table = await metric_compute.compute("verification.documents_held", db)
    row = next(r for r in table["rows"] if r["key"] == "has_bcp")
    assert row["no"] == 0, "a CSP who was never asked was counted as No"
    assert row["unanswered"] == 1


async def test_opening_a_document_row_shows_who_said_what(db):
    db.add_all([
        _csp("HELD020", has_csp_certificate="Yes"),
        _csp("HELD021", has_csp_certificate="No"),
        _csp("HELD022"),
    ])
    await db.flush()

    opened = await metric_drilldown.records_for(
        "verification.documents_held", db, "has_csp_certificate")
    answers = {r["csp_code"]: r["answer"] for r in opened["rows"]}

    assert answers["HELD020"] == "Yes"
    assert answers["HELD021"] == "No"
    assert answers["HELD022"] == "Not answered"


async def test_the_list_agrees_with_the_row_it_opened(db):
    """Same promise as the tiles: the counts and the list must match."""
    db.add_all([
        _csp("HELD030", has_training_certificate="Yes"),
        _csp("HELD031", has_training_certificate="No"),
        _csp("HELD032"),
    ])
    await db.flush()

    table = await metric_compute.compute("verification.documents_held", db)
    for row in table["rows"]:
        opened = await metric_drilldown.records_for(
            "verification.documents_held", db, row["key"])
        counted = {"Yes": 0, "No": 0, "Not answered": 0}
        for r in opened["rows"]:
            counted[r["answer"]] += 1
        assert counted["Yes"] == row["yes"], row["key"]
        assert counted["No"] == row["no"], row["key"]
        assert counted["Not answered"] == row["unanswered"], row["key"]


async def test_yes_comes_first_in_the_list(db):
    """Who has the document is the question being asked."""
    db.add_all([
        _csp("HELD040"),
        _csp("HELD041", has_bcp="No"),
        _csp("HELD042", has_bcp="Yes"),
    ])
    await db.flush()

    opened = await metric_drilldown.records_for(
        "verification.documents_held", db, "has_bcp")
    assert [r["answer"] for r in opened["rows"]][:3] == [
        "Yes", "No", "Not answered"]


async def test_a_document_row_must_say_which_document(db):
    """Without a row there is no single list, and saying so beats guessing."""
    with pytest.raises(ValueError):
        await metric_drilldown.records_for("verification.documents_held", db)


async def test_an_arbitrary_column_cannot_be_read_through_the_field(db):
    """`field` reaches getattr, so it is checked against the questions."""
    db.add(_csp("HELD050"))
    await db.flush()

    for sneaky in ("password_hash", "email", "photo_url", "id"):
        with pytest.raises(KeyError):
            await metric_drilldown.records_for(
                "verification.documents_held", db, sneaky)
