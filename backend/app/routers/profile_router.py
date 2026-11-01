"""
CSP DocMaker — your profile picture (No. 171)

  GET    /api/profile/photo/{email}   the picture (signed in; your own, or a
                                      member of the workspace you are in)
  PUT    /api/profile/photo           upload / change your own
  DELETE /api/profile/photo           remove your own — initials again

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_any_role
from app.models.audit_log import AuditLog
from app.models.user_photo import UserPhoto
from app.services import photo_intake
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
