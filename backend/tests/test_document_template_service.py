# -*- coding: utf-8 -*-
"""Uploading, mapping and editing a document template.

The risk an admin-editable template carries is that editing the wording
quietly breaks the document: the ID Card's content lives in text boxes, its
photograph sits in a VML frame sized to 35x45mm, and a signature image is
embedded in all four. Rebuilding a .docx from HTML would lose every one of
those, which is why the wording is edited run by run, in place.

The other risk is a placeholder that maps to nothing — it would print a blank
where a name belongs on an official document.
"""

import re
import zipfile

import pytest

from app.models.enums import DocumentType
from app.services import document_template_service as d
from app.services import template_service as ts

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _bytes(doc_type) -> bytes:
    with open(ts.template_path(doc_type), "rb") as handle:
        return handle.read()


# ---- the supplied templates map themselves ------------------------------

@pytest.mark.parametrize("doc_type", list(DocumentType))
async def test_every_supplied_template_maps_completely(doc_type):
    """If these need hand-mapping, the vocabulary is wrong."""
    info = d.inspect(_bytes(doc_type))
    assert info["unmapped"] == [], (
        f"{doc_type.value}: {info['unmapped']} would have to be mapped by hand")
    assert len(info["mapped"]) == len(info["placeholders"])


@pytest.mark.parametrize("doc_type", list(DocumentType))
async def test_the_guessed_mapping_matches_the_registry(doc_type):
    """Auto-mapping must agree with what the system already does."""
    info = d.inspect(_bytes(doc_type))
    registered = ts.PLACEHOLDER_FIELDS[doc_type]
    for text, field in info["mapped"].items():
        assert registered.get(text) == field, (
            f"{text!r} would be filled with {field}, not {registered.get(text)}")


# ---- a name nobody knows is asked about, never guessed ------------------

async def test_an_unknown_placeholder_is_reported_not_guessed():
    mapped, unmapped = d.auto_map(["CSP Name", "Officer Designation"])
    assert mapped == {"CSP Name": "csp_name"}
    assert unmapped == ["Officer Designation"]


async def test_matching_ignores_case_spacing_and_punctuation():
    mapped, _ = d.auto_map(["  csp   name  ", "CSP-CODE", "Branch Name"])
    assert mapped["  csp   name  "] == "csp_name"
    assert mapped["CSP-CODE"] == "csp_code"


async def test_a_near_miss_is_not_taken():
    """Printing the wrong field is worse than asking one question."""
    _, unmapped = d.auto_map(["CSP Name of Nominee", "Branch Manager Name"])
    assert len(unmapped) == 2


# ---- what may be uploaded ----------------------------------------------

async def test_an_empty_file_is_refused():
    with pytest.raises(d.TemplateUploadError, match="empty"):
        d.validate_upload(b"")


async def test_something_that_is_not_a_docx_is_refused():
    with pytest.raises(d.TemplateUploadError, match="not a .docx"):
        d.validate_upload(b"%PDF-1.4 this is a pdf")


async def test_an_old_doc_file_is_refused_with_an_explanation():
    """A .doc is an entirely different format, not a .docx."""
    with pytest.raises(d.TemplateUploadError, match="older"):
        d.validate_upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 old word")


async def test_an_oversized_file_is_refused():
    big = b"PK\x03\x04" + b"\0" * (d.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(d.TemplateUploadError, match="under"):
        d.validate_upload(big)


async def test_a_corrupt_docx_is_refused():
    with pytest.raises(d.TemplateUploadError, match="could not be opened"):
        d.validate_upload(b"PK\x03\x04" + b"not really a zip")


async def test_a_real_template_passes():
    d.validate_upload(_bytes(DocumentType.BCP))


# ---- editing the wording must not break the document --------------------

async def _edit_first_text_paragraph(doc_type, transform):
    original = _bytes(doc_type)
    paragraphs = d.read_paragraphs(original)
    target = next(p for p in paragraphs if not p["has_placeholder"]
                  and len(p["text"]) > 5)
    return original, d.apply_paragraph_edits(
        original, {target["index"]: transform(target["text"])}), target


async def test_editing_the_wording_keeps_the_passport_photo_frame():
    """The frame is what makes the photograph 35x45mm. Losing it is silent."""
    original, edited, _ = await _edit_first_text_paragraph(
        DocumentType.CSP_ID_CARD, lambda t: t + " LIMITED")

    def frames(data):
        # Since 11 Oct 2026 the frame is a 35 x 45 mm table cell: its column
        # width and its exact row height.
        xml = zipfile.ZipFile(__import__("io").BytesIO(data)).read(
            "word/document.xml").decode("utf-8")
        return (re.findall(r'<w:gridCol w:w="(\d+)"', xml),
                re.findall(r'<w:trHeight[^>]*>', xml))

    assert frames(edited) == frames(original)
    assert "2551" in "".join(frames(edited)[1]), (
        "the ID Card has no 45 mm photo row at all")


async def test_editing_the_wording_keeps_every_image():
    """The signature is embedded in all four templates."""
    original, edited, _ = await _edit_first_text_paragraph(
        DocumentType.CSP_ID_CARD, lambda t: t + " X")

    def images(data):
        names = zipfile.ZipFile(__import__("io").BytesIO(data)).namelist()
        return sorted(n for n in names if n.startswith("word/media/")
                      and not n.endswith("/"))

    assert images(edited) == images(original)
    assert images(edited), "the ID Card has no embedded images"


async def test_the_edited_wording_is_actually_there():
    _, edited, target = await _edit_first_text_paragraph(
        DocumentType.TRAINING_CERTIFICATE, lambda t: t + " CONFIRMED")
    texts = [p["text"] for p in d.read_paragraphs(edited)]
    assert any("CONFIRMED" in t for t in texts)


async def test_the_document_still_opens_and_fills_after_an_edit(tmp_path):
    """The real proof: an edited template still produces a document."""
    original = _bytes(DocumentType.TRAINING_CERTIFICATE)
    paragraphs = d.read_paragraphs(original)
    target = next(p for p in paragraphs if not p["has_placeholder"]
                  and len(p["text"]) > 10)
    edited = d.apply_paragraph_edits(
        original, {target["index"]: target["text"] + " (revised)"})

    path = tmp_path / "edited.docx"
    path.write_bytes(edited)
    out = tmp_path / "filled.docx"
    ts.fill_template(
        DocumentType.TRAINING_CERTIFICATE,
        {"csp_name": "Abhishek Anand", "csp_code": "1A850466",
         "branch_name": "Dhabauli", "branch_code": "8567",
         "certificate_date": "02.10.2026", "gender": "Male"},
        str(out), template_file=str(path),
        photo_path="app/assets/placeholder_photo.png",
    )
    assert out.exists() and out.stat().st_size > 0


# ---- an edit may not delete a value from the document -------------------

async def test_an_edit_that_drops_a_placeholder_is_refused():
    """Otherwise a field silently stops printing on every future document."""
    original = _bytes(DocumentType.TRAINING_CERTIFICATE)
    target = next(p for p in d.read_paragraphs(original) if p["has_placeholder"])
    with pytest.raises(d.TemplateUploadError, match="removes"):
        d.apply_paragraph_edits(original, {target["index"]: "nothing here"})


async def test_an_edit_keeping_the_placeholder_is_allowed():
    original = _bytes(DocumentType.TRAINING_CERTIFICATE)
    target = next(p for p in d.read_paragraphs(original) if p["has_placeholder"])
    edited = d.apply_paragraph_edits(
        original, {target["index"]: "Revised: " + target["text"]})
    assert any("Revised:" in p["text"] for p in d.read_paragraphs(edited))


async def test_editing_a_paragraph_that_does_not_exist_is_refused():
    with pytest.raises(d.TemplateUploadError, match="no paragraph"):
        d.apply_paragraph_edits(_bytes(DocumentType.BCP), {99999: "x"})


# ---- where the photograph goes ------------------------------------------

@pytest.mark.parametrize("doc_type", list(ts.PHOTO_MARKERS))
async def test_the_photo_marker_is_found_in_templates_that_have_one(doc_type):
    assert d.guess_photo_marker(_bytes(doc_type)) == ts.PHOTO_MARKERS[doc_type]


@pytest.mark.parametrize("doc_type", [DocumentType.CSP_CERTIFICATE,
                                      DocumentType.BCP])
async def test_no_marker_is_invented_for_a_document_without_a_photo(doc_type):
    """A wrong marker replaces a real paragraph with someone's face."""
    assert d.guess_photo_marker(_bytes(doc_type)) is None
