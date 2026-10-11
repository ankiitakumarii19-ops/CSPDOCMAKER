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

OUT_RATIO = studio_photo.output_size()[0] / studio_photo.output_size()[1]


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
        return Image.new("RGB", studio_photo.output_size(), "white")

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



# ---- size and automation (tracker No. 72, 12 Oct 2026) -------------------

def test_the_size_comes_from_millimetres_and_dpi(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "passport_photo_width_mm", 35)
    monkeypatch.setattr(s, "passport_photo_height_mm", 45)
    monkeypatch.setattr(s, "passport_photo_dpi", 300)
    assert studio_photo.output_size() == (413, 531)
    monkeypatch.setattr(s, "passport_photo_dpi", 500)
    assert studio_photo.output_size() == (689, 886)


def test_changing_the_size_makes_a_fresh_photo(photo, monkeypatch):
    from app.config import get_settings
    first = studio_photo._cache_path(photo)
    monkeypatch.setattr(get_settings(), "passport_photo_dpi", 300)
    assert studio_photo._cache_path(photo) != first


def test_an_agent_without_a_photo_is_skipped():
    from app.models.csp_record import CSPRecord
    assert studio_photo.prepare_for(CSPRecord(csp_id="X", photo_url=None)) is None


def test_the_automation_edits_a_new_agents_photo(monkeypatch):
    """New KO / Sub-KO: the photo is edited when the automation picks it up."""
    import inspect
    from app.workers import new_csp_worker, pending_request_worker
    for module in (new_csp_worker, pending_request_worker):
        assert "studio_photo.prepare_for(csp)" in inspect.getsource(module)


# ---- studio tone (tracker No. 73, 12 Oct 2026) ---------------------------

def _disc(colour_inside, rim=None, size=200):
    """A 'person' disc with an optional coloured rim, and its matte."""
    import cv2
    rgb = np.full((size, size, 3), 255, np.uint8)
    alpha = np.zeros((size, size), np.uint8)
    cv2.circle(rgb, (100, 100), 70, colour_inside, -1)
    cv2.circle(alpha, (100, 100), 70, 255, -1)
    if rim:
        cv2.circle(rgb, (100, 100), 70, rim, 4)
    return rgb, alpha


def test_a_coloured_rim_from_the_wall_is_removed():
    import cv2
    rgb, alpha = _disc((150, 120, 100), rim=(120, 200, 60))   # green rim
    out = studio_photo._suppress_spill(rgb, alpha)
    lab_in = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[100, 168]
    lab_out = cv2.cvtColor(out, cv2.COLOR_RGB2LAB)[100, 168]
    inside = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[100, 100]
    assert abs(int(lab_out[1]) - int(inside[1])) < abs(int(lab_in[1]) - int(inside[1]))


def test_the_middle_of_the_person_is_not_touched_by_the_rim_fix():
    rgb, alpha = _disc((150, 120, 100), rim=(120, 200, 60))
    out = studio_photo._suppress_spill(rgb, alpha)
    assert (out[100, 100].astype(int) - rgb[100, 100].astype(int)).max() <= 2


def test_navy_and_red_keep_their_colour():
    for colour in ((30, 40, 90), (160, 20, 30)):            # navy, red
        rgb, alpha = _disc(colour)
        out = studio_photo._suppress_spill(rgb, alpha)
        assert np.abs(out[100, 100].astype(int) - np.array(colour)).max() <= 3


def test_a_dark_face_is_brightened_and_a_bright_one_never_darkened():
    import cv2
    for level, should_rise in ((90, True), (200, False)):
        rgb = np.full((300, 300, 3), level, np.uint8)
        out = studio_photo._studio_tone(rgb, (100, 100, 100, 100))
        before = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[150, 150, 0]
        after = cv2.cvtColor(out, cv2.COLOR_RGB2LAB)[150, 150, 0]
        if should_rise:
            assert after > before + 10
        else:
            assert after >= before - 2, "a bright face was darkened"


def test_studio_tone_keeps_size_and_is_repeatable():
    rng = np.random.default_rng(7)
    rgb = rng.integers(60, 200, (240, 200, 3), dtype=np.uint8)
    a = studio_photo._studio_tone(rgb, (50, 50, 100, 120))
    b = studio_photo._studio_tone(rgb, (50, 50, 100, 120))
    assert a.shape == rgb.shape and np.array_equal(a, b)


def test_a_style_change_remakes_saved_photos(photo):
    assert f".{studio_photo.STYLE_VERSION}." in studio_photo._cache_path(photo)
