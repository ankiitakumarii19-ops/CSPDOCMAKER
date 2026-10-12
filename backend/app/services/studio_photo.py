"""
CSP DocMaker — a passport-style photo made on this machine

Chosen 11 Oct 2026 (tracker No. 67), after the AI services were tried: a
plain WHITE background and passport framing, with the person's real face.
Nothing is generated and nothing leaves the machine.

Since 12 Oct 2026 (tracker No. 72) this is THE photo on every document —
the Cloudflare AI portrait is off — and a new KO's or Sub-KO's photo is
edited automatically as soon as the automation has it. Deterministic: the
same photo always gives the same result.

  1. Find the face (OpenCV YuNet, already used for the face check).
  2. Level the head: the whole photo is turned so the eyes are level —
     at most 15 degrees. The face itself is not altered.
  3. Cut the person out (rembg, model u2net_human_seg, run locally) and
     put them on pure white.
  4. Frame it like a passport photo: the face centred, a little space above
     the head, head and shoulders, 35:45. A distant selfie is zoomed in;
     where the frame runs past the photo's edge it is simply white.
  5. The light touch-up (template_service.touch_up).

Pixels of the person are never invented or changed, only moved as a whole
(turned, zoomed). If any step cannot be done — no face found, the cut-out
model missing — None is returned and the photo is used as before.

The result is kept beside the photo, so it is made once per photo.
"""

import hashlib
import logging
import math
import os
from typing import Optional
from app import telemetry

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "assets", "models", "rembg")
MODEL_NAME = "u2net_human_seg"

# Passport framing, as fractions of the finished photo's height.
FACE_HEIGHT = 0.40        # the detected face box (brow to chin, roughly)
FACE_CENTRE_Y = 0.43      # where the middle of that box sits
MAX_FACE_HEIGHT = 0.62    # zoomed in no further than this
MAX_TILT_DEGREES = 15

_TAG = ".white"
_session = None


def _session_for_cutout():
    global _session
    if _session is None:
        os.environ.setdefault("U2NET_HOME", MODEL_DIR)
        from rembg import new_session
        _session = new_session(MODEL_NAME)
    return _session


def output_size():
    """The finished photo in pixels, from the configured mm and DPI."""
    from app.config import get_settings
    s = get_settings()
    return (int(round(s.passport_photo_width_mm / 25.4 * s.passport_photo_dpi)),
            int(round(s.passport_photo_height_mm / 25.4 * s.passport_photo_dpi)))


def _cache_path(photo_path: str) -> str:
    with open(photo_path, "rb") as f:
        key = hashlib.sha256(f.read()).hexdigest()[:16]
    stem, _ = os.path.splitext(photo_path)
    w, h = output_size()
    # The size is part of the name, so changing it makes a fresh photo.
    return f"{stem}{_TAG}.{w}x{h}.{key}.png"


def cached_for(photo_path: str) -> Optional[str]:
    """The passport version already made for this photo, or None. Never
    builds one (that is make()); used to file it in the database."""
    if not photo_path or not os.path.isfile(photo_path):
        return None
    done = _cache_path(photo_path)
    return done if os.path.isfile(done) else None


def prepare_for(csp) -> Optional[str]:
    """Edit this agent's photo now, if they have one (No. 72).

    Called by the automation when a new KO or Sub-KO is picked up, so the
    edited photo exists before any document needs it. Safe to call often:
    a finished photo is reused.
    """
    photo = (getattr(csp, "photo_url", None) or "").strip()
    if not photo or not os.path.isfile(photo):
        return None
    return make(photo)


def _face(image_bgr):
    """(x, y, w, h, right_eye, left_eye) of the largest face, or None."""
    import cv2
    from app.services import face_match

    for size in (640, 1000, 400):
        scale = size / max(image_bgr.shape[:2])
        small = cv2.resize(image_bgr, None, fx=scale, fy=scale)
        face = face_match._largest_face(small)
        if face is not None:
            f = [float(v) / scale for v in face[:14]]
            return (f[0], f[1], f[2], f[3], (f[4], f[5]), (f[6], f[7]))
    return None


@telemetry.traced("make_passport_photo", "studio_photo")
def make(photo_path: str) -> Optional[str]:
    """The white-background passport photo for this photo, or None."""
    if not photo_path or not os.path.isfile(photo_path):
        return None
    from app.services import template_service
    if os.path.abspath(photo_path) == os.path.abspath(
            template_service.PLACEHOLDER_PHOTO):
        return None

    done = _cache_path(photo_path)
    if os.path.isfile(done):
        return done

    try:
        result = _build(photo_path)
    except Exception as e:
        logger.warning("studio_photo: could not make a white-background "
                       "photo of %s: %s: %s", os.path.basename(photo_path),
                       type(e).__name__, e)
        return None
    if result is None:
        return None
    result.save(done, "PNG", optimize=True)
    logger.info("studio_photo: white-background photo made for %s",
                os.path.basename(photo_path))
    return done


def _build(photo_path: str):
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    with Image.open(photo_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    # Big phone photos are reduced first: plenty for a 35 x 45 mm print.
    image.thumbnail((2000, 2000))

    bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    face = _face(bgr)
    if face is None:
        logger.info("studio_photo: no face found in %s",
                    os.path.basename(photo_path))
        return None
    x, y, w, h, eye_a, eye_b = face

    # 2. Level the head.
    angle = math.degrees(math.atan2(eye_b[1] - eye_a[1], eye_b[0] - eye_a[0]))
    if abs(angle) > 90:
        angle -= 180 * (1 if angle > 0 else -1)
    angle = max(-MAX_TILT_DEGREES, min(MAX_TILT_DEGREES, angle))
    centre = (x + w / 2, y + h / 2)

    # 3. Cut out, then onto white.
    from rembg import remove
    cut = remove(image, session=_session_for_cutout())        # RGBA
    valid = Image.new("L", cut.size, 255)    # where the photo has pixels
    if abs(angle) > 0.5:
        cut = cut.rotate(angle, resample=Image.BICUBIC, center=centre,
                         expand=False)
        valid = valid.rotate(angle, resample=Image.NEAREST, center=centre,
                             expand=False)
    # Soften the very edge so a coloured wall does not leave a fringe.
    alpha = cut.split()[3].point(lambda a: 0 if a < 24 else a)
    white = Image.new("RGB", cut.size, "white")
    white.paste(cut.convert("RGB"), mask=alpha)

    # 4. Passport framing around the (levelled) face.
    box = _frame(centre, h, np.asarray(alpha) > 128, np.asarray(valid) > 0)
    canvas = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), "white")
    canvas.paste(white, (-box[0], -box[1]))
    framed = canvas.resize(output_size(), Image.LANCZOS)

    # 5. The light touch-up, on the finished photo.
    import tempfile
    handle, staged = tempfile.mkstemp(suffix=".png", prefix="white_")
    os.close(handle)
    try:
        framed.save(staged, "PNG")
        touched = template_service_touch_up(staged)
        try:
            with Image.open(touched) as finished:
                return finished.copy()
        finally:
            os.remove(touched)
    finally:
        os.remove(staged)


def _frame(centre, face_h, person, valid):
    """The crop box: passport framing that never shows a cut edge.

    Ideally the face is FACE_HEIGHT of the frame, centred, with the face's
    middle at FACE_CENTRE_Y. But where the person runs off the photo — a
    selfie cut at the shoulders, a head cut at the top — framing past that
    edge would show a white gap with the body ending in a straight line. So
    on any side the person touches, the frame stops at the photo's edge and
    the photo is zoomed in a little instead, never beyond the face filling
    MAX_FACE_HEIGHT of the frame.
    """
    import numpy as np

    out_w, out_h = output_size()
    cx, cy = centre
    height, width = valid.shape
    # Where the person's body ends at the top and bottom, and whether it
    # ends there because the PHOTO ends (cut off) rather than the person.
    # Measured on the person themselves: after levelling, a photo has blank
    # wedges at its corners, and those must not be mistaken for its edges.
    # The sides are left alone: shoulders running off the sides is normal
    # in a passport photo.
    band = 6
    limits = {}
    rows = np.where(person.any(axis=1))[0]
    if len(rows):
        for side, row, beyond in (("top", int(rows[0]), int(rows[0]) - band),
                                  ("bottom", int(rows[-1]) + 1,
                                   int(rows[-1]) + band)):
            line = person[min(max(row if side == "top" else row - 1, 0),
                              height - 1)]
            cols = np.where(line)[0]
            if not len(cols):
                continue
            if beyond < 0 or beyond >= height:
                cut = True                       # the photo ends right here
            else:
                cut = not valid[beyond, cols].mean() > 0.5
            if cut:
                # After levelling, the photo's own edge slopes; stop at its
                # nearest point under the person, so no white sliver shows.
                # Every column the body covers near that end, not only the
                # single lowest (or highest) row, which after levelling is
                # just one corner of the slope.
                reach = max(band, int(0.15 * (rows[-1] - rows[0])))
                region = (person[max(0, row - reach):row] if side == "bottom"
                          else person[row:row + reach])
                span = np.where(region.any(axis=0))[0]
                if side == "bottom":
                    edge = [height - int(np.argmax(valid[::-1, c]))
                            for c in span]
                    row = min([row] + edge)
                else:
                    edge = [int(np.argmax(valid[:, c])) for c in span]
                    row = max([row] + edge)
                limits[side] = row

    frame_h = face_h / FACE_HEIGHT
    if "bottom" in limits:
        frame_h = min(frame_h, (limits["bottom"] - cy) / (1 - FACE_CENTRE_Y))
    if "top" in limits:
        frame_h = min(frame_h, (cy - limits["top"]) / FACE_CENTRE_Y)
    frame_h = max(frame_h, face_h / MAX_FACE_HEIGHT)
    if "top" in limits and "bottom" in limits:
        # Both edges are cut: the frame must fit between them.
        frame_h = min(frame_h, limits["bottom"] - limits["top"])
    frame_w = frame_h * out_w / out_h

    left = cx - frame_w / 2
    top = cy - FACE_CENTRE_Y * frame_h
    # If zooming could not go far enough, slide rather than show a gap.
    if "bottom" in limits and top + frame_h > limits["bottom"]:
        top = limits["bottom"] - frame_h
    if "top" in limits and top < limits["top"]:
        top = limits["top"]
    return tuple(int(round(v)) for v in
                 (left, top, left + frame_w, top + frame_h))


def template_service_touch_up(path: str) -> str:
    from app.services import template_service
    return template_service.touch_up(path)
