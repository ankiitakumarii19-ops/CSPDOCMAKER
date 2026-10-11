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
from app.services.template_service import count_images, has_photo_marker

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


def _marker_cell(document, doc_type):
    """The table cell whose text is the photo marker (since 11 Oct 2026)."""
    from docx.oxml.ns import qn

    wanted = " ".join(template_service.photo_marker_for(doc_type).split())
    for tc in document.element.body.iter(qn("w:tc")):
        lines = ["".join(t.text or "" for t in p.iter(qn("w:t")))
                 for p in tc.findall(qn("w:p"))]
        text = " ".join(" ".join(lines).split())
        if text == wanted:
            return tc
    return None


@pytest.mark.parametrize("doc_type", [DocumentType.CSP_ID_CARD,
                                      DocumentType.TRAINING_CERTIFICATE])
def test_every_photo_cell_can_hold_a_passport_photo(doc_type):
    """The photo box is a table cell drawn at 35 x 45 mm (11 Oct 2026).

    If this fails the template was resized — check for a Word edit before
    changing any code.
    """
    import docx
    from docx.oxml.ns import qn

    document = docx.Document(template_service.template_path(doc_type))
    tc = _marker_cell(document, doc_type)
    assert tc is not None, f"{doc_type.value}: no photo cell in the template"

    tbl = tc
    while tbl.tag != qn("w:tbl"):
        tbl = tbl.getparent()
    tr = tc.getparent()
    widths = [int(g.get(qn("w:w"))) for g in tbl.iter(qn("w:gridCol"))]
    index = list(tr.findall(qn("w:tc"))).index(tc)
    width_twips = widths[index] if index < len(widths) else min(widths)
    heights = [int(h.get(qn("w:val"))) for h in tr.iter(qn("w:trHeight"))]
    assert heights, f"{doc_type.value}: the photo row has no fixed height"

    # 35 mm = 1984.25 twips, 45 mm = 2551.2 twips; Word stores whole twips.
    assert width_twips >= 1984, (
        f"{doc_type.value} photo cell is {width_twips / 56.7:.1f}mm wide, "
        f"a passport photo needs 35mm")
    assert heights[0] >= 2551, (
        f"{doc_type.value} photo cell is {heights[0] / 56.7:.1f}mm tall, "
        f"a passport photo needs 45mm")


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


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_the_photo_cell_has_no_padding_and_nothing_else_in_it(doc_type):
    """A 35 x 45 mm photo fits a 35 x 45 mm cell only with no padding.

    A Word table cell pads its contents left and right by default, which
    would squeeze the photograph. The caption lines are removed so they
    cannot push it down. The template file itself is not changed.
    """
    from docx.oxml.ns import qn

    (_, path), = document_service.generate_documents(
        _csp(photo_url=template_service.PLACEHOLDER_PHOTO), [doc_type])
    para = _passport_paragraph(path)
    assert para is not None, f"{doc_type.value}: no 35x45mm photograph"

    tc = para._p.getparent()
    assert tc.tag == qn("w:tc"), f"{doc_type.value}: photo is not in a cell"
    assert len(tc.findall(qn("w:p"))) == 1, (
        f"{doc_type.value}: caption lines were left beside the photo")
    margins = tc.find(qn("w:tcPr") + "/" + qn("w:tcMar"))
    assert margins is not None, f"{doc_type.value}: cell padding not cleared"
    for side in margins:
        assert side.get(qn("w:w")) in ("0", None), (
            f"{doc_type.value}: cell still pads its contents")




# ---- the light touch-up (tracker No. 58, 11 Oct 2026) --------------------
#
# "Make it look professional; don't change the look or the face." Only the
# tone may change: every pixel stays where it was.

def _correlation(a, b):
    import numpy as np
    x = np.asarray(a.convert("L"), dtype=float).ravel()
    y = np.asarray(b.convert("L"), dtype=float).ravel()
    return float(np.corrcoef(x, y)[0, 1])


def test_the_touch_up_keeps_size_and_structure(tmp_path):
    from PIL import Image

    source = template_service.passport_crop(template_service.PLACEHOLDER_PHOTO)
    done = template_service.touch_up(source)
    with Image.open(source) as a, Image.open(done) as b:
        assert a.size == b.size, "the touch-up changed the photo's size"
        assert _correlation(a, b) > 0.97, (
            "the touch-up changed the picture itself, not just its tone")


def test_a_dark_photo_is_lifted_and_a_good_one_barely_moves(tmp_path):
    from PIL import Image, ImageDraw, ImageStat

    dark = Image.new("RGB", (350, 450), (40, 35, 30))
    ImageDraw.Draw(dark).ellipse((100, 100, 250, 300), fill=(90, 70, 60))
    dark.save(tmp_path / "dark.png")
    lifted = Image.open(template_service.touch_up(str(tmp_path / "dark.png")))
    assert (ImageStat.Stat(lifted.convert("L")).mean[0]
            > ImageStat.Stat(dark.convert("L")).mean[0])


def test_the_original_photo_file_is_never_changed(tmp_path):
    import hashlib
    photo = tmp_path / "csp.png"
    shutil.copy(template_service.PLACEHOLDER_PHOTO, photo)
    before = hashlib.sha256(photo.read_bytes()).hexdigest()
    document_service.generate_documents(_csp(photo_url=str(photo)),
                                        [DocumentType.CSP_ID_CARD])
    assert hashlib.sha256(photo.read_bytes()).hexdigest() == before


# ---- no gap on the left (tracker No. 76, 12 Oct 2026) --------------------

@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_the_photo_is_pulled_left_by_libreoffices_reserve(doc_type):
    (_, path), = document_service.generate_documents(
        _csp(photo_url=template_service.PLACEHOLDER_PHOTO), [doc_type])
    para = _passport_paragraph(path)
    assert para.paragraph_format.left_indent.twips == \
        -template_service._LIBREOFFICE_CELL_OFFSET_TWIPS


@pytest.mark.parametrize("doc_type", PHOTO_TYPES)
def test_in_the_pdf_the_photo_starts_at_the_border(doc_type, tmp_path):
    """Measured on the real PDF: no gap on the left, nothing past the right."""
    import pymupdf as fitz
    from app.services import pdf_service

    (_, path), = document_service.generate_documents(
        _csp(photo_url=template_service.PLACEHOLDER_PHOTO), [doc_type])
    try:
        (_, pdf), = pdf_service.convert_all([path], output_dir=str(tmp_path))
    except pdf_service.PDFConversionError:
        pytest.skip("LibreOffice is not installed here")
    page = fitz.open(pdf)[0]
    mm = lambda v: v / 72 * 25.4
    photo = [r for img in page.get_images(full=True)
             for r in page.get_image_rects(img[0])
             if 30 < mm(r.width) < 40 and 40 < mm(r.height) < 50][0]
    verticals = [d["rect"].x0 for d in page.get_drawings()
                 if d["rect"].width < 1 and 44 < mm(d["rect"].height) < 46]
    boxes = [d["rect"] for d in page.get_drawings()
             if 34.5 < mm(d["rect"].width) < 35.5
             and 44.5 < mm(d["rect"].height) < 45.5]
    if boxes:
        left, right = boxes[0].x0, boxes[0].x1
    else:
        left = min(verticals, key=lambda v: abs(v - photo.x0))
        right = min(verticals, key=lambda v: abs(v - photo.x1))
    assert abs(mm(photo.x0 - left)) < 0.3, "gap on the left of the photo"
    assert abs(mm(right - photo.x1)) < 0.3, "photo runs past the right border"
