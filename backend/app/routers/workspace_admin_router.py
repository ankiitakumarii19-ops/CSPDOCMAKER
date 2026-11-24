"""
CSP DocMaker — a workspace's own data out, and closing a workspace
(PROJECT-REGISTER No. 216, Stage 9: TK-072)

Super Admin only (feature "workspace_admin", locked):

  GET  /api/admin/workspace/export   a .zip of CSV files: its records,
                                     WhatsApps, emails, form links, documents
                                     (list, not the PDFs), members, settings.
                                     No passwords, keys or link tokens.
  POST /api/admin/workspace/close    {"confirm": "<workspace name>"} — the
                                     workspace is switched OFF (nobody signs
                                     in, no job runs for it). Nothing is
                                     deleted; Eko's workspace cannot be
                                     closed. Opening it again, or deleting it
                                     for good, is the server administrator's,
                                     after a database backup (DEPLOY.md).
"""

import csv
import io
import logging
import zipfile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/workspace", tags=["admin", "workspace"])
owner = require_role("super_admin")

# Never exported: secrets and what could open a CSP's form.
NEVER = {"token_hash", "password_hash", "ciphertext", "file_data"}


def _tables():
    from app.models.csp_record import CSPRecord
    from app.models.data_request import DataRequest
    from app.models.email_message import EmailMessage
    from app.models.stored_document import StoredDocument
    from app.models.whatsapp_message import WhatsAppMessage
    from app.models.workspace_member import WorkspaceMember
    from app.models.workspace_setting import WorkspaceSetting
    return [("records", CSPRecord), ("whatsapp_messages", WhatsAppMessage),
            ("emails", EmailMessage), ("form_links", DataRequest),
            ("documents", StoredDocument), ("members", WorkspaceMember),
            ("settings", WorkspaceSetting)]


@router.get("/export")
async def export(session: AsyncSession = Depends(get_session),
                 user=Depends(owner)):
    from app.services.workspace_settings import _workspace
    ws = await _workspace(session)
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, model in _tables():
            cols = [c.name for c in model.__table__.columns
                    if c.name not in NEVER]
            text = io.StringIO()
            w = csv.writer(text)
            w.writerow(cols)
            # Only the exported columns: a PDF is never read into memory.
            table = model.__table__
            rows = (await session.execute(
                select(*[table.c[c] for c in cols]).where(
                    table.c.workspace_id == ws.id))).all()
            for r in rows:
                w.writerow(["" if v is None else str(v) for v in r])
            counts[name] = len(rows)
            z.writestr(f"{name}.csv", text.getvalue())
        z.writestr("README.txt",
                   f"Data of the workspace {ws.name}, exported by "
                   f"{user.get('sub')}.\nPasswords, keys, form-link tokens "
                   "and the PDF files themselves are not included.\n"
                   + "\n".join(f"{k}: {v} rows" for k, v in counts.items()))
    logger.info("workspace_admin: %s exported %s (%s)", user.get("sub"),
                ws.slug, counts)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="{ws.slug}-export.zip"'})


class CloseIn(BaseModel):
    confirm: str


@router.post("/close")
async def close(body: CloseIn, session: AsyncSession = Depends(get_session),
                user=Depends(owner)):
    from app.models.audit_log import AuditLog
    from app.services.workspace_settings import EKO_WORKSPACE, _workspace
    ws = await _workspace(session)
    if ws.id == EKO_WORKSPACE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Eko's workspace cannot be closed.")
    if body.confirm.strip() != ws.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Type the workspace's name exactly to close it.")
    ws.active = False
    session.add(AuditLog(workspace_id=ws.id, action="workspace_closed",
                         resource_type="workspace", resource_id=str(ws.id),
                         result="success",
                         metadata_json={"by": user.get("sub")}))
    await session.commit()
    logger.warning("workspace_admin: %s CLOSED workspace %s (nothing deleted)",
                   user.get("sub"), ws.slug)
    return {"closed": True,
            "note": "Switched off. Nothing was deleted; the server "
                    "administrator can open it again."}
