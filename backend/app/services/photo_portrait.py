"""
CSP DocMaker — a studio portrait from the CSP's own photo

Confirmed 11 Oct 2026 (tracker No. 61): photos on documents should look
like a studio portrait — plain WHITE background, front-facing, head and
shoulders, even light — made by Google Gemini ("Nano Banana") from the
CSP's own photo. The CSP keeps their own clothes. Fully automatic.

The safeguards, because this goes on an identity card:

  * Every portrait is checked against the CSP's own photo by face_match.
    One that does not clearly show the same person is thrown away and the
    CSP's own photo (with the light touch-up) is used instead.
  * The CSP's original photo is never changed or deleted.
  * A portrait is made ONCE per photo and kept beside it, so a CSP's four
    documents — and every later reissue — reuse it rather than paying for
    a new one. A rejected attempt is remembered too, so the same photo is
    not sent again and again.
  * Anything going wrong — no key, Google unreachable, an answer with no
    image — falls back to the CSP's own photo. A document is never held up
    by this step.

The photo is sent to Google. That was accepted when this was chosen.
"""

import base64
import hashlib
import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

PROMPT = (
    "Turn this photo into a professional studio passport-style portrait of "
    "the SAME person. Keep their face exactly as it is: the same facial "
    "features, face shape, eyes, nose, mouth, skin tone, age, expression and "
    "any marks such as a bindi or sindoor. Do not beautify, slim, smooth the "
    "skin or add make-up. Keep their own clothes, hairstyle, jewellery and "
    "glasses unchanged. Change only: a plain pure white background; the "
    "person facing the camera, head and shoulders, centred, with a little "
    "space above the head; soft, even studio lighting. Portrait orientation. "
    "Return only the photo."
)

_DONE = ".studio"
_REJECTED = ".studio-rejected"


def enabled() -> bool:
    from app.config import get_settings
    s = get_settings()
    return bool(s.photo_ai_portrait and (s.gemini_api_key or "").strip())


def _fingerprint(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def _cache_paths(photo_path: str):
    stem, _ = os.path.splitext(photo_path)
    key = _fingerprint(photo_path)
    return f"{stem}{_DONE}.{key}.png", f"{stem}{_REJECTED}.{key}"


def _ask_gemini(photo_path: str) -> bytes:
    """The portrait's image bytes. Raises on any failure."""
    import httpx

    from app.config import get_settings

    s = get_settings()
    ext = os.path.splitext(photo_path)[1].lower()
    mime = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    with open(photo_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")

    url = (f"{s.gemini_api_base.rstrip('/')}/models/"
           f"{s.gemini_image_model}:generateContent")
    body = {"contents": [{"parts": [
        {"text": PROMPT},
        {"inline_data": {"mime_type": mime, "data": data}},
    ]}]}
    response = httpx.post(
        url, json=body, timeout=s.gemini_timeout_seconds,
        headers={"x-goog-api-key": s.gemini_api_key.strip(),
                 "Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise RuntimeError(f"Gemini answered HTTP {response.status_code}: "
                           f"{response.text[:300]}")
    for candidate in response.json().get("candidates", []):
        for part in (candidate.get("content") or {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise RuntimeError("Gemini's answer contained no image")


def studio_portrait(photo_path: str) -> Optional[str]:
    """The checked studio portrait for this photo, or None to use the photo.

    None whenever the portrait is switched off, cannot be made, or does not
    clearly show the same person.
    """
    if not enabled() or not photo_path or not os.path.isfile(photo_path):
        return None
    from app.services import template_service
    if os.path.abspath(photo_path) == os.path.abspath(
            template_service.PLACEHOLDER_PHOTO):
        return None

    done, rejected = _cache_paths(photo_path)
    if os.path.isfile(done):
        return done
    if os.path.isfile(rejected):
        return None

    from app.services import face_match

    handle, attempt = tempfile.mkstemp(suffix=".png", prefix="portrait_")
    os.close(handle)
    try:
        try:
            image = _ask_gemini(photo_path)
        except Exception as e:
            # Not remembered as rejected: Google being down is not a verdict
            # on the photo, so it is tried again next time.
            logger.warning("photo_portrait: no portrait for %s: %s",
                           os.path.basename(photo_path), e)
            return None
        with open(attempt, "wb") as f:
            f.write(image)

        if not face_match.same_person(photo_path, attempt):
            logger.warning("photo_portrait: portrait of %s does not match "
                           "the original — using the original",
                           os.path.basename(photo_path))
            open(rejected, "w").close()
            return None

        os.replace(attempt, done)
        logger.info("photo_portrait: studio portrait made for %s",
                    os.path.basename(photo_path))
        return done
    finally:
        if os.path.exists(attempt):
            os.remove(attempt)
