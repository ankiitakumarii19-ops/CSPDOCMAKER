"""
CSP DocMaker — is this the same person?

Used to check an AI-made studio portrait against the CSP's own photo
(tracker No. 61). The AI re-draws the picture; if it drifts into someone who
does not look like the CSP, the portrait is thrown away and the CSP's own
photo is used instead. On an identity card that is not optional.

OpenCV's YuNet finds the face and SFace turns it into a fingerprint; two
fingerprints are compared by cosine similarity. Both models are OpenCV's
own, run on this machine, and nothing is sent anywhere. They live in
app/assets/models (YuNet 2023mar, SFace 2021dec, from opencv_zoo).

OpenCV's published threshold for "same person" with SFace is 0.363. The
default here is stricter; see FACE_MATCH_THRESHOLD in the settings.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_MODELS = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "assets", "models")
DETECTOR_MODEL = os.path.join(_MODELS, "face_detection_yunet_2023mar.onnx")
RECOGNIZER_MODEL = os.path.join(_MODELS, "face_recognition_sface_2021dec.onnx")

OPENCV_SAME_PERSON = 0.363


class FaceMatchError(RuntimeError):
    """The check could not be made (no face found, model missing)."""


def _largest_face(image):
    import cv2

    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(DETECTOR_MODEL, "", (width, height),
                                         0.8, 0.3, 5000)
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[2] * f[3])


def _fingerprint(path: str):
    import cv2

    for model in (DETECTOR_MODEL, RECOGNIZER_MODEL):
        if not os.path.isfile(model):
            raise FaceMatchError(f"face model missing: {model}")
    image = cv2.imread(path)
    if image is None:
        raise FaceMatchError(f"cannot read image: {path}")
    # The detector misses a face that fills a very large photo (Nitasha's
    # 3135 px portrait: nothing at 1600 px, found at 1000 and below), so the
    # photo is looked at at a few ordinary sizes, most reliable first.
    original = image
    face = None
    for size in (640, 1000, 400):
        scale = size / max(original.shape[:2])
        image = cv2.resize(original, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA if scale < 1
                           else cv2.INTER_LINEAR)
        face = _largest_face(image)
        if face is not None:
            break
    if face is None:
        raise FaceMatchError(f"no face found in {os.path.basename(path)}")
    recognizer = cv2.FaceRecognizerSF.create(RECOGNIZER_MODEL, "")
    return recognizer, recognizer.feature(recognizer.alignCrop(image, face))


def similarity(path_a: str, path_b: str) -> float:
    """Cosine similarity of the two largest faces: higher = more alike."""
    import cv2

    recognizer, a = _fingerprint(path_a)
    _, b = _fingerprint(path_b)
    return float(recognizer.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))


def same_person(path_a: str, path_b: str,
                threshold: Optional[float] = None) -> bool:
    """True only when both faces are found and they match.

    Any failure — no face, unreadable file — answers False: a portrait that
    cannot be checked is not used.
    """
    if threshold is None:
        from app.config import get_settings
        threshold = get_settings().face_match_threshold
    try:
        score = similarity(path_a, path_b)
    except FaceMatchError as e:
        logger.warning("face_match: could not compare: %s", e)
        return False
    logger.info("face_match: similarity %.3f (needs %.3f)", score, threshold)
    return score >= threshold
