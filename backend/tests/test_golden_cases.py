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
  verify     verification_auto — which value wins a difference (No. 171)
  message    manual_messages   — who may get a person's message (No. 174)
  access     csp_access        — which CSPs an RM may act on (No. 175)
  edit       csp_editor        — what an edit of a CSP may save (No. 175)
  link       message_sender    — the 3-day details link, by hand or not (No. 192-193)
  force      whatsapp_platform — a person's message always goes (No. 195)
  sender     WhatsApp screen   — who sent each message (No. 194)

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
from tests.test_verify_old_csps import _old, db  # noqa: F401

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
           "form", "channel", "go_live", "verify", "message", "access", "edit",
           "link", "force", "sender", "setting", "feature", "connection", "data"}


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


@pytest.mark.parametrize("case", _cases("verify"))
def test_verify(case):
    from app.services import verification_auto

    i = case["input"]
    field = i["field"]
    request = SimpleNamespace(
        id="golden", csp_id="1A990901",
        sheet_saved=[field] if i["reached"] else [],
        previous_values={field: i["before"]} if "before" in i else {})
    d = verification_auto.decide(request, field, i["answered"], i["current"])
    expect = case["expect"]
    if expect["decision"] is None:
        assert d is None, d
    else:
        assert (d.kind, d.after) == (expect["decision"], expect["value"])


@pytest.mark.parametrize("case", _cases("message"))
def test_message(case):
    from app.services import manual_messages

    i, expect = case["input"], case["expect"]
    why = manual_messages.refusal(i["on_hold"], i["existing"], i["kind"])
    assert (why is None) == expect["allowed"], why
    if not expect["allowed"]:
        assert expect["says"] in why


@pytest.mark.parametrize("case", _cases("access"))
def test_access(case):
    from app.services import csp_access

    i = case["input"]
    csp = SimpleNamespace(rm_email=i["csp_rm_email"], rm_resolution=i["rm_resolution"])
    user = {"role": i["role"], "sub": i["user"]}
    assert csp_access.can_access(csp, user) == case["expect"]["allowed"]


@pytest.mark.parametrize("case", _cases("edit"))
def test_edit(case):
    from app.services import csp_editor

    i, expect = case["input"], case["expect"]
    if "locked" in expect:
        assert (i["field"] in csp_editor.LOCKED) == expect["locked"]
        return
    assert csp_editor.check(i["column"], i["field"], i["value"]) == expect["problem"]


@pytest.mark.parametrize("case", _cases("force"))
def test_force(case, monkeypatch):
    from app.services import send_reason, whatsapp_platform

    calls = {}

    def platform(name, arguments):
        calls[name] = arguments
        return {"job_id": "golden"} if name == "upload_contacts" else {"action": "sent", "sent": 1}

    monkeypatch.setattr(whatsapp_platform, "call_tool", platform)
    monkeypatch.setattr(whatsapp_platform, "_settings", lambda: SimpleNamespace(
        test_copy=False, whatsapp_language="en_US"))
    with send_reason.sent_by(case["input"]["sent_by"]):
        out = whatsapp_platform.send("9812345678", "Namaste {name}", {"name": "Csp"},
                                     source_name="golden")
    assert out["status"] == whatsapp_platform.SENT, out
    assert bool(calls["smart_send_template"].get("force")) == case["expect"]["force"]


@pytest.mark.parametrize("case", _cases("sender"))
def test_sender(case):
    from app.routers.whatsapp_message_router import _sender

    i, expect = case["input"], case["expect"]
    names = {k: tuple(v) for k, v in i["names"].items()}
    out = _sender(i["sent_by"], i["because"], i["me"], names)
    assert (out["sender_label"], out["sender_role"]) == (expect["label"], expect["role"])


@pytest.mark.parametrize("case", _cases("link"))
def test_link(case, db):  # noqa: F811
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.csp_record import CSPRecord
    from app.models.data_request import DataRequest
    from app.services import whatsapp_platform

    i, expect = case["input"], case["expect"]
    s = db.session
    _old(s, i["code"])
    s.commit()
    csp = s.execute(select(CSPRecord).where(CSPRecord.csp_id == i["code"])).scalar_one()
    sent = []
    for send in i["sends"]:
        db.status = whatsapp_platform.SENT if send["reaches"] else whatsapp_platform.FAILED
        if send["by_hand"]:
            out = message_sender.ask_for_details(s, csp, verify=True, manual=True, fresh=True)
        else:
            out = message_sender.ask_for_details(s, csp, verify=True)
        sent.append(out["sent"])
    assert sent == expect["sent"]
    links = s.execute(select(DataRequest).where(DataRequest.csp_id == i["code"])
                      .order_by(DataRequest.created_at)).scalars().all()
    assert [r.status for r in links] == expect["links"]
    newest_open = [r for r in links if r.status == "open"][-1]
    left = newest_open.expires_at - datetime.now(timezone.utc)
    days = timedelta(days=expect["valid_days"])
    assert days - timedelta(minutes=5) < left <= days


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


@pytest.mark.parametrize("case", _cases("setting"))
def test_setting(case):
    """No. 204: Eko's standard values stay what the code used before; the
    chat reads a 'set ... to ...' command the same way every time."""
    from app.config import Settings
    from app.services import settings_catalog, settings_chat

    i, expect = case["input"], case["expect"]
    if "standard" in i:
        assert [Settings.model_fields[k].default for k in i["standard"]] == expect["values"]
        assert all(k in settings_catalog.KEYS for k in i["standard"])
        return
    if "together" in i:
        with pytest.raises(settings_catalog.SettingError) as e:
            settings_catalog.check_together(i["together"])
        assert expect["problem"] in str(e.value)
        return
    parsed = settings_chat.parse(i["chat"])
    assert parsed is not None
    key = parsed.setting.key if parsed.setting else None
    assert key == expect["key"]
    if "value" in expect:
        assert parsed.problem is None and parsed.value == expect["value"]
    if "problem" in expect:
        assert expect["problem"] in (parsed.problem or "")


@pytest.mark.parametrize("case", _cases("feature"))
def test_feature(case):
    """No. 206: who may use which feature; the chat's give / take."""
    from app.services import access_chat, feature_access, feature_catalog

    i, expect = case["input"], case["expect"]
    if "chat" in i:
        p = access_chat.parse(i["chat"])
        assert (p.feature.key, p.subject, p.allowed) == (
            expect["feature"], expect["subject"], expect["allowed"])
        return
    if "routes" in i:
        assert [feature_catalog.feature_for(m, path).key
                for m, path in i["routes"]] == expect["features"]
        return
    data = {"grants": {tuple(k.split("|")): v for k, v in i["grants"].items()},
            "roles": i.get("roles", {}), "members": i.get("members", {})}
    user = {"role": i["role"], "sub": i["email"]}
    for key in expect["has"]:
        assert feature_access.allowed(key, user, data), key
    for key in expect["not"]:
        assert not feature_access.allowed(key, user, data), key
    if "scope" in expect:
        role = feature_access.own_role(user, data)
        assert data["roles"][role]["scope"] == expect["scope"]


@pytest.mark.parametrize("case", _cases("connection"))
def test_connection(case):
    """No. 210: each workspace's own connections; Eko's stay Eko's."""
    from app.services import connection_catalog as cc, connection_chat

    i, expect = case["input"], case["expect"]
    if "eko_only" in i:
        assert all(cc.BY_KEY[k].eko_only for k in i["eko_only"])
        return
    if "secret" in i:
        assert set(i["secret"]) == set(cc.SECRET_KEYS)
        return
    if "chat" in i:
        p = connection_chat.parse(i["chat"])
        if expect.get("none"):
            assert p is None
        elif "tests" in expect:
            assert p.tests == expect["tests"]
        else:
            assert expect["problem"] in (p.problem or "")
        return
    c = cc.BY_KEY[i["key"]]
    if "value" in expect:
        assert cc.parse(c, i["value"]) == expect["value"]
    else:
        with pytest.raises(cc.ConnectionError_) as e:
            cc.parse(c, i["value"])
        assert expect["problem"] in str(e.value)


@pytest.mark.parametrize("case", _cases("data"))
def test_data(case):
    """No. 211: record types, and guessing a sheet's columns."""
    from app.services import data_shape, ko_level

    i, expect = case["input"], case["expect"]
    if "codes" in i:
        assert [ko_level.level_of(c) for c in i["codes"]] == expect["levels"]
        return
    if "store" in i:
        assert data_shape.to_store(i["store"]) == expect["kept"]
        return
    got = data_shape.guess(i["headers"])
    assert {f: v["header"] for f, v in got.items()} == expect["guess"]
    if "score" in expect:
        assert all(v["score"] == expect["score"] for v in got.values())
