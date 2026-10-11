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
    monkeypatch.setattr(s, "photo_ai_provider", "gemini")
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
    monkeypatch.setattr(get_settings(), "photo_ai_provider", "gemini")
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
    assert "white background" in prompt and "clothes" in prompt
    # Naming an accessory made the model ADD it (glasses, 11 Oct 2026 test).
    # Naming a thing makes the model add it: "bindi" put one on three men.
    for word in ("glasses", "bindi", "sindoor"):
        assert word not in prompt.lower()
    assert "Do not add anything" in prompt


def test_a_portrait_is_paid_for_once(switched_on, photo, gemini, monkeypatch):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: True)
    first = photo_portrait.studio_portrait(photo)
    second = photo_portrait.studio_portrait(photo)
    assert first == second
    assert len(gemini) == 1, "the same photo was sent to Google twice"


def test_someone_else_is_thrown_away_and_not_retried(switched_on, photo,
                                                     gemini, monkeypatch):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: False)
    tries = get_settings().photo_ai_attempts
    assert photo_portrait.studio_portrait(photo) is None
    assert len(gemini) == tries, "each photo gets its few tries"
    assert photo_portrait.studio_portrait(photo) is None
    assert len(gemini) == tries, "a rejected photo was sent again"


def test_a_later_try_that_matches_is_used(switched_on, photo, gemini,
                                          monkeypatch):
    verdicts = iter([False, True])
    monkeypatch.setattr(face_match, "same_person",
                        lambda a, b: next(verdicts))
    assert photo_portrait.studio_portrait(photo)
    assert len(gemini) == 2, "stopped at the first matching try"


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



# ---- Cloudflare Workers AI (the default, chosen 11 Oct 2026) -------------

@pytest.fixture
def cloudflare(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "photo_ai_portrait", True)
    monkeypatch.setattr(s, "photo_ai_provider", "cloudflare")
    monkeypatch.setattr(s, "cloudflare_account_id", "acct123")
    monkeypatch.setattr(s, "cloudflare_api_token", "cf-token")
    calls = []

    class _CF:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def __init__(self, image):
            self._image = image

        def json(self):
            return {"success": True, "result": {
                "image": base64.b64encode(self._image).decode()}}

    def post(url, headers, data, files, timeout):
        calls.append({"url": url, "headers": headers, "data": data,
                      "files": files})
        return _CF(files["input_image_0"][1])   # echo the photo back

    import httpx
    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_cloudflare_is_the_default_provider():
    from app.config import Settings
    assert Settings.model_fields["photo_ai_provider"].default == "cloudflare"
    assert photo_portrait.CF_INPUT[0] < 512 and photo_portrait.CF_INPUT[1] < 512


def test_cloudflare_needs_both_account_and_token(photo, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "photo_ai_portrait", True)
    monkeypatch.setattr(s, "photo_ai_provider", "cloudflare")
    monkeypatch.setattr(s, "cloudflare_account_id", "acct123")
    monkeypatch.setattr(s, "cloudflare_api_token", "")
    assert photo_portrait.enabled() is False


def test_the_cloudflare_request(cloudflare, photo, monkeypatch):
    import io
    from PIL import Image

    monkeypatch.setattr(face_match, "same_person", lambda a, b: True)
    assert photo_portrait.studio_portrait(photo)
    call = cloudflare[0]
    assert call["url"] == ("https://api.cloudflare.com/client/v4/accounts/"
                           "acct123/ai/run/@cf/black-forest-labs/"
                           "flux-2-klein-9b")
    assert call["headers"]["Authorization"] == "Bearer cf-token"
    assert "white background" in call["data"]["prompt"]
    assert "glasses" not in call["data"]["prompt"].lower()
    sent = Image.open(io.BytesIO(call["files"]["input_image_0"][1]))
    assert sent.size[0] < 512 and sent.size[1] < 512, (
        "Cloudflare refuses input images of 512 x 512 or larger")


def test_a_cloudflare_rejection_does_not_block_gemini(cloudflare, photo,
                                                      monkeypatch):
    monkeypatch.setattr(face_match, "same_person", lambda a, b: False)
    assert photo_portrait.studio_portrait(photo) is None
    monkeypatch.setattr(get_settings(), "photo_ai_provider", "gemini")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "g-key")
    done, rejected = photo_portrait._cache_paths(photo)
    import os
    assert not os.path.exists(rejected), (
        "Cloudflare's rejection must not stop Gemini being tried")


# ---- documents wait for the portrait (tracker No. 70, 12 Oct 2026) -------

def _agent(photo):
    from app.models.csp_record import CSPRecord
    return CSPRecord(csp_id="1A850344", csp_code="1A850344", name="Wait",
                     branch_name="B", branch_code="1", address="A",
                     mobile="9876543210", photo_url=photo)


def test_a_document_with_a_photo_waits_for_the_portrait(switched_on, photo):
    from app.services.missing_data_service import check_missing_data
    check = check_missing_data(_agent(photo), [DocumentType.CSP_ID_CARD,
                                               DocumentType.CSP_CERTIFICATE])
    by_doc = {d.document_type: [f.field_name for f in d.missing_fields]
              for d in check.documents}
    assert "studio_photo" in by_doc[DocumentType.CSP_ID_CARD]
    assert "studio_photo" not in by_doc[DocumentType.CSP_CERTIFICATE], (
        "the Appointment Letter has no photo, so it never waits")


def test_once_the_portrait_exists_nothing_waits(switched_on, photo, gemini,
                                                monkeypatch):
    from app.services.missing_data_service import check_missing_data
    monkeypatch.setattr(face_match, "same_person", lambda a, b: True)
    assert photo_portrait.prepare_for(_agent(photo))
    check = check_missing_data(_agent(photo), [DocumentType.CSP_ID_CARD])
    assert not any(f.field_name == "studio_photo"
                   for d in check.documents for f in d.missing_fields)


def test_the_check_itself_never_calls_the_ai(switched_on, photo, gemini):
    from app.services.missing_data_service import check_missing_data
    check_missing_data(_agent(photo), [DocumentType.CSP_ID_CARD])
    assert gemini == [], "a dashboard or check must not spend AI calls"


def test_nothing_waits_when_the_ai_is_off(photo, monkeypatch):
    from app.services.missing_data_service import check_missing_data
    monkeypatch.setattr(get_settings(), "photo_ai_portrait", False)
    check = check_missing_data(_agent(photo), [DocumentType.CSP_ID_CARD])
    assert not any(f.field_name == "studio_photo"
                   for d in check.documents for f in d.missing_fields)


def test_a_rejected_photo_gets_new_tries_the_next_day(switched_on, photo,
                                                      gemini, monkeypatch):
    import os
    import time
    monkeypatch.setattr(face_match, "same_person", lambda a, b: False)
    assert photo_portrait.studio_portrait(photo) is None
    tries = len(gemini)
    assert photo_portrait.studio_portrait(photo) is None
    assert len(gemini) == tries, "retried the same day"

    _, rejected = photo_portrait._cache_paths(photo)
    yesterday = time.time() - 86400
    os.utime(rejected, (yesterday, yesterday))
    photo_portrait.studio_portrait(photo)
    assert len(gemini) == 2 * tries, "not retried the next day"
