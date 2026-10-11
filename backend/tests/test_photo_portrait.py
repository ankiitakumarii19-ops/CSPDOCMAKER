"""AI studio portrait (tracker No. 61, 11 Oct 2026).

Google is never called here: the request is replaced, and so is the face
check where a test needs a particular verdict. What is being pinned is the
safety around the portrait: it is used only when it shows the same person,
the original is never touched, and nothing is paid for twice.
"""

import base64
import hashlib
import shutil

import pytest

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import (
    document_service, face_match, photo_portrait, template_service,
)


@pytest.fixture
def switched_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "photo_ai_portrait", True)
    monkeypatch.setattr(s, "gemini_api_key", "test-key")


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "1A850344.png"
    shutil.copy(template_service.PLACEHOLDER_PHOTO, path)
    return str(path)


class _Reply:
    def __init__(self, status=200, image=b"", text=""):
        self.status_code, self.text = status, text
        self._image = image

    def json(self):
        if not self._image:
            return {"candidates": [{"content": {"parts": [{"text": "no"}]}}]}
        return {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png",
                            "data": base64.b64encode(self._image).decode()}}
        ]}}]}


@pytest.fixture
def gemini(monkeypatch):
    """Google's reply: by default, a copy of the photo it was sent."""
    calls = []

    def post(url, json, timeout, headers):
        calls.append({"url": url, "headers": headers, "body": json})
        sent = json["contents"][0]["parts"][1]["inline_data"]["data"]
        return _Reply(image=base64.b64decode(sent))

    import httpx
    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_off_without_a_key(photo, gemini, monkeypatch):
    monkeypatch.setattr(get_settings(), "photo_ai_portrait", True)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    assert photo_portrait.studio_portrait(photo) is None
    assert gemini == [], "Google was called with no key"


def test_a_matching_portrait_is_used_and_kept(switched_on, photo, gemini,
                                              monkeypatch):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: True)
    portrait = photo_portrait.studio_portrait(photo)
    assert portrait and portrait != photo
    # The request: the right model, the key in the header, white background
    # asked for, own clothes kept.
    call = gemini[0]
    assert get_settings().gemini_image_model in call["url"]
    assert call["headers"]["x-goog-api-key"] == "test-key"
    prompt = call["body"]["contents"][0]["parts"][0]["text"]
    assert "white background" in prompt and "own clothes" in prompt


def test_a_portrait_is_paid_for_once(switched_on, photo, gemini, monkeypatch):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: True)
    first = photo_portrait.studio_portrait(photo)
    second = photo_portrait.studio_portrait(photo)
    assert first == second
    assert len(gemini) == 1, "the same photo was sent to Google twice"


def test_someone_else_is_thrown_away_and_not_retried(switched_on, photo,
                                                     gemini, monkeypatch):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: False)
    assert photo_portrait.studio_portrait(photo) is None
    assert photo_portrait.studio_portrait(photo) is None
    assert len(gemini) == 1, "a rejected photo was sent again"


def test_google_failing_falls_back_and_tries_again_later(switched_on, photo,
                                                         monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: (calls.append(1),
                                         _Reply(503, text="busy"))[1])
    assert photo_portrait.studio_portrait(photo) is None
    assert photo_portrait.studio_portrait(photo) is None
    assert len(calls) == 2, "an outage must not be remembered as a verdict"


def test_an_answer_without_an_image_falls_back(switched_on, photo,
                                               monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Reply(image=b""))
    assert photo_portrait.studio_portrait(photo) is None


def test_the_placeholder_is_never_sent(switched_on, gemini):
    assert photo_portrait.studio_portrait(
        template_service.PLACEHOLDER_PHOTO) is None
    assert gemini == []


def test_a_document_uses_the_portrait_and_leaves_the_original_alone(
        switched_on, photo, gemini, monkeypatch, tmp_path):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: True)
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path / "out"))
    before = hashlib.sha256(open(photo, "rb").read()).hexdigest()
    csp = CSPRecord(csp_id="1A850344", csp_code="1A850344", name="P",
                    branch_name="B", branch_code="1", address="A",
                    mobile="9876543210", photo_url=photo)
    (_, path), = document_service.generate_documents(
        csp, [DocumentType.CSP_ID_CARD])
    assert template_service.count_images(path) > template_service.count_images(
        template_service.template_path(DocumentType.CSP_ID_CARD))
    assert len(gemini) == 1
    assert hashlib.sha256(open(photo, "rb").read()).hexdigest() == before


def test_the_face_check_needs_a_face(tmp_path):
    """No face, no match: a portrait that cannot be checked is not used."""
    from PIL import Image
    blank = tmp_path / "blank.png"
    Image.new("RGB", (350, 450), "white").save(blank)
    assert face_match.same_person(str(blank), str(blank)) is False


def test_the_threshold_is_the_measured_one():
    assert get_settings().face_match_threshold == pytest.approx(0.60)
    assert get_settings().face_match_threshold > face_match.OPENCV_SAME_PERSON
