"""The golden cases: fixed CSP situations with their known right answers.

PROJECT-REGISTER No. 146. tests/golden/cases.json holds each situation
(made-up people and codes, real situations from Eko's data) and the answer
the business rules give. This file runs every one through the real rule
code — the same functions the sync, the jobs and the forms call:

  documents  ko_level          — KO or Sub-KO, which documents (No. 57)
  info       InfoDirectory     — AO / RBO / DC / ASM / LHO / State, and why
  rm         rm_resolution     — who owns the CSP (No. 12)
  hold       source_sheets     — when nothing may be sent (No. 121)
  mobile     alert_composer    — the WhatsApp number (No. 7, No. 144)
  address    zoho_client       — the address from a Zoho Lead (No. 131)
  ask        data_request      — what the CSP is asked (No. 128, No. 143)
  form       field_ownership   — what their form shows (No. 130)
  channel    message_sender    — WhatsApp or email (No. 7)
  go_live    source_sheets.run — old or new, over several runs (No. 121, 145)

Run before every deploy (DEPLOY.md):

    PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q tests/test_golden_cases.py

A failure names the case. Either the change broke a business outcome, or
the rule really changed — then the case is updated with the user's OK, in
the same commit, and the register says so.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.enums import DocumentType
from app.services import (alert_composer, data_request_service,
                          field_ownership, ko_level, message_sender,
                          rm_resolution, source_sheets, zoho_client)
from app.services.info_directory import InfoDirectory
from tests.test_source_sheets import (KO, _run, _state, calling_row,
                                      lead_row, world)  # noqa: F401

GOLDEN = json.loads((Path(__file__).parent / "golden" / "cases.json")
                    .read_text(encoding="utf-8"))
CASES = GOLDEN["cases"]
INFO = InfoDirectory.from_rows(GOLDEN["info_tab"])

on_loop = pytest.mark.asyncio(loop_scope="session")


def _cases(*kinds):
    return [pytest.param(c, id=f"{c['id']} {c['title']}")
            for c in CASES if c["kind"] in kinds]


# ---- the file itself ----------------------------------------------------

RUNNERS = {"documents", "info", "rm", "hold", "mobile", "address", "ask",
           "form", "channel", "go_live"}


def test_the_golden_file_is_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    assert len(CASES) >= 50
    for c in CASES:
        assert {"id", "kind", "rule", "title", "input", "expect"} <= set(c), c
        assert c["kind"] in RUNNERS, f"{c['id']}: no runner for {c['kind']}"


def test_the_golden_file_holds_no_real_contact_details():
    """Made-up data only: every email is @example.com, every mobile is in
    the 98123 / 9000000 test ranges."""
    import re
    text = json.dumps(GOLDEN)
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    assert all(e.endswith("@example.com") for e in emails), emails
    for number in re.findall(r"\b\d{10}\b", text):
        assert number.startswith(("98123", "9000000")), number


# ---- pure rules -----------------------------------------------------------

@pytest.mark.parametrize("case", _cases("documents"))
def test_documents(case):
    code, expect = case["input"]["code"], case["expect"]
    assert ko_level.level_of(code) == expect["level"]
    allowed = ko_level.allowed_documents(code, list(DocumentType))
    assert [d.value for d in allowed] == expect["documents"]
    if "parent" in expect:
        assert ko_level.parent_ko_code(code) == expect["parent"]


@pytest.mark.parametrize("case", _cases("info"))
def test_info(case):
    why = {}
    filled = INFO.fill_missing(dict(case["input"]), why=why)
    expect = case["expect"]
    if expect.get("filled") == {}:
        assert filled == {}, filled
    for field, value in (expect.get("filled") or {}).items():
        assert filled.get(field) == value, (field, filled)
    for field in expect.get("not_filled", []):
        assert field not in filled, (field, filled)
    for field, reason in (expect.get("why") or {}).items():
        assert why.get(field) == reason, (field, why)
    assert set(why) == set(filled), "every filled value says why"


@pytest.mark.parametrize("case", _cases("rm"))
def test_rm(case):
    people = [SimpleNamespace(name=n, email=e)
              for n, e in GOLDEN["authorized_rms"].items()]
    email, how = rm_resolution.resolve_rm(
        dict(case["input"]), rm_resolution.build_name_to_email(people), {},
        info=INFO, authorized_emails=set(GOLDEN["authorized_rms"].values()))
    assert (email, how) == (case["expect"]["rm_email"], case["expect"]["how"])


@pytest.mark.parametrize("case", _cases("hold"))
def test_hold(case):
    reason = source_sheets.hold_reason(**case["input"])
    expect = case["expect"]
    assert (reason is not None) == expect["held"], reason
    if "starts_with" in expect:
        assert reason.startswith(expect["starts_with"]), reason


@pytest.mark.parametrize("case", _cases("mobile"))
def test_mobile(case):
    assert alert_composer.normalize_mobile(case["input"]["mobile"]) \
        == case["expect"]["whatsapp"]


@pytest.mark.parametrize("case", _cases("address"))
def test_address(case):
    assert zoho_client.lead_address(case["input"]) == case["expect"]["address"]


def _record(fields: dict, photo_file: str) -> SimpleNamespace:
    """A CSP as the rules read it. No csp_id: the photo is then judged by
    whether photo_url is a file, without looking in the database."""
    values = {f: "" for f in field_ownership.CSP_OWNED + field_ownership.ORG_OWNED}
    fields = dict(fields)
    has_photo = fields.pop("photo", False)
    values.update(fields)
    values["photo_url"] = photo_file if has_photo else ""
    return SimpleNamespace(**values)


@pytest.mark.parametrize("case", _cases("ask"))
def test_ask(case, tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"not really a photo")
    record = _record(case["input"]["record"], str(photo))
    assert data_request_service.fields_to_ask(record) \
        == case["expect"]["asked"]


@pytest.mark.parametrize("case", _cases("form"))
def test_form(case, tmp_path):
    record = _record(case["input"]["record"], "")
    assert field_ownership.request_fields(
        record, verify=case["input"]["verify"]) == case["expect"]["fields"]


@pytest.mark.parametrize("case", _cases("channel"))
def test_channel(case):
    i = case["input"]
    to, via = message_sender.address_for(
        SimpleNamespace(mobile=i["mobile"], email=i["email"]), i["channel"])
    assert (to, via) == (case["expect"]["to"], case["expect"]["via"])


# ---- old or new, over several runs of the Calling / Lead job ------------

@on_loop
@pytest.mark.parametrize("case", _cases("go_live"))
async def test_go_live(case, world):  # noqa: F811
    i, expect = case["input"], case["expect"]
    world.data[KO] = [{"CSP Code": c} for c in i.get("in_cspdata", [])]
    imported_new, became_new = [], []
    for run in i["runs"]:
        world.calling = [calling_row(r["code"], f"Csp {r['code']}",
                                     r.get("status", "Active"))
                         for r in run["calling"]]
        world.lead = [lead_row(r["code"], f"Csp {r['code']}", r["remarks"])
                      for r in run["lead"]]
        summary = _run(world)
        imported_new += summary.imported_new
        became_new += summary.became_new

    for code, origin in (expect.get("imported_as") or {}).items():
        assert _state(world, code).imported_as == origin, code
    for code, held in (expect.get("held") or {}).items():
        assert (_state(world, code).hold_reason is not None) == held, code
    if "imported_new" in expect:
        assert imported_new == expect["imported_new"]
    if "became_new" in expect:
        assert became_new == expect["became_new"]
