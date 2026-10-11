"""Fetch the two OpenCV face models the AI-portrait face check needs.

Run once on a new machine:  python scripts/download_face_models.py
Each file is checked against the fingerprint recorded on 11 Oct 2026; a
file that does not match is deleted rather than used.
"""
import hashlib
import os
import sys
import urllib.request

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "face_recognition_sface_2021dec.onnx": (
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}
TARGET = os.path.join(os.path.dirname(__file__), "..", "app", "assets", "models")


def main() -> int:
    os.makedirs(TARGET, exist_ok=True)
    for name, (path, expected) in MODELS.items():
        dest = os.path.join(TARGET, name)
        if not os.path.isfile(dest):
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(BASE + path, dest)
        actual = hashlib.sha256(open(dest, "rb").read()).hexdigest()
        if actual != expected:
            os.remove(dest)
            print(f"{name}: fingerprint mismatch — deleted")
            return 1
        print(f"{name}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
