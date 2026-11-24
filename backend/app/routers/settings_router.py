"""
CSP DocMaker — Setup → Settings (PROJECT-REGISTER No. 204, Stage 1)

  GET    /api/admin/settings                     every setting: this workspace's
                                                 value, the standard (Eko's)
                                                 value, who may change it
  PUT    /api/admin/settings/{key}               change one  {"value": ...}
  DELETE /api/admin/settings/{key}               back to the standard value
  GET    /api/admin/settings/history?key=        what changed, by whom, when
  POST   /api/admin/settings/history/{id}/undo   put one change back
  PUT    /api/admin/settings/admin-groups        which groups Admins may change
                                                 (Super Admin only)

Seen by Admins and the Super Admin. Changed by the Super Admin, and by
Admins only in the groups handed to them. The server checks every value
(safe range, the rules between settings) — the screen's checks are only a
convenience. What a setting is and does: services/settings_catalog.py.
"""

import logging
from typing import Any, List, Optional

from fastapi import (APIRouter, Depends, File, HTTPException, Query,
                     UploadFile, status)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.services import workspace_settings
from app.services.settings_catalog import SettingError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/settings", tags=["admin", "settings"])

viewer = require_role("admin", "super_admin")


class ValueIn(BaseModel):
    value: Any


class GroupsIn(BaseModel):
    groups: List[str] = Field(default_factory=list, max_length=50)


def _refused(e: Exception) -> HTTPException:
    if isinstance(e, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("")
async def list_settings(session: AsyncSession = Depends(get_session),
                        user=Depends(viewer)):
    return await workspace_settings.describe(session, user)


@router.get("/history")
async def setting_history(key: Optional[str] = Query(None, max_length=80),
                          limit: int = Query(100, ge=1, le=500),
                          session: AsyncSession = Depends(get_session),
                          user=Depends(viewer)):
    return {"changes": await workspace_settings.history(session, key, limit)}


@router.post("/history/{change_id}/undo")
async def undo_change(change_id: int,
                      session: AsyncSession = Depends(get_session),
                      user=Depends(viewer)):
    try:
        return await workspace_settings.undo(session, change_id, user)
    except (SettingError, PermissionError) as e:
        await session.rollback()
        raise _refused(e)


@router.get("/sheet")
async def download_sheet(session: AsyncSession = Depends(get_session),
                         user=Depends(viewer)):
    """ZU-07: every setting in one Excel file (No. 215)."""
    from fastapi.responses import Response
    from app.services import settings_sheet
    view = await workspace_settings.describe(session, user)
    name = (view["workspace"] or {}).get("name", "workspace")
    return Response(
        settings_sheet.build(view),
        media_type="application/vnd.openxmlformats-officedocument."
                   "spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="Settings - {name}.xlsx"'})


@router.post("/sheet")
async def upload_sheet(file: UploadFile = File(...), apply: bool = False,
                       session: AsyncSession = Depends(get_session),
                       user=Depends(viewer)):
    """ZU-07: the changes an uploaded settings sheet asks for. apply=false
    shows them; apply=true saves the allowed ones (same checks and history
    as the screen, via "sheet")."""
    from app.services import settings_sheet
    data = await file.read()
    if len(data) > 2_000_000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is too big.")
    try:
        uploaded = settings_sheet.read(data)
    except SettingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    view = await workspace_settings.describe(session, user)
    current = {s["key"]: s["value"] for s in view["settings"]}
    changes = settings_sheet.preview(current, uploaded)
    if not apply:
        return {"changes": changes, "applied": []}
    applied = []
    for c in changes:
        if c.get("problem") or not c.get("key"):
            continue
        try:
            await workspace_settings.set_value(session, c["key"], c["value"],
                                               user, via="sheet")
            applied.append(c["key"])
        except (SettingError, PermissionError) as e:
            await session.rollback()
            c["problem"] = str(e)
    return {"changes": changes, "applied": applied}


@router.put("/admin-groups")
async def set_admin_groups(body: GroupsIn,
                           session: AsyncSession = Depends(get_session),
                           user=Depends(require_role("super_admin"))):
    try:
        groups = await workspace_settings.set_admin_groups(
            session, body.groups, user)
    except (SettingError, PermissionError) as e:
        await session.rollback()
        raise _refused(e)
    return {"admin_groups": groups}


@router.put("/{key}")
async def change_setting(key: str, body: ValueIn,
                         session: AsyncSession = Depends(get_session),
                         user=Depends(viewer)):
    try:
        return await workspace_settings.set_value(session, key, body.value,
                                                  user, via="screen")
    except (SettingError, PermissionError) as e:
        await session.rollback()
        raise _refused(e)


@router.delete("/{key}")
async def back_to_standard(key: str,
                           session: AsyncSession = Depends(get_session),
                           user=Depends(viewer)):
    try:
        return await workspace_settings.to_standard(session, key, user)
    except (SettingError, PermissionError) as e:
        await session.rollback()
        raise _refused(e)
