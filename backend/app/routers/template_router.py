"""
CSP DocMaker — managing document templates from the admin screen

An admin uploads a .docx, sees the placeholders it contains, says what fills
each one, edits the wording if they need to, and activates it.

Admins and Workspace Owners both work here. A template decides what every
CSP's official documents say, so RMs cannot reach any of it — but shaping
the documents is operational work, not platform administration.

What stays with the Workspace Owner alone is Access: who may sign in. An
Admin who could grant access could grant themselves anything.

Two refusals are deliberate and worth knowing about:

  * A template is not activated while any placeholder is unmapped. An
    unmapped placeholder prints nothing where a name belongs.
  * A built-in template cannot be deleted. Documents already issued refer to
    it, and their history would stop making sense.
"""

import logging
import os
from typing import Dict, List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile, status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.document_template import DocumentTemplate
from app.services import csp_mapping
from app.services import document_template_service as dts
from app.services import template_service as ts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/templates", tags=["admin", "templates"])


def _who(user: dict) -> str:
    """Who is doing this, for the log and the audit trail.

    A token always carries `sub`; it does not always carry `email`, and
    logging "None" for who deleted something is worse than useless.
    """
    return (user or {}).get("email") or (user or {}).get("sub") or "unknown"



# ---- what the screen sends back -----------------------------------------

class TemplateSettings(BaseModel):
    name: Optional[str] = None
    placeholder_map: Optional[Dict[str, str]] = None
    photo_marker: Optional[str] = None
    active: Optional[bool] = None


class ContentEdit(BaseModel):
    edits: Dict[str, str] = Field(
        ..., description="Paragraph index -> its new wording",
    )


# ---- helpers -------------------------------------------------------------

async def _get(session: AsyncSession, code: str) -> DocumentTemplate:
    template = (await session.execute(
        select(DocumentTemplate).where(DocumentTemplate.code == code)
    )).scalars().first()
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No document template called {code}.",
        )
    return template


def _file_bytes(template: DocumentTemplate) -> bytes:
    """The template's .docx, wherever it lives.

    A built-in's file is on disk where it has always been; an uploaded one is
    in the database.
    """
    if template.file_data:
        return bytes(template.file_data)

    directory = ts.settings.document_templates_dir
    name = template.filename or ""
    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        # The supplied templates get renamed in Word; resolve the same way
        # generation does rather than failing on a space-vs-underscore.
        for entry in sorted(os.listdir(directory)):
            if entry.startswith("~$") or not entry.lower().endswith(".docx"):
                continue
            if ts._same_name(entry, name):
                path = os.path.join(directory, entry)
                break
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The file for {template.code} is missing from {directory}.",
        )
    with open(path, "rb") as handle:
        return handle.read()


def _available_fields() -> List[dict]:
    """Every field a placeholder may be mapped to, for the dropdown."""
    from app.services import field_ownership as fo

    seen: Dict[str, str] = {}
    for field, (label, _type) in csp_mapping.FIELD_LABELS.items():
        seen[field] = label
    for field in fo.ALL_FIELDS:
        seen.setdefault(field, fo.label_of(field))
    for field in csp_mapping.COMPUTED_FIELDS:
        seen.setdefault(field, field.replace("_", " ").title())
    return [{"field": f, "label": l} for f, l in sorted(seen.items())]


def _summarise(template: DocumentTemplate, placeholders: List[str]) -> dict:
    mapping = template.placeholder_map or {}
    unmapped = [p for p in placeholders if not mapping.get(p)]
    return {
        "code": template.code,
        "name": template.name,
        "is_builtin": template.is_builtin,
        "active": template.active,
        "version": template.version,
        "filename": template.filename,
        "photo_marker": template.photo_marker,
        "placeholder_count": len(placeholders),
        "unmapped_count": len(unmapped),
        "ready": not unmapped,
    }


# ---- endpoints -----------------------------------------------------------

@router.get("")
async def list_templates(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Every document this system can issue."""
    templates = (await session.execute(
        select(DocumentTemplate).order_by(DocumentTemplate.name)
    )).scalars().all()

    rows = []
    for template in templates:
        try:
            placeholders = dts.read_placeholders(_file_bytes(template))
            row = _summarise(template, placeholders)
        except HTTPException as e:
            row = _summarise(template, [])
            row["error"] = e.detail
        rows.append(row)
    return {"templates": rows, "total": len(rows)}


@router.get("/fields")
async def available_fields(user=Depends(require_role("admin", "super_admin"))):
    """What a placeholder may be mapped to."""
    return {"fields": _available_fields()}


@router.get("/{code}")
async def template_detail(
    code: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Everything the editing screen needs for one template."""
    template = await _get(session, code)
    data = _file_bytes(template)
    info = dts.inspect(data)

    stored = template.placeholder_map or {}
    # What is stored wins; the guess only fills what nobody has decided yet.
    mapping = {p: stored.get(p) or info["mapped"].get(p) or ""
               for p in info["placeholders"]}

    return {
        **_summarise(template, info["placeholders"]),
        "placeholders": [
            {"text": p, "field": mapping[p],
             "guessed": not stored.get(p) and bool(info["mapped"].get(p))}
            for p in info["placeholders"]
        ],
        "paragraphs": info["paragraphs"],
        "photo_marker_guess": info["photo_marker"],
        "fields": _available_fields(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_template(
    code: str = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Add a new document by uploading its .docx."""
    code = (code or "").strip().upper().replace(" ", "_")
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A document needs a code.")

    existing = (await session.execute(
        select(DocumentTemplate).where(DocumentTemplate.code == code)
    )).scalars().first()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{code} already exists. Upload a new version of it instead.",
        )

    data = await file.read()
    try:
        dts.validate_upload(data, file.filename or "")
    except dts.TemplateUploadError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    info = dts.inspect(data)
    template = DocumentTemplate(
        code=code,
        name=(name or code).strip(),
        filename=file.filename,
        file_data=data,
        file_size=len(data),
        checksum=dts.checksum(data),
        placeholder_map=info["mapped"],
        photo_marker=info["photo_marker"],
        is_builtin=False,
        # Nothing is issued from a template until its mapping is confirmed.
        active=False,
        version=1,
    )
    session.add(template)
    await session.commit()

    logger.info(
        "template_router.upload_template: %s uploaded %s — %d placeholders, "
        "%d mapped automatically", _who(user), code,
        len(info["placeholders"]), len(info["mapped"]),
    )
    return {
        **_summarise(template, info["placeholders"]),
        "unmapped": info["unmapped"],
        "message": (
            f"{len(info['mapped'])} of {len(info['placeholders'])} "
            f"placeholders mapped automatically."
        ),
    }


@router.post("/{code}/version", status_code=status.HTTP_201_CREATED)
async def upload_new_version(
    code: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Replace a template's file, keeping its code and its mapping."""
    template = await _get(session, code)
    data = await file.read()
    try:
        dts.validate_upload(data, file.filename or "")
    except dts.TemplateUploadError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    info = dts.inspect(data)
    kept = {p: f for p, f in (template.placeholder_map or {}).items()
            if p in info["placeholders"]}
    template.file_data = data
    template.file_size = len(data)
    template.checksum = dts.checksum(data)
    template.filename = file.filename or template.filename
    template.placeholder_map = {**info["mapped"], **kept}
    template.version = (template.version or 1) + 1
    unmapped = [p for p in info["placeholders"]
                if not template.placeholder_map.get(p)]
    if unmapped:
        # A new file can introduce a placeholder nobody has mapped. Issuing
        # from it would print a blank, so it stops being used until an admin
        # has looked at it.
        template.active = False
    await session.commit()

    logger.info("template_router.upload_new_version: %s -> v%d by %s",
                code, template.version, _who(user))
    return {**_summarise(template, info["placeholders"]), "unmapped": unmapped}


@router.patch("/{code}")
async def update_template(
    code: str,
    settings: TemplateSettings,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Rename it, change what fills its placeholders, activate it."""
    template = await _get(session, code)
    placeholders = dts.read_placeholders(_file_bytes(template))

    if settings.name is not None:
        template.name = settings.name.strip() or template.name

    if settings.placeholder_map is not None:
        unknown = sorted(set(settings.placeholder_map) - set(placeholders))
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{unknown} are not placeholders in this template.",
            )
        valid = {f["field"] for f in _available_fields()}
        bad = sorted({v for v in settings.placeholder_map.values()
                      if v and v not in valid})
        if bad:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{bad} are not fields this system holds.",
            )
        template.placeholder_map = {
            p: f for p, f in settings.placeholder_map.items() if f
        }

    if settings.photo_marker is not None:
        template.photo_marker = settings.photo_marker.strip() or None

    if settings.active is not None:
        if settings.active:
            unmapped = [p for p in placeholders
                        if not (template.placeholder_map or {}).get(p)]
            if unmapped:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Cannot activate {code}: {unmapped} have nothing mapped "
                    f"to them, so the document would print a blank there.",
                )
        template.active = settings.active

    await session.commit()
    logger.info("template_router.update_template: %s changed by %s",
                code, _who(user))
    return _summarise(template, placeholders)


@router.put("/{code}/content")
async def edit_content(
    code: str,
    body: ContentEdit,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Change the wording, leaving the document's layout untouched.

    The text is rewritten run by run rather than the file being rebuilt, so
    text boxes, the photo frame and embedded images all survive.
    """
    template = await _get(session, code)
    try:
        data = dts.apply_paragraph_edits(
            _file_bytes(template), {int(k): v for k, v in body.edits.items()})
    except dts.TemplateUploadError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except (TypeError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Could not apply that edit: {e}")

    template.file_data = data
    template.file_size = len(data)
    template.checksum = dts.checksum(data)
    template.version = (template.version or 1) + 1
    # A built-in's wording now differs from the file on disk, so the database
    # copy becomes the one that counts.
    await session.commit()

    logger.info(
        "template_router.edit_content: %s wording changed by %s (%d "
        "paragraph(s)), now v%d",
        code, _who(user), len(body.edits), template.version,
    )
    return {
        **_summarise(template, dts.read_placeholders(data)),
        "paragraphs": dts.read_paragraphs(data),
    }


@router.delete("/{code}")
async def delete_template(
    code: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Remove an uploaded template. Built-ins cannot be removed."""
    template = await _get(session, code)
    if template.is_builtin:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{code} is one of the supplied documents and cannot be deleted. "
            f"Deactivate it instead — documents already issued refer to it.",
        )
    await session.delete(template)
    await session.commit()
    logger.info("template_router.delete_template: %s deleted by %s",
                code, _who(user))
    return {"deleted": code}
