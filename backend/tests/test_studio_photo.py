"""White background and passport framing, made locally (tracker No. 67).

Real faces are personal data and are not kept with the code, so the framing
is tested on drawn shapes, and the pipeline's safety on stand-ins.
"""

import hashlib
import shutil

import numpy as np
import pytest
from PIL import Image

from app.services import studio_photo, template_service

OUT_RATIO = studio_photo.OUTPUT_SIZE[0] / studio_photo.OUTPUT_SIZE[1]


def _masks(height=1000, width=800, body_to_bottom=True, head_top=150):
    """A 'person' (head + body) inside a photo, as the cut-out sees it."""
    person = np.zeros((height, width), dtype=bool)
    person[head_top:420, 300:500] = True                     # head
    person[420:height if body_to_bottom else 800, 150:650] = True   # body
    valid = np.ones((height, width), dtype=bool)
    return person, valid


def test_a_body_cut_by_the_photo_never_shows_a_white_gap():
    person, valid = _masks(body_to_bottom=True)
    left, top, right, bottom = studio_photo._frame((400, 300), 250,
                                                   person, valid)
    assert bottom <= 1000, "the frame runs below the photo: a white gap"


def test_the_face_stays_centred_left_to_right():
    person, valid = _masks()
    left, top, right, bottom = studio_photo._frame((400, 300), 250,
                                                   person, valid)
    assert abs((left + right) / 2 - 400) <= 1


def test_the_frame_is_passport_shaped():
    person, valid = _masks()
    left, top, right, bottom = studio_photo._frame((400, 300), 250,
                                                   person, valid)
    assert (right - left) / (bottom - top) == pytest.approx(OUT_RATIO,
                                                            abs=0.01)


def test_a_whole_person_gets_room_above_the_head():
    """Not cut anywhere: ideal framing, the face FACE_HEIGHT of the frame."""
    person, valid = _masks(body_to_bottom=False, head_top=150)
    left, top, right, bottom = studio_photo._frame((400, 300), 250,
                                                   person, valid)
    assert (bottom - top) == pytest.approx(250 / studio_photo.FACE_HEIGHT,
                                           abs=2)
    assert top < 150, "no space above the head"


def test_a_head_cut_at_the_top_is_not_framed_into_white():
    person, valid = _masks(head_top=0)
    left, top, right, bottom = studio_photo._frame((400, 300), 250,
                                                   person, valid)
    assert top >= 0


def test_zoom_never_goes_past_the_limit():
    person, valid = _masks()
    left, top, right, bottom = studio_photo._frame((400, 300), 250,
                                                   person, valid)
    assert 250 / (bottom - top) <= studio_photo.MAX_FACE_HEIGHT + 0.01


# ---- the pipeline's safety ---------------------------------------------

@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "1A850344.png"
    shutil.copy(template_service.PLACEHOLDER_PHOTO, path)
    return str(path)


def test_no_face_means_the_photo_is_used_as_before(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (350, 450), "white").save(blank)
    assert studio_photo.make(str(blank)) is None


def test_the_placeholder_is_never_processed():
    assert studio_photo.make(template_service.PLACEHOLDER_PHOTO) is None


def test_made_once_and_the_original_is_untouched(photo, monkeypatch):
    calls = []

    def fake_build(path):
        calls.append(path)
        return Image.new("RGB", studio_photo.OUTPUT_SIZE, "white")

    monkeypatch.setattr(studio_photo, "_build", fake_build)
    before = hashlib.sha256(open(photo, "rb").read()).hexdigest()
    first = studio_photo.make(photo)
    second = studio_photo.make(photo)
    assert first == second and len(calls) == 1
    assert hashlib.sha256(open(photo, "rb").read()).hexdigest() == before


def test_any_failure_falls_back(photo, monkeypatch):
    def broken(path):
        raise RuntimeError("cut-out model missing")
    monkeypatch.setattr(studio_photo, "_build", broken)
    assert studio_photo.make(photo) is None


def test_documents_use_it(photo, monkeypatch, tmp_path):
    from app.models.csp_record import CSPRecord
    from app.models.enums import DocumentType
    from app.services import document_service

    used = []
    monkeypatch.setattr(studio_photo, "make",
                        lambda p: used.append(p) or None)
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path / "out"))
    csp = CSPRecord(csp_id="1A850344", csp_code="1A850344", name="P",
                    branch_name="B", branch_code="1", address="A",
                    mobile="9876543210", photo_url=photo)
    document_service.generate_documents(csp, [DocumentType.CSP_ID_CARD])
    assert used == [photo]
