"""All settings as one Excel sheet (ZU-07) and the starter pack at sign-up
(ZU-08) — No. 215, Stage 8."""

import io
import uuid

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select, text

from app.services import jwt_service, workspace_service, workspace_settings
from app.workspace_context import all_workspaces

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "sheet.owner@eko.co.in"


async def _new(starter="blank"):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Sheet Test {uuid.uuid4().hex[:6]}", OWNER, "Owner",
            starter=starter)
        await s.commit()
        return ws


async def _drop(ws):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=ws.id))
            await s.commit()
    workspace_settings.forget()


def _h(ws):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin", "name": "O",
        "ws": str(ws.id)})}


def _xlsx(changes):
    """The downloaded sheet with some "Your value" cells changed."""
    def edit(data):
        wb = load_workbook(io.BytesIO(data))
        ws = wb["Settings"]
        for row in ws.iter_rows(min_row=2):
            if row[0].value in changes:
                row[3].value = changes[row[0].value]
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()
    return edit


async def test_the_settings_sheet_round_trip(strict_client, migrated_db):
    ws = await _new()
    try:
        r = await strict_client.get("/api/admin/settings/sheet", headers=_h(ws))
        assert r.status_code == 200
        data = r.content
        wb = load_workbook(io.BytesIO(data))
        assert wb["Settings"]["A1"].value == "Key"
        # unchanged sheet -> nothing to change
        r = await strict_client.post("/api/admin/settings/sheet?apply=false",
                                     headers=_h(ws),
                                     files={"file": ("s.xlsx", data)})
        assert r.json()["changes"] == []
        changed = _xlsx({"documents_feedback_after_minutes": 40,
                         "verify_batch_size": 5000})(data)
        r = await strict_client.post("/api/admin/settings/sheet?apply=false",
                                     headers=_h(ws),
                                     files={"file": ("s.xlsx", changed)})
        changes = {c["key"]: c for c in r.json()["changes"]}
        assert changes["documents_feedback_after_minutes"]["new"] == "40 minutes"
        assert "from 1 to 200" in changes["verify_batch_size"]["problem"]
        r = await strict_client.post("/api/admin/settings/sheet?apply=true",
                                     headers=_h(ws),
                                     files={"file": ("s.xlsx", changed)})
        assert r.json()["applied"] == ["documents_feedback_after_minutes"]
        hist = (await strict_client.get("/api/admin/settings/history",
                                        headers=_h(ws))).json()["changes"]
        assert hist[0]["via"] == "sheet" and hist[0]["after"] == "40 minutes"
        r = await strict_client.post("/api/admin/settings/sheet?apply=false",
                                     headers=_h(ws),
                                     files={"file": ("s.xlsx", b"not excel")})
        assert r.status_code == 400
    finally:
        await _drop(ws)


async def test_a_starter_pack_like_eko_or_blank(migrated_db):
    from app.database import async_session_factory
    from app.models.document_template import DocumentTemplate
    from app.models.messaging import MessageTemplate
    eko, blank = await _new("eko"), await _new("blank")
    try:
        async with async_session_factory() as s:
            with all_workspaces():
                def count(model, w, *where):
                    return select(func.count()).select_from(model).where(
                        model.workspace_id == w, *where)
                assert (await s.execute(count(MessageTemplate, eko.id))).scalar() > 0
                assert (await s.execute(count(DocumentTemplate, eko.id))).scalar() > 0
                assert (await s.execute(count(
                    DocumentTemplate, eko.id,
                    DocumentTemplate.active.is_(True)))).scalar() == 0
                assert (await s.execute(count(MessageTemplate, blank.id))).scalar() == 0
                assert (await s.execute(count(DocumentTemplate, blank.id))).scalar() == 0
    finally:
        await _drop(eko)
        await _drop(blank)
