"""
CSP DocMaker — signatures chosen by rule (No. 247)

Document templates → Signatures. Admins and Super Admins (feature
"templates"), each workspace only its own (workspace_context).

  GET    /api/admin/signatures                       pictures, rules, columns, documents
  POST   /api/admin/signatures                       upload a picture (name + file)
  PATCH  /api/admin/signatures/{id}                  rename
  DELETE /api/admin/signatures/{id}                  remove (refused while a rule uses it)
  GET    /api/admin/signatures/{id}/picture          the PNG
  POST   /api/admin/signatures/rules                 add a rule
  PATCH  /api/admin/signatures/rules/{id}            change a rule
  DELETE /api/admin/signatures/rules/{id}            remove a rule
  PUT    /api/admin/signatures/rules/order           {ids: [...]} the order rules are tried in
  GET    /api/admin/signatures/values?column=lho     that column's values in this workspace
  GET    /api/admin/signatures/documents/{code}      where the signature sits + its pictures
  GET    /api/admin/signatures/documents/{code}/pictures/{sha}   one picture from the file
  PUT    /api/admin/signatures/documents/{code}/spot {spot}      choose where it sits
  GET    /api/admin/signatures/which?code=&csp_id=   which signature this CSP would get

Every change is audited and takes effect within 30 seconds on every worker
(signature_rules cache), at once on this one.
"""

import logging
import uuid
from typing import List, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Response,
                     UploadFile, status)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.models.document_template import DocumentTemplate
from app.models.signature import Signature, SignatureRule
from app.services import signature_rules as sr
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/signatures", tags=["admin", "signatures"])

admin = require_role("admin", "super_admin")


def _who(user: dict) -> str:
    return (user or {}).get("email") or (user or {}).get("sub") or "unknown"


async def _audit(session, action: str, resource_id: str, user, **meta) -> None:
    session.add(AuditLog(workspace_id=current_workspace_id(), action=action,
                         resource_type="signature", resource_id=resource_id,
                         result="success", metadata_json={"by": _who(user), **meta}))


def _changed() -> None:
    sr.forget(current_workspace_id())


def _sig_row(s: Signature, used: int) -> dict:
    return {"id": str(s.id), "name": s.name, "width": s.width, "height": s.height,
            "checksum": s.checksum[:12], "used_by": used,
            "created_by": s.created_by,
            "created_at": s.created_at.isoformat() if s.created_at else None}


def _rule_row(r: SignatureRule, names: dict, docs: dict) -> dict:
    rule = sr.Rule(id=str(r.id), document_code=r.document_code,
                   column=r.column_name or "", values=list(r.match_values or []),
                   signature_id=str(r.signature_id),
                   signature_name=names.get(r.signature_id, "?"), active=r.active)
    return {"id": str(r.id), "document_code": r.document_code,
            "column": r.column_name or "", "values": list(r.match_values or []),
            "signature_id": str(r.signature_id),
            "signature_name": names.get(r.signature_id, "?"),
            "position": r.position, "active": r.active,
            "words": sr.describe(rule, docs)}


async def _documents(session) -> dict:
    rows = (await session.execute(select(DocumentTemplate.code, DocumentTemplate.name)
                                  .order_by(DocumentTemplate.name))).all()
    return {code: name for code, name in rows}


async def _rules(session) -> List[SignatureRule]:
    return (await session.execute(select(SignatureRule).order_by(
        SignatureRule.position, SignatureRule.created_at))).scalars().all()


async def _signature(session, sig_id: uuid.UUID) -> Signature:
    s = (await session.execute(select(Signature).where(Signature.id == sig_id))).scalars().first()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such signature in this workspace.")
    return s


async def _rule(session, rule_id: uuid.UUID) -> SignatureRule:
    r = (await session.execute(select(SignatureRule).where(SignatureRule.id == rule_id))).scalars().first()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such rule in this workspace.")
    return r


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give the signature a name.")
    if len(name) > 120:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The name is too long (120 letters at most).")
    return name


async def _name_taken(session, name: str, but: Optional[uuid.UUID] = None) -> bool:
    q = select(Signature.id).where(func.lower(Signature.name) == name.lower())
    if but is not None:
        q = q.where(Signature.id != but)
    return (await session.execute(q)).first() is not None


# ---- pictures ----------------------------------------------------------------

@router.get("")
async def overview(session: AsyncSession = Depends(get_session), user=Depends(admin)):
    sigs = (await session.execute(select(Signature).order_by(Signature.name))).scalars().all()
    rules = await _rules(session)
    names = {s.id: s.name for s in sigs}
    docs = await _documents(session)
    used = {}
    for r in rules:
        used[r.signature_id] = used.get(r.signature_id, 0) + 1
    return {
        "signatures": [_sig_row(s, used.get(s.id, 0)) for s in sigs],
        "rules": [_rule_row(r, names, docs) for r in rules],
        "columns": [{"key": k, "label": v} for k, v in sr.COLUMNS],
        "documents": [{"code": c, "name": n} for c, n in docs.items()],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(name: str = Form(...), file: UploadFile = File(...),
                 session: AsyncSession = Depends(get_session), user=Depends(admin)):
    name = _clean_name(name)
    if await _name_taken(session, name):
        raise HTTPException(status.HTTP_409_CONFLICT, f"There is already a signature called {name}.")
    try:
        png, width, height = sr.check_picture(await file.read())
    except sr.SignatureError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    s = Signature(name=name, image=png, width=width, height=height,
                  checksum=sr.sha256(png), created_by=_who(user))
    session.add(s)
    await session.flush()
    await _audit(session, "signature_added", str(s.id), user, name=name)
    await session.commit()
    _changed()
    logger.info("signature_router.upload: %s (%dx%d) by %s", name, width, height, _who(user))
    return _sig_row(s, 0)


class Rename(BaseModel):
    name: str = Field(..., max_length=200)


@router.patch("/{sig_id:uuid}")
async def rename(sig_id: uuid.UUID, body: Rename,
                 session: AsyncSession = Depends(get_session), user=Depends(admin)):
    s = await _signature(session, sig_id)
    name = _clean_name(body.name)
    if await _name_taken(session, name, but=s.id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"There is already a signature called {name}.")
    old, s.name = s.name, name
    await _audit(session, "signature_renamed", str(s.id), user, old=old, new=name)
    await session.commit()
    _changed()
    return {"ok": True}


@router.delete("/{sig_id:uuid}")
async def remove(sig_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                 user=Depends(admin)):
    s = await _signature(session, sig_id)
    used = (await session.execute(select(func.count()).select_from(SignatureRule)
                                  .where(SignatureRule.signature_id == s.id))).scalar() or 0
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{s.name} is used by {used} rule(s). Remove or change "
                            "those rules first.")
    await _audit(session, "signature_removed", str(s.id), user, name=s.name)
    await session.delete(s)
    await session.commit()
    _changed()
    return {"ok": True}


@router.get("/{sig_id:uuid}/picture")
async def picture(sig_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                  user=Depends(admin)):
    s = await _signature(session, sig_id)
    return Response(bytes(s.image), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=60"})


# ---- rules -----------------------------------------------------------------------

class RuleIn(BaseModel):
    document_code: Optional[str] = Field(None, max_length=50)
    column: str = Field("", max_length=50)
    values: List[str] = Field(default_factory=list, max_length=500)
    signature_id: uuid.UUID
    active: bool = True


async def _check_rule(session, body: RuleIn) -> tuple:
    code = (body.document_code or "").strip() or None
    if code is not None and code not in await _documents(session):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No document called {code}.")
    column = (body.column or "").strip()
    if column and column not in sr.COLUMN_KEYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{column} is not a column a rule can use.")
    values, seen = [], set()
    for v in body.values:
        v = " ".join(str(v or "").split())
        if v and sr.norm(v) not in seen:
            seen.add(sr.norm(v))
            values.append(v[:200])
    if column and not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Give at least one value, or choose \"every other CSP\".")
    if not column:
        values = []
    await _signature(session, body.signature_id)
    return code, column, values


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def add_rule(body: RuleIn, session: AsyncSession = Depends(get_session),
                   user=Depends(admin)):
    code, column, values = await _check_rule(session, body)
    rules = await _rules(session)
    # A rule for particular CSPs goes before the "every other CSP" rules, so
    # adding one never leaves it unreachable behind a catch-all.
    catch_alls = [r for r in rules if not r.column_name]
    if column and catch_alls:
        position = min(r.position for r in catch_alls)
        for r in rules:
            if r.position >= position:
                r.position += 1
    else:
        position = max([r.position for r in rules], default=-1) + 1
    r = SignatureRule(document_code=code, column_name=column, match_values=values,
                      signature_id=body.signature_id, position=position,
                      active=body.active, created_by=_who(user))
    session.add(r)
    await session.flush()
    await _audit(session, "signature_rule_added", str(r.id), user,
                 document=code, column=column, values=values,
                 signature_id=str(body.signature_id))
    await session.commit()
    _changed()
    return {"id": str(r.id)}


@router.put("/rules/order")
async def order_rules(body: dict, session: AsyncSession = Depends(get_session),
                      user=Depends(admin)):
    ids = [str(i) for i in (body or {}).get("ids") or []]
    rules = {str(r.id): r for r in await _rules(session)}
    if sorted(ids) != sorted(rules):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Send every rule once, in the new order.")
    for n, rid in enumerate(ids):
        rules[rid].position = n
    await _audit(session, "signature_rules_ordered", "rules", user, order=ids)
    await session.commit()
    _changed()
    return {"ok": True}


@router.patch("/rules/{rule_id:uuid}")
async def change_rule(rule_id: uuid.UUID, body: RuleIn,
                      session: AsyncSession = Depends(get_session), user=Depends(admin)):
    r = await _rule(session, rule_id)
    code, column, values = await _check_rule(session, body)
    before = {"document": r.document_code, "column": r.column_name,
              "values": r.match_values, "signature_id": str(r.signature_id),
              "active": r.active}
    r.document_code, r.column_name, r.match_values = code, column, values
    r.signature_id, r.active = body.signature_id, body.active
    await _audit(session, "signature_rule_changed", str(r.id), user, before=before,
                 after={"document": code, "column": column, "values": values,
                        "signature_id": str(body.signature_id), "active": body.active})
    await session.commit()
    _changed()
    return {"ok": True}


@router.delete("/rules/{rule_id:uuid}")
async def remove_rule(rule_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                      user=Depends(admin)):
    r = await _rule(session, rule_id)
    await _audit(session, "signature_rule_removed", str(r.id), user,
                 document=r.document_code, column=r.column_name, values=r.match_values)
    await session.delete(r)
    await session.commit()
    _changed()
    return {"ok": True}


@router.get("/values")
async def column_values(column: str, session: AsyncSession = Depends(get_session),
                        user=Depends(admin)):
    """The values this column holds in this workspace's records, most common
    first — what the admin picks a rule's values from."""
    if column not in sr.COLUMN_KEYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{column} is not a column a rule can use.")
    col = getattr(CSPRecord, column)
    rows = (await session.execute(
        select(col, func.count()).where(col.is_not(None), func.trim(col) != "")
        .group_by(col).order_by(func.count().desc(), col).limit(300))).all()
    merged: dict = {}
    for value, count in rows:
        key = sr.norm(value)
        if key in merged:
            merged[key]["count"] += count
        else:
            merged[key] = {"value": " ".join(str(value).split()), "count": count}
    return {"column": column, "values": list(merged.values())}


# ---- where the signature sits in a document -----------------------------------------

async def _template(session, code: str) -> DocumentTemplate:
    from app.routers.template_router import _get
    return await _get(session, code)


def _open_doc(template: DocumentTemplate):
    import io
    from docx import Document
    from app.routers.template_router import _file_bytes
    return Document(io.BytesIO(_file_bytes(template)))


@router.get("/documents/{code}")
async def document_spot(code: str, session: AsyncSession = Depends(get_session),
                        user=Depends(admin)):
    from starlette.concurrency import run_in_threadpool
    from app.services import document_template_service as dts
    from app.routers.template_router import _file_bytes

    template = await _template(session, code)
    data = _file_bytes(template)

    def read():
        import io
        from docx import Document
        return sr.pictures_in(Document(io.BytesIO(data))), dts.read_paragraphs(data)

    pictures, paragraphs = await run_in_threadpool(read)
    stored = template.signature_spot
    spot = stored or (sr.default_spot() if template.is_builtin else None)
    found = True
    if spot and spot.startswith("picture:"):
        found = spot[len("picture:"):] in pictures
    elif spot and spot.startswith("text:"):
        from app.services import template_service as ts
        wanted = ts._squash(spot[len("text:"):])
        found = any(ts._squash(p["text"]) == wanted for p in paragraphs)
    return {
        "code": template.code, "name": template.name,
        "spot": spot, "chosen": bool(stored), "found": found,
        "pictures": [{"checksum": k, "width": v["width"], "height": v["height"],
                      "count": v["count"]} for k, v in pictures.items()],
        "paragraphs": [{"text": p["text"]} for p in paragraphs
                       if not p["has_placeholder"] and len(p["text"].strip()) <= 120],
    }


@router.get("/documents/{code}/pictures/{checksum}")
async def document_picture(code: str, checksum: str,
                           session: AsyncSession = Depends(get_session),
                           user=Depends(admin)):
    from starlette.concurrency import run_in_threadpool
    template = await _template(session, code)
    pictures = await run_in_threadpool(lambda: sr.pictures_in(_open_doc(template)))
    pic = pictures.get(checksum)
    if pic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That picture is not in this document.")
    return Response(pic["blob"], media_type=pic["content_type"],
                    headers={"Cache-Control": "private, max-age=60"})


class SpotIn(BaseModel):
    spot: Optional[str] = Field(None, max_length=400)


@router.put("/documents/{code}/spot")
async def set_spot(code: str, body: SpotIn, session: AsyncSession = Depends(get_session),
                   user=Depends(admin)):
    from app.services import document_registry
    template = await _template(session, code)
    spot = (body.spot or "").strip() or None
    if spot is not None:
        info = await document_spot(code, session, user)
        if spot.startswith("picture:"):
            if spot[len("picture:"):] not in {p["checksum"] for p in info["pictures"]}:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That picture is not in this document.")
        elif spot.startswith("text:"):
            from app.services import template_service as ts
            wanted = ts._squash(spot[len("text:"):])
            if not wanted or wanted not in {ts._squash(p["text"]) for p in info["paragraphs"]}:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That line is not in this document.")
            spot = "text:" + wanted
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a picture or a line of the document.")
    before, template.signature_spot = template.signature_spot, spot
    await _audit(session, "signature_spot_set", template.code, user, before=before, after=spot)
    await session.commit()
    document_registry.invalidate(current_workspace_id())
    _changed()
    logger.info("signature_router.set_spot: %s → %s by %s", code, spot, _who(user))
    return {"ok": True, "spot": spot}


@router.get("/which")
async def which(code: str, csp_id: str, session: AsyncSession = Depends(get_session),
                user=Depends(admin)):
    """Which signature this CSP would get on this document, and why."""
    csp = (await session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == csp_id.strip()))).scalars().first()
    if csp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No CSP {csp_id.strip()} in this workspace.")
    sigs = {s.id: s.name for s in (await session.execute(select(Signature))).scalars().all()}
    rules = [sr.Rule(id=str(r.id), document_code=r.document_code, column=r.column_name or "",
                     values=list(r.match_values or []), signature_id=str(r.signature_id),
                     signature_name=sigs.get(r.signature_id, "?"), active=r.active)
             for r in await _rules(session)]
    docs = await _documents(session)
    hit = sr.first_match(rules, code, sr.record_of(csp))
    if hit:
        return {"signature": hit.signature_name, "rule_id": hit.id,
                "why": sr.describe(hit, docs)}
    from app.services import lho_signature
    template = await _template(session, code)
    from app.services.workspace_settings import EKO_WORKSPACE
    own = (lho_signature.own_signature_path(csp.lho)
           if template.is_builtin and str(current_workspace_id()) == str(EKO_WORKSPACE)
           else None)
    if own:
        return {"signature": None, "rule_id": None,
                "why": f"No rule matches this CSP, so the LHO's own picture from the "
                       f"server ({own.replace(chr(92), '/').rsplit('/', 1)[-1]}) is used."}
    return {"signature": None, "rule_id": None,
            "why": "No rule matches this CSP, so the document keeps its own signature."}
