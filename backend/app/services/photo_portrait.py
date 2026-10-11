"""
CSP DocMaker — a studio portrait from the CSP's own photo

Confirmed 11 Oct 2026 (tracker No. 61): photos on documents should look
like a studio portrait — plain WHITE background, front-facing, head and
shoulders, even light — made by an AI service from the CSP's own photo.
The CSP keeps their own clothes. Fully automatic.

Two services, chosen by PHOTO_AI_PROVIDER:
  * cloudflare (default) — Workers AI, FLUX.2 [klein] 4B. Free daily
    allowance. Takes an input photo smaller than 512 x 512, so the photo is
    shrunk first; the face check matters all the more for it.
  * gemini — Google "Nano Banana". Paid per image.

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

# Words matter here: an earlier wording said "keep their ... glasses
# unchanged" and the free model ADDED glasses to three people who wear none
# (11 Oct 2026 test). So accessories are never named — only "add nothing".
PROMPT = (
    "Make a professional studio passport photo of exactly this person. "
    "The face must stay identical: same face shape, eyes, eyebrows, nose, "
    "mouth, skin tone, age and expression, and any bindi or sindoor exactly "
    "where it is. Keep exactly the clothes, hairstyle and jewellery they "
    "are wearing in this photo. Do not add anything that is not in the "
    "photo, and do not remove anything from the person. No beautifying, no "
    "slimming, no skin smoothing, no make-up. Change only these: a plain "
    "pure white background; the person facing the camera, head and "
    "shoulders, centred, with a little space above the head; soft, even "
    "studio lighting. Portrait orientation. Return only the photo."
)

_DONE = ".studio"
_REJECTED = ".studio-rejected"


def provider() -> str:
    from app.config import get_settings
    return (get_settings().photo_ai_provider or "").strip().lower()


def enabled() -> bool:
    """Switched on AND the chosen service has its credentials."""
    from app.config import get_settings
    s = get_settings()
    if not s.photo_ai_portrait:
        return False
    if provider() == "cloudflare":
        return bool((s.cloudflare_account_id or "").strip()
                    and (s.cloudflare_api_token or "").strip())
    if provider() == "gemini":
        return bool((s.gemini_api_key or "").strip())
    return False


def _fingerprint(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def _cache_paths(photo_path: str):
    stem, _ = os.path.splitext(photo_path)
    key = _fingerprint(photo_path)
    # A rejection is remembered per service: one that failed the face check
    # must not stop the other from being tried.
    return (f"{stem}{_DONE}.{key}.png",
            f"{stem}{_REJECTED}.{provider()}.{key}")


# Cloudflare's FLUX.2 [klein] takes input images smaller than 512 x 512.
CF_INPUT = (392, 504)          # the passport shape, 7:9, inside that limit
CF_OUTPUT = (784, 1008)        # 7:9 again; the API allows 256-1920


def _ask_cloudflare(photo_path: str) -> bytes:
    """The portrait's image bytes from Workers AI. Raises on any failure."""
    import io

    import httpx
    from PIL import Image

    from app.config import get_settings
    from app.services import template_service

    s = get_settings()
    shaped = template_service.passport_crop(photo_path)
    try:
        with Image.open(shaped) as image:
            small = image.convert("RGB").resize(CF_INPUT, Image.LANCZOS)
        buffer = io.BytesIO()
        small.save(buffer, "PNG")
    finally:
        if shaped != photo_path and os.path.exists(shaped):
            os.remove(shaped)

    url = (f"https://api.cloudflare.com/client/v4/accounts/"
           f"{s.cloudflare_account_id.strip()}/ai/run/"
           f"{s.cloudflare_image_model}")
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {s.cloudflare_api_token.strip()}"},
        data={"prompt": "The person in image 0. " + PROMPT,
              "width": str(CF_OUTPUT[0]), "height": str(CF_OUTPUT[1])},
        files={"input_image_0": ("photo.png", buffer.getvalue(),
                                 "image/png")},
        timeout=s.gemini_timeout_seconds,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Cloudflare answered HTTP "
                           f"{response.status_code}: {response.text[:300]}")
    if response.headers.get("content-type", "").startswith("image/"):
        return response.content
    body = response.json()
    result = body.get("result", body) if isinstance(body, dict) else {}
    image = (result or {}).get("image")
    if not image:
        raise RuntimeError(f"Cloudflare's answer contained no image: "
                           f"{str(body)[:300]}")
    return base64.b64decode(image)


def _ask(photo_path: str) -> bytes:
    if provider() == "cloudflare":
        return _ask_cloudflare(photo_path)
    return _ask_gemini(photo_path)


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

    from app.config import get_settings

    tries = max(1, get_settings().photo_ai_attempts)
    handle, attempt = tempfile.mkstemp(suffix=".png", prefix="portrait_")
    os.close(handle)
    try:
        for number in range(1, tries + 1):
            try:
                image = _ask(photo_path)
            except Exception as e:
                # Not remembered as rejected: the service being down is not
                # a verdict on the photo, so it is tried again next time.
                logger.warning("photo_portrait: no portrait for %s: %s",
                               os.path.basename(photo_path), e)
                return None
            with open(attempt, "wb") as f:
                f.write(image)

            if face_match.same_person(photo_path, attempt):
                os.replace(attempt, done)
                logger.info("photo_portrait: studio portrait made for %s "
                            "(try %d of %d)", os.path.basename(photo_path),
                            number, tries)
                return done
            logger.info("photo_portrait: try %d of %d for %s did not match",
                        number, tries, os.path.basename(photo_path))

        logger.warning("photo_portrait: no portrait of %s matched in %d "
                       "tries — using the original",
                       os.path.basename(photo_path), tries)
        open(rejected, "w").close()
        return None
    finally:
        if os.path.exists(attempt):
            os.remove(attempt)
