"""
CSP DocMaker — your profile picture (No. 171)

  GET    /api/profile/photo/{email}   the picture (signed in; your own, or a
                                      member of the workspace you are in)
  PUT    /api/profile/photo           upload / change your own
  DELETE /api/profile/photo           remove your own — initials again
  GET/PUT/PATCH/DELETE /api/profile/appearance
                                      your own look (No. 240; see below)

Optional: nobody must have one. Every signed-in role may set their own and
only their own. JPEG, PNG or WEBP up to 10 MB (the CSP photo rules,
photo_intake.check_image); kept as a square JPEG of at most 256 x 256.
Changes are audited. Nothing to do with CSP photos (35 x 45 mm), which are
untouched.
"""

import hashlib
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_any_role
from app.models.audit_log import AuditLog
from app.models.user_photo import UserPhoto
from app.models.user_preference import UserPreference
from app.services import my_look, notification_prefs, photo_intake
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])

SIZE = 256


def _email(user: dict) -> str:
    return ((user or {}).get("sub") or (user or {}).get("email") or "").strip().lower()


def square_jpeg(data: bytes) -> bytes:
    """The middle square of the picture, at most SIZE x SIZE, as JPEG —
    turned upright first (phone photos carry their rotation separately)."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            # Transparent parts on white, not black.
            image = image.convert("RGBA")
            flat = Image.new("RGB", image.size, "white")
            flat.paste(image, mask=image.split()[-1])
            image = flat
        side = min(image.size)
        image = ImageOps.fit(image.convert("RGB"), (side, side),
                             method=Image.LANCZOS)
        if side > SIZE:
            image = image.resize((SIZE, SIZE), Image.LANCZOS)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=88)
        return out.getvalue()


def _audit(session, user, action: str, detail: dict) -> None:
    session.add(AuditLog(
        workspace_id=current_workspace_id(), action=action,
        resource_type="user", resource_id=_email(user), result="success",
        metadata_json={"by": _email(user), **detail}))


@router.put("/photo", summary="Upload or change your profile picture")
async def set_photo(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    data = await file.read(photo_intake.MAX_BYTES + 1)
    try:
        photo_intake.check_image(data)
        image = square_jpeg(data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        logger.warning("profile_router.set_photo: %s's picture could not be "
                       "read: %s: %s", _email(user), type(e).__name__, e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That picture could not be read. Please use a "
                            "JPEG or PNG.")
    email = _email(user)
    checksum = hashlib.sha256(image).hexdigest()
    row = await session.get(UserPhoto, email)
    if row is None:
        session.add(UserPhoto(email=email, image=image,
                              content_type="image/jpeg",
                              file_size=len(image), checksum=checksum))
    else:
        row.image, row.file_size, row.checksum = image, len(image), checksum
    _audit(session, user, "profile_photo_set", {"bytes": len(image)})
    await session.commit()
    logger.info("profile_router: %s set a profile picture (%d bytes)",
                email, len(image))
    return {"email": email, "version": checksum[:12]}


@router.delete("/photo", summary="Remove your profile picture")
async def remove_photo(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    row = await session.get(UserPhoto, _email(user))
    if row is not None:
        await session.delete(row)
        _audit(session, user, "profile_photo_remove", {})
        await session.commit()
        logger.info("profile_router: %s removed their profile picture",
                    _email(user))
    return {"email": _email(user), "removed": row is not None}


@router.get("/photo/{email}", summary="A person's profile picture")
async def get_photo(
    email: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    """404 when they have none — the screen then shows initials. Only your
    own, or someone in the workspace you are signed in to."""
    from app.services import workspace_service

    email = (email or "").strip().lower()
    if email != _email(user):
        ws = current_workspace_id()
        if ws is None or await workspace_service.membership(
                session, email, ws) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture.")
    row = await session.get(UserPhoto, email)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture.")
    return Response(row.image, media_type=row.content_type,
                    headers={"Cache-Control": "private, no-store",
                             "X-Photo-Version": row.checksum[:12]})


# ---- Your own look (No. 240, SaaS upgrade Stage 2) ------------------------
#
#   GET    /api/profile/appearance   your saved choices + what may be changed
#   PUT    /api/profile/appearance   save the whole set (replaces it)
#   PATCH  /api/profile/appearance   change some choices (null = as the
#                                    workspace has it); the header's
#                                    light / dark button uses this
#   DELETE /api/profile/appearance   back to the workspace's look
#
# Always and only the signed-in person's own row: no email in the path, so
# nobody can read or change someone else's. Checked by services/my_look.py.

class AppearanceBody(BaseModel):
    appearance: dict


def _own_colours_allowed() -> bool:
    from app.config import get_settings
    return bool(get_settings().allow_personal_look)


def _appearance_view(row: UserPreference | None, warnings=None) -> dict:
    return {
        "own_colours_allowed": _own_colours_allowed(),
        "appearance": dict(row.appearance or {}) if row else {},
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "options": my_look.options(),
        "warnings": warnings or [],
    }


async def _save_appearance(session, user, wanted: dict, how: str) -> dict:
    try:
        clean, warnings = my_look.check(wanted)
    except my_look.LookError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    email = _email(user)
    row = await session.get(UserPreference, email)
    before = dict(row.appearance or {}) if row else {}
    # No. 240 (Stage 3): the workspace may keep colours and font its own.
    # Then what was saved before stays as it was (and is not shown), and a
    # new colour or font is not taken.
    if not _own_colours_allowed():
        tried = sorted(k for k in my_look.WORKSPACE_LOCKABLE
                       if clean.get(k) != before.get(k))
        for k in my_look.WORKSPACE_LOCKABLE:
            clean.pop(k, None)
            if k in before:
                clean[k] = before[k]
        if tried:
            warnings.append("Your workspace sets the colours and font, so "
                            f"these were not changed: {', '.join(tried)}.")
    if row is None:
        row = UserPreference(email=email, appearance=clean, notifications={},
                             dashboards={})
        session.add(row)
    else:
        row.appearance = clean
    changed = sorted(k for k in set(before) | set(clean)
                     if before.get(k) != clean.get(k))
    if changed:
        _audit(session, user, "appearance_change", {"how": how, "changed": changed})
    await session.commit()
    await session.refresh(row)
    logger.info("profile_router: %s %s their appearance (%s)", email, how,
                ", ".join(changed) or "no change")
    return _appearance_view(row, warnings)


@router.get("/appearance", summary="Your own look and what you may change")
async def get_appearance(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    return _appearance_view(await session.get(UserPreference, _email(user)))


@router.put("/appearance", summary="Save your own look")
async def put_appearance(
    body: AppearanceBody,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    return await _save_appearance(session, user, body.appearance, "saved")


@router.patch("/appearance", summary="Change some of your own look")
async def patch_appearance(
    body: AppearanceBody,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    row = await session.get(UserPreference, _email(user))
    merged = dict(row.appearance or {}) if row else {}
    merged.update(body.appearance)
    return await _save_appearance(session, user, merged, "changed")


@router.delete("/appearance", summary="Back to the workspace's look")
async def reset_appearance(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    row = await session.get(UserPreference, _email(user))
    if row is not None:
        had = sorted(row.appearance or {})
        await session.delete(row)
        if had:
            _audit(session, user, "appearance_reset", {"changed": had})
        await session.commit()
        logger.info("profile_router: %s reset their appearance", _email(user))
    return _appearance_view(None)


# ---- What you are told, and how (No. 240, Stage 3) ------------------------
#
#   GET /api/profile/notifications   every staff notification, by channel
#   PUT /api/profile/notifications   {kind: {channel: on/off}}; a mandatory
#                                    one cannot be switched off (400)

class NotificationsBody(BaseModel):
    notifications: dict


@router.get("/notifications", summary="Your notifications")
async def get_notifications(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    row = await session.get(UserPreference, _email(user))
    return {"notifications": notification_prefs.view(row.notifications if row else {})}


@router.put("/notifications", summary="Change your notifications")
async def put_notifications(
    body: NotificationsBody,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    try:
        clean = notification_prefs.check(body.notifications)
    except notification_prefs.NotificationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    email = _email(user)
    row = await session.get(UserPreference, email)
    if row is None:
        row = UserPreference(email=email, appearance={}, notifications=clean,
                             dashboards={})
        session.add(row)
    else:
        row.notifications = clean
    _audit(session, user, "notifications_change",
           {"off": sorted(f"{k}:{c}" for k, chs in clean.items() for c in chs)})
    await session.commit()
    logger.info("profile_router: %s changed their notifications (%d off)",
                email, sum(len(v) for v in clean.values()))
    return {"notifications": notification_prefs.view(clean)}


# ---- Your own dashboard arrangement (No. 240, Stage 5) --------------------
#
#   GET    /api/profile/dashboards/{slug}   your order / hidden / columns
#   PUT    /api/profile/dashboards/{slug}   save them
#   DELETE /api/profile/dashboards/{slug}   back to the workspace's
#
# Only how YOUR screen arranges the workspace's widgets. The widgets, their
# numbers and who may see a dashboard are unchanged (dashboard_router).

class DashboardLayoutBody(BaseModel):
    order: list = []
    hidden: list = []
    columns: int | None = None


def _check_layout(body: DashboardLayoutBody) -> dict:
    import uuid as _uuid
    for name, ids in (("order", body.order), ("hidden", body.hidden)):
        if len(ids) > 200:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Too many widgets in {name}.")
        for i in ids:
            try:
                _uuid.UUID(str(i))
            except ValueError:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"{name}: {i!r} is not a widget.")
    if body.columns is not None and body.columns not in (1, 2, 3, 4):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Columns: 1, 2, 3 or 4.")
    out = {"order": [str(i) for i in body.order], "hidden": [str(i) for i in body.hidden]}
    if body.columns is not None:
        out["columns"] = body.columns
    return out


def _layout_key(slug: str) -> str:
    import re as _re
    if not _re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", slug or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a dashboard.")
    # Per workspace: the same slug in two workspaces is two dashboards.
    return f"{current_workspace_id()}:{slug}"


@router.get("/dashboards/{slug}", summary="Your arrangement of a dashboard")
async def get_dashboard_layout(
    slug: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    key = _layout_key(slug)
    row = await session.get(UserPreference, _email(user))
    return {"layout": ((row.dashboards or {}) if row else {}).get(key)}


@router.put("/dashboards/{slug}", summary="Save your arrangement of a dashboard")
async def put_dashboard_layout(
    slug: str,
    body: DashboardLayoutBody,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    key = _layout_key(slug)
    layout = _check_layout(body)
    email = _email(user)
    row = await session.get(UserPreference, email)
    if row is None:
        row = UserPreference(email=email, appearance={}, notifications={},
                             dashboards={key: layout})
        session.add(row)
    else:
        row.dashboards = {**(row.dashboards or {}), key: layout}
    _audit(session, user, "dashboard_layout_change", {"dashboard": slug})
    await session.commit()
    return {"layout": layout}


@router.delete("/dashboards/{slug}", summary="Back to the workspace's arrangement")
async def reset_dashboard_layout(
    slug: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    key = _layout_key(slug)
    row = await session.get(UserPreference, _email(user))
    if row is not None and key in (row.dashboards or {}):
        row.dashboards = {k: v for k, v in row.dashboards.items() if k != key}
        _audit(session, user, "dashboard_layout_reset", {"dashboard": slug})
        await session.commit()
    return {"layout": None}
