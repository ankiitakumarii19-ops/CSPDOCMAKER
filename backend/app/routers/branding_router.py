"""
CSP DocMaker — the organisation's logo (No. 240, SaaS upgrade Stage 3)

  PUT    /api/admin/branding/logo   upload / change (Super Admin; feature "branding")
  DELETE /api/admin/branding/logo   back to the app's own logo
  GET    /api/me/logo               the workspace's logo for every signed-in
                                    member (404 = none: the app's own)

Name, colours, look and the "people may pick their own colours" switch are
workspace settings (Setup -> Display; history and undo on Settings). The
email sender is on Setup -> Connections. Changes are audited.
"""

import hashlib
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_user, require_role
from app.models.audit_log import AuditLog
from app.models.workspace_file import WorkspaceFile
from app.services import workspace_files
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["branding"])

owner = require_role("super_admin")


def _email(user: dict) -> str:
    return ((user or {}).get("sub") or (user or {}).get("email") or "").strip().lower()


async def _logo(session: AsyncSession):
    return (await session.execute(select(WorkspaceFile).where(
        WorkspaceFile.kind == "logo"))).scalars().first()


@router.put("/api/admin/branding/logo", summary="Upload the organisation's logo")
async def set_logo(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(owner),
):
    data = await file.read(workspace_files.MAX_BYTES + 1)
    try:
        png = workspace_files.check_logo(data)
    except workspace_files.LogoError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    checksum = hashlib.sha256(png).hexdigest()
    row = await _logo(session)
    if row is None:
        row = WorkspaceFile(kind="logo", content_type="image/png", data=png,
                            file_size=len(png), checksum=checksum,
                            filename=file.filename, updated_by=_email(user))
        session.add(row)
    else:
        row.data, row.file_size, row.checksum = png, len(png), checksum
        row.filename, row.updated_by = file.filename, _email(user)
    session.add(AuditLog(workspace_id=current_workspace_id(),
                         action="branding_logo_set", resource_type="workspace",
                         resource_id=str(current_workspace_id()), result="success",
                         metadata_json={"by": _email(user), "bytes": len(png)}))
    await session.commit()
    workspace_files.forget(current_workspace_id())
    logger.info("branding_router: %s set the logo of workspace %s (%d bytes)",
                _email(user), current_workspace_id(), len(png))
    return {"logo": checksum[:12], "bytes": len(png)}


@router.delete("/api/admin/branding/logo", summary="Use the app's own logo again")
async def remove_logo(
    session: AsyncSession = Depends(get_session),
    user=Depends(owner),
):
    row = await _logo(session)
    if row is not None:
        await session.delete(row)
        session.add(AuditLog(workspace_id=current_workspace_id(),
                             action="branding_logo_remove", resource_type="workspace",
                             resource_id=str(current_workspace_id()),
                             result="success", metadata_json={"by": _email(user)}))
        await session.commit()
        workspace_files.forget(current_workspace_id())
        logger.info("branding_router: %s removed the logo of workspace %s",
                    _email(user), current_workspace_id())
    return {"logo": None, "removed": row is not None}


@router.get("/api/me/logo", summary="This workspace's logo")
async def get_logo(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    row = await _logo(session)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo: the app's own is shown.")
    return Response(row.data, media_type=row.content_type,
                    headers={"Cache-Control": "private, max-age=300",
                             "X-Logo-Version": row.checksum[:12]})
