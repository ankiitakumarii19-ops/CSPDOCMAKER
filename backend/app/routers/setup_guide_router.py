"""
CSP DocMaker — Setup → Setup guide (PROJECT-REGISTER No. 215, Stage 8:
TK-064 - TK-067)

Super Admin only (feature "setup_guide", locked):

  GET  /api/admin/setup-guide          every setup step (Done / To do /
                                       Problem), where to do it, and the
                                       switches: live, test mode, pause all
  POST /api/admin/setup-guide/go-live  go live — refused until every
                                       essential step is done
  POST /api/admin/setup-guide/dry-run  what would happen for 5 records,
                                       sending nothing

The same steps the chat walks through ("setup status"). The switches are
settings (Settings → Going live); services/send_guard.py enforces them.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/setup-guide",
                   tags=["admin", "setup-guide"])
owner = require_role("super_admin")

# Where each step is done (the Admin page's section).
WHERE = {"sheet": "connections", "records": "connections",
         "templates": "templates", "wordings": "messaging",
         "channel": "connections", "members": "access",
         "knowledge": "knowledge", "server": None, "agents": "agents"}


async def _state(session, user) -> dict:
    from app.config import get_settings
    from app.services import workspace_setup
    steps = await workspace_setup.checklist(session, user, live=True)
    s = get_settings()
    cards = []
    for step in steps:
        c = step.card()
        c["where"] = WHERE.get(step.key)
        c["essential"] = step.key in workspace_setup.CORE
        cards.append(c)
    essentials_done = all(c["status"] == workspace_setup.DONE
                          for c in cards if c["essential"])
    return {"steps": cards, "summary": workspace_setup.summary(steps),
            "live": bool(s.workspace_live), "test_mode": bool(s.test_mode),
            "test_mode_phone": s.test_mode_phone,
            "test_mode_email": s.test_mode_email,
            "pause_all": bool(s.pause_all),
            "ready_to_go_live": essentials_done}


@router.get("")
async def guide(session: AsyncSession = Depends(get_session),
                user=Depends(owner)):
    return await _state(session, user)


@router.post("/go-live")
async def go_live(session: AsyncSession = Depends(get_session),
                  user=Depends(owner)):
    from app.services import workspace_settings
    state = await _state(session, user)
    if state["live"]:
        return state
    if not state["ready_to_go_live"]:
        left = [c["title"] for c in state["steps"]
                if c["essential"] and c["status"] != "done"]
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Not yet: finish these first — " + "; ".join(left))
    await workspace_settings.set_value(session, "workspace_live", True, user,
                                       note="went live from the Setup guide")
    logger.info("setup_guide: %s took the workspace live", user.get("sub"))
    return await _state(session, user)


@router.post("/dry-run")
async def dry_run(session: AsyncSession = Depends(get_session),
                  user=Depends(owner)):
    """What the app would do for the 5 newest records. Sends nothing."""
    from app.config import get_settings
    from app.models.csp_record import CSPRecord
    from app.models.document_template import DocumentTemplate
    from app.services import field_ownership as fo, ko_level, send_guard
    s = get_settings()
    records = list((await session.execute(select(CSPRecord).order_by(
        CSPRecord.created_at.desc()).limit(5))).scalars())
    codes = [t.code for t in (await session.execute(select(
        DocumentTemplate).where(DocumentTemplate.active.is_(True)))).scalars()]
    held = send_guard.refusal()
    out = []
    for r in records:
        code = r.csp_code or r.csp_id
        missing = fo.missing(r)
        docs = [str(getattr(d, "value", d)) for d in
                ko_level.allowed_documents(code, codes)]
        if r.send_hold:
            happens = f"Nothing — on hold: {r.send_hold}"
        elif missing["csp"]:
            happens = ("WhatsApp with the details form asking for: "
                       + ", ".join(fo.label_of(f) for f in missing["csp"]))
        elif not docs:
            happens = "No active document applies to this record."
        else:
            happens = (f"Make {', '.join(docs)}; email them to "
                       f"{r.email or '(no email)'}"
                       + ("; WhatsApp “documents ready”"
                          if s.msg_documents_ready else ""))
        if held and not r.send_hold:
            happens += f" — but held now: {held}"
        elif s.test_mode and not r.send_hold:
            happens += " — in test mode: sent only to the test number / email"
        out.append({"code": code, "name": r.name,
                    "type": ko_level.label_for(code) or "unknown type",
                    "documents": docs, "missing": missing["csp"]
                    + missing["org"], "on_hold": r.send_hold or "",
                    "would_happen": happens})
    return {"records": out, "sent": 0,
            "note": "Nothing was sent; this only shows what would happen."}
