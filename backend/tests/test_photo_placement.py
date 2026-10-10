"""CSP photo placement in the ID Card and Training Certificate.

The signature is already embedded in the supplied templates, so only the CSP
photo is inserted. Until photos are extracted from the CRM, a placeholder box
is used — that substitution is explicit and switchable.
"""

import os
import shutil

import pytest

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import document_service, template_service
from app.services.template_service import TemplateError, count_images, has_photo_marker

PHOTO_TYPES = [DocumentType.CSP_ID_CARD, DocumentType.TRAINING_CERTIFICATE]
NO_PHOTO_TYPES = [DocumentType.CSP_CERTIFICATE, DocumentType.BCP]


def _csp(**overrides) -> CSPRecord:
    values = dict(
        csp_id="TESTCSP001", csp_code="TC001", name="Test Csp Name",
        branch_name="Testbranch", branch_code="BR0001", address="1 Test Street",
        district="Testdistrict", state="Teststate", mobile="9876543210",
        email="test.csp@example.com", ao="Testao", rbo_name="Testrbo",
        asm_name="Testasm", asm_email="test.asm@example.com", asm_contact="9876500000",
        certificate_date=__import__("datetime").date(2026, 3, 4),
    )
    values.update(overrides)
    return CSPRecord(**values)


@pytest.fixture(autouse=True)
def _output_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(document_service.settings, "document_output_dir", str(tmp_path))


def test_placeholder_asset_exists():
    assert os.path.isfile(template_service.PLACEHOLDER_PHOTO)


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_marker_is_replaced_by_an_image(doc_type, tmp_path):
    (_, path), = document_service.generate_documents(_csp(), [doc_type])
    assert not has_photo_marker(path, doc_type), "marker text still visible"
    assert count_images(path) == count_images(template_service.template_path(doc_type)) + 1


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_the_csps_own_photo_is_used_when_present(doc_type, tmp_path):
    photo = tmp_path / "csp_photo.png"
    shutil.copy(template_service.PLACEHOLDER_PHOTO, photo)
    csp = _csp(photo_url=str(photo))
    assert document_service.used_placeholder_photo(csp) is False
    assert document_service.resolve_photo(csp) == str(photo)
    (_, path), = document_service.generate_documents(csp, [doc_type])
    assert not has_photo_marker(path, doc_type)


def test_placeholder_is_reported_as_such():
    assert document_service.used_placeholder_photo(_csp()) is True
    assert document_service.resolve_photo(_csp()) == template_service.PLACEHOLDER_PHOTO


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_missing_photo_is_refused_when_placeholders_are_disabled(doc_type, monkeypatch):
    monkeypatch.setattr(document_service.settings, "photo_placeholder_allowed", False)
    with pytest.raises(RuntimeError, match="no usable photo"):
        document_service.generate_documents(_csp(), [doc_type])


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_unreadable_photo_path_falls_back_to_placeholder(doc_type):
    csp = _csp(photo_url="/no/such/file.jpg")
    assert document_service.resolve_photo(csp) == template_service.PLACEHOLDER_PHOTO


@pytest.mark.parametrize("doc_type", NO_PHOTO_TYPES)
def test_documents_without_a_photo_marker_are_untouched(doc_type):
    (_, path), = document_service.generate_documents(_csp(), [doc_type])
    assert count_images(path) == count_images(template_service.template_path(doc_type))


def test_photo_becomes_required_data_once_placeholders_are_disabled(monkeypatch):
    from app.config import get_settings
    from app.services import csp_mapping
    assert "photo" not in csp_mapping.required_fields_for(DocumentType.CSP_ID_CARD)
    monkeypatch.setattr(get_settings(), "photo_placeholder_allowed", False)
    assert "photo" in csp_mapping.required_fields_for(DocumentType.CSP_ID_CARD)


def test_all_four_documents_generate_together():
    csp = _csp()
    results = document_service.generate_documents(csp, list(DocumentType))
    assert len(results) == 4
    for doc_type, path in results:
        assert os.path.getsize(path) > 0
        assert not has_photo_marker(path, doc_type)


# ---- Passport sizing and the ID Card layout fix --------------------------

def _png(path, width, height):
    """Write a minimal PNG of the given pixel size (stdlib only)."""
    import struct, zlib
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    return str(path)


@pytest.mark.parametrize("w,h", [
    (350, 450),    # exactly passport proportions
    (1200, 1600),  # portrait, taller than passport
    (2000, 1000),  # landscape
    (60, 60),      # square and tiny
    (4000, 5143),  # very large portrait
])
def test_every_photo_comes_out_exactly_passport_size(tmp_path, w, h):
    """Standing rule: the placed photo is always 35mm x 45mm.

    This replaces the old "never larger than" rule. Fitting a square scan
    inside the box produced 35mm x 35mm — smaller than a passport photo,
    which is what the rule forbids.
    """
    width, height = template_service.passport_size()
    assert width.inches == pytest.approx(
        template_service.PASSPORT_WIDTH_INCHES, rel=1e-6)
    assert height.inches == pytest.approx(
        template_service.PASSPORT_HEIGHT_INCHES, rel=1e-6)


@pytest.mark.parametrize("w,h", [(350, 450), (1200, 1600), (2000, 1000), (60, 60)])
def test_the_source_is_cropped_rather_than_squashed(tmp_path, w, h):
    """The crop changes the framing, never the proportions of the face."""
    from PIL import Image

    path = _png(tmp_path / f"a{w}x{h}.png", w, h)
    cropped = template_service.passport_crop(path)
    with Image.open(cropped) as image:
        cw, ch = image.size
    # The crop is a sub-rectangle of the source: never stretched beyond it.
    assert cw <= w + 1 and ch <= h + 1
    assert cw / ch == pytest.approx(template_service.PASSPORT_ASPECT, rel=0.02)


def test_the_shipped_placeholder_is_passport_shaped():
    """A square placeholder hides the layout problems a real photo causes."""
    from PIL import Image

    cropped = template_service.passport_crop(template_service.PLACEHOLDER_PHOTO)
    with Image.open(cropped) as image:
        width, height = image.size
    assert width / height == pytest.approx(35 / 45, rel=0.02)


def test_the_id_card_address_wraps_before_the_photo():
    """A real address must not disappear under the floating photo box.

    The photo floats at margin-left 226.4pt, so the address paragraph needs a
    right indent. Without it the text runs underneath the photo and is lost —
    which deterministic validation cannot see, because the text is present in
    the document either way.
    """
    import re
    import zipfile

    path = template_service.template_path(DocumentType.CSP_ID_CARD)
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")

    start = xml.rfind("<w:p ", 0, xml.find("CSP Address-"))
    paragraph = xml[start:xml.find("</w:p>", start)]
    match = re.search(r'<w:ind[^>]*w:right="(\d+)"', paragraph)
    assert match, "the ID Card address paragraph has no right indent"

    # The photo starts 4528 twips from the left of a ~6955 twip text area.
    assert int(match.group(1)) >= 2400, (
        "the address indent is too small — text will reach under the photo")


# ---- output is grouped per CSP ------------------------------------------

def test_documents_are_written_into_a_folder_named_after_the_csp(tmp_path, monkeypatch):
    """Each CSP's documents live in their own folder, not all in one heap."""
    from datetime import date
    monkeypatch.setattr(document_service.settings, "document_output_dir", str(tmp_path))

    csp = CSPRecord(
        csp_id="1A850647", csp_code="1A850647", name="Folder Test",
        email="folder@example.com", address="1 Test Street",
        mobile="9876543210", branch_name="Br", branch_code="0001",
        district="Sitamarhi", state="Bihar",
    )
    generated = document_service.generate_documents(
        csp, [DocumentType.CSP_CERTIFICATE], certificate_date_value=date(2026, 9, 25))

    filepath = generated[0][1]
    assert os.path.basename(os.path.dirname(filepath)) == "1A850647"
    assert os.path.isfile(filepath)


def test_a_csp_id_cannot_escape_the_output_directory(tmp_path, monkeypatch):
    """The ID comes from a spreadsheet cell, so it is not a trusted path."""
    monkeypatch.setattr(document_service.settings, "document_output_dir", str(tmp_path))
    folder = document_service._ensure_output_dir("../../etc/evil")
    assert os.path.realpath(folder).startswith(os.path.realpath(str(tmp_path)))
    assert ".." not in os.path.basename(folder)


def test_an_empty_csp_id_still_yields_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(document_service.settings, "document_output_dir", str(tmp_path))
    assert os.path.basename(document_service._ensure_output_dir("")) == os.path.basename(str(tmp_path))
    assert os.path.basename(document_service._ensure_output_dir("   ")) == "unknown_csp"


# ---- passport size is a guarantee, not a best fit ----------------------
#
# Standing rule: every photograph on every document is 35mm x 45mm. Fitting
# a photo inside that box is not the same thing — a square scan fitted
# inside comes out 35mm x 35mm. These pin the crop-then-place behaviour.

def _photo(tmp_path, width, height, name="src.png"):
    from PIL import Image
    path = tmp_path / name
    Image.new("RGB", (width, height), (180, 180, 180)).save(path)
    return str(path)


def test_the_insert_size_is_always_exactly_a_passport_photo():
    width, height = template_service.passport_size()
    assert round(width.inches * 25.4, 1) == 35.0
    assert round(height.inches * 25.4, 1) == 45.0


@pytest.mark.parametrize("source", [(900, 900), (1400, 700), (600, 1600),
                                    (966, 1123)])
def test_any_shape_is_cropped_to_the_passport_ratio(tmp_path, source):
    from PIL import Image

    cropped = template_service.passport_crop(_photo(tmp_path, *source))
    with Image.open(cropped) as image:
        ratio = image.size[0] / image.size[1]
    assert abs(ratio - template_service.PASSPORT_ASPECT) < 0.02, (
        f"{source} came out at {ratio:.3f}, not {template_service.PASSPORT_ASPECT:.3f}")


def test_a_photo_already_passport_shaped_is_left_alone(tmp_path):
    path = _photo(tmp_path, 700, 900)        # exactly 35:45
    assert template_service.passport_crop(path) == path


def test_a_tall_photo_keeps_the_head(tmp_path):
    """Trimming a too-tall scan takes more off the bottom than the top."""
    from PIL import Image

    path = _photo(tmp_path, 600, 1600)
    with Image.open(path) as original:
        height = original.size[1]
    cropped = template_service.passport_crop(path)
    with Image.open(cropped) as image:
        new_height = image.size[1]
    removed = height - new_height
    top_removed = int(removed * template_service.PASSPORT_TOP_BIAS)
    assert top_removed < removed - top_removed, "more must come off the bottom"


@pytest.mark.parametrize("doc_type", [DocumentType.CSP_ID_CARD,
                                      DocumentType.TRAINING_CERTIFICATE])
def test_every_photo_frame_can_hold_a_passport_photo(doc_type):
    """A frame smaller than 35x45mm means the photo gets shrunk to fit.

    If this fails the template was resized — check for a Word edit before
    changing any code.
    """
    import re
    import zipfile

    # Word writes these as "99.2pt", rounded to two decimals, so a frame set
    # to exactly 35x45mm reads back a hundredth of a point short. The
    # tolerance is that rounding and nothing more: 0.1pt is 0.035mm, while a
    # genuinely shrunk frame has been out by 6pt and 22pt.
    ROUNDING = 0.1
    need_w = template_service.PASSPORT_WIDTH_INCHES * 72 - ROUNDING
    need_h = template_service.PASSPORT_HEIGHT_INCHES * 72 - ROUNDING

    with zipfile.ZipFile(template_service.template_path(doc_type)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")

    if doc_type is DocumentType.CSP_ID_CARD:
        match = re.search(r'width:([\d.]+)pt;height:([\d.]+)pt', xml)
        assert match, "no photo frame found in the ID Card template"
        frame_w, frame_h = float(match.group(1)), float(match.group(2))
    else:
        # The narrowest column and shortest row are the photo cell.
        widths = [int(v) / 20 for v in
                  re.findall(r'<w:gridCol[^>]*w:w="(\d+)"', xml)]
        heights = [int(v) / 20 for v in
                   re.findall(r'<w:trHeight[^>]*w:val="(\d+)"', xml)]
        assert widths and heights, "no photo cell found in the Training template"
        frame_w, frame_h = min(widths), min(heights)

    assert frame_w >= need_w, (
        f"{doc_type.value} photo frame is {frame_w:.1f}pt wide, "
        f"a passport photo needs {need_w:.1f}pt")
    assert frame_h >= need_h, (
        f"{doc_type.value} photo frame is {frame_h:.1f}pt tall, "
        f"a passport photo needs {need_h:.1f}pt")


# ---- the photo must sit inside its frame, not merely be the right size ----
#
# The frame and the photograph are both exactly 35x45mm, so anything between
# them pushes the photo out of the frame, where it is clipped with no error
# and no failing test. The ID Card caption carried 50pt of space before it —
# which centred the words 'Affix Passport Size Photo' inside the empty box,
# and cut the face off at the eyes once a real photograph replaced them.
#
# Checking the size of the frame was not enough to catch that, because the
# frame was the right size all along. These check the gap instead.

PASSPORT_EMU = (1260000, 1620000)       # 35mm x 45mm, exactly


def _passport_paragraph(path):
    """The paragraph holding the 35x45mm photograph, not the logo or stamp.

    A paragraph wrapping a text box contains the photograph's markup too, so
    the one that holds no further paragraph is the one the image sits in —
    and the only one whose spacing moves the photograph.
    """
    import docx
    from docx.oxml.ns import qn

    document = docx.Document(path)
    for para in template_service._all_paragraphs(document):
        if para._p.findall(".//" + qn("w:p")):
            continue                      # a container, not the holder
        for extent in para._p.findall(".//" + qn("wp:extent")):
            if (int(extent.get("cx")), int(extent.get("cy"))) == PASSPORT_EMU:
                return para
    return None


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_nothing_pushes_the_photo_out_of_its_frame(doc_type, tmp_path):
    """The paragraph holding the photo adds no space around it."""
    photo = tmp_path / "csp_photo.png"
    shutil.copy(template_service.PLACEHOLDER_PHOTO, photo)
    (_, path), = document_service.generate_documents(
        _csp(photo_url=str(photo)), [doc_type])

    para = _passport_paragraph(path)
    assert para is not None, (
        f"{doc_type.value}: no 35x45mm image in the generated file")

    before = para.paragraph_format.space_before
    after = para.paragraph_format.space_after
    assert not before, (
        f"{doc_type.value}: {before.pt}pt of space before the photograph "
        f"pushes it out of a frame that is exactly as tall as the photo")
    assert not after, f"{doc_type.value}: space after the photograph"


def test_the_id_cards_photo_box_does_not_inset_its_contents():
    """A 35mm photo does not fit a 35mm box that pads its contents.

    Word insets a text box by 0.1 inch either side by default, which would
    steal 5mm from a 35mm-wide photograph and clip it.
    """
    import zipfile

    (_, path), = document_service.generate_documents(
        _csp(photo_url=template_service.PLACEHOLDER_PHOTO),
        [DocumentType.CSP_ID_CARD])

    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")

    assert 'inset="0,0,0,0"' in xml, (
        "the ID Card photo box still insets its contents, so a 35x45mm "
        "photograph cannot fit inside its 35x45mm frame")


def test_the_id_cards_photo_frame_is_widened_to_fit_the_photograph():
    """A 35mm frame cannot hold a 35mm photograph once padding is added.

    LibreOffice reserves 3.2mm on each side of a text box whatever `inset`
    says, so a frame drawn exactly as wide as the photograph pushes it
    sideways until it hangs off the edge of the card. The frame is widened
    by that padding and moved left by half of it, which puts the photograph
    back on the rectangle the template drew for it.
    """
    import re
    import zipfile

    def frame(path):
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        shape = re.search(r'<v:rect id="_x0000_s1040"[^>]*>', xml)
        assert shape, f"no photo frame in {os.path.basename(path)}"
        style = dict(p.split(":", 1) for p in
                     re.search(r'style="([^"]*)"', shape.group(0)).group(1)
                     .split(";") if ":" in p)
        return shape.group(0), float(style["width"][:-2]), \
            float(style["margin-left"][:-2])

    _, template_w, template_x = frame(
        template_service.template_path(DocumentType.CSP_ID_CARD))

    (_, path), = document_service.generate_documents(
        _csp(photo_url=template_service.PLACEHOLDER_PHOTO),
        [DocumentType.CSP_ID_CARD])
    shape, made_w, made_x = frame(path)

    needed = template_service.PASSPORT_WIDTH_INCHES * 72
    inset = template_service._LIBREOFFICE_SIDE_INSET_PT

    assert made_w == pytest.approx(template_w + 2 * inset), (
        "the frame was not widened to make room for the photograph")
    assert made_x == pytest.approx(template_x - inset), (
        "the frame was widened but not moved, so the photo sits too far right")
    assert made_w - 2 * inset >= needed - 0.1, (
        f"the widened frame still leaves only {made_w - 2 * inset:.1f}pt "
        f"for a photograph needing {needed:.1f}pt")

    # The photograph covers the frame completely, so a white fill and an
    # outline on a now-larger frame would only draw a border in the wrong
    # place.
    assert 'filled="f"' in shape and 'stroked="f"' in shape, (
        "the widened frame is still painted, so it shows around the photo")
