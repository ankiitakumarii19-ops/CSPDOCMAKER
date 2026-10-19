"""
CSP DocMaker — where is the face in a photo?

OpenCV's YuNet face detector, used by studio_photo to level and frame the
passport photo. It runs on this machine and nothing is sent anywhere. The
model lives in app/assets/models (YuNet 2023mar, from opencv_zoo).

(The face-similarity check that judged AI-made portraits went with the AI
portrait itself — tracker No. 116, 19 Oct 2026.)
"""

import os

_MODELS = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "assets", "models")
DETECTOR_MODEL = os.path.join(_MODELS, "face_detection_yunet_2023mar.onnx")


def _largest_face(image):
    import cv2

    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(DETECTOR_MODEL, "", (width, height),
                                         0.8, 0.3, 5000)
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[2] * f[3])
