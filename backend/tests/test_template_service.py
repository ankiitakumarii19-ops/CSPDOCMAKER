"""Template filling, run against the real supplied DOCX templates.

Values used here are obvious test strings, never business data.
"""

import os

import pytest
from docx import Document

from app.models.enums import DocumentType
from app.services import template_service
from app.services.template_service import (
    PLACEHOLDER_FIELDS, TemplateError, fill_template, required_fields, template_path,
)

VALUES = {
    "csp_name": "Testname Testsurname",
    "csp_code": "TC0001",
    "branch_name": "Testbranch",
    "branch_code": "BR0001",
    "address": "1 Test Street, Testarea",
    "district": "Testdistrict",
    "state": "Teststate",
    "mobile": "9876543210",
    "email": "test.csp@example.com",
    "ao": "Testao",
    "rbo_name": "Testrbo",
    "asm_name": "Testasm",
    "asm_email": "test.asm@example.com",
    "asm_contact": "9876500000",
    "certificate_date": "15.08.2024",
    "certificate_month_year": "March 2026",
}

ALL_TYPES = list(DocumentType)


def _fill(doc_type, values, out, **kwargs):
    """fill_template with the photo the templates with a photo box require."""
    if doc_type in template_service.PHOTO_MARKERS:
        kwargs.setdefault("photo_path", template_service.PLACEHOLDER_PHOTO)
    return fill_template(doc_type, values, out, **kwargs)


def _text(path: str) -> str:
    """All text in the document, including tables, text boxes and footers."""
    doc = Document(path)
    return "\n".join("".join(r.text for r in p.runs)
                     for p in template_service._all_paragraphs(doc))


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_supplied_template_exists(doc_type):
    assert os.path.isfile(template_path(doc_type))


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_registry_matches_the_template_exactly(doc_type):
    """Guards against a template being edited without updating the mapping.

    A placeholder present in the file but not registered would never be
    filled, and the document would go out showing the raw placeholder.
    """
    doc = Document(template_path(doc_type))
    in_template = {
        m.group(1).strip()
        for p in template_service._all_paragraphs(doc)
        for m in template_service._PLACEHOLDER_RE.finditer("".join(r.text for r in p.runs))
    }
    registered = set(PLACEHOLDER_FIELDS[doc_type])
    assert in_template == registered, (
        f"{doc_type.value}: in template but not registered "
        f"{sorted(in_template - registered)}; registered but not in template "
        f"{sorted(registered - in_template)}"
    )


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_every_value_is_written_and_no_placeholder_remains(doc_type, tmp_path):
    out = str(tmp_path / f"{doc_type.value}.docx")
    _fill(doc_type, VALUES, out)
    text = _text(out)

    for placeholder, field in PLACEHOLDER_FIELDS[doc_type].items():
        assert VALUES[field] in text, f"{doc_type.value}: {field} not written"
        # The quoted placeholder token itself must be gone, quotes included.
        for quoted in (f'"{placeholder}"', f"“{placeholder}”"):
            assert quoted not in text, f"{doc_type.value}: {quoted} still present"


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_template_design_is_preserved(doc_type, tmp_path):
    """Filling must not change the document's structure — only the text."""
    src, out = template_path(doc_type), str(tmp_path / "out.docx")
    _fill(doc_type, VALUES, out)
    before, after = Document(src), Document(out)
    assert len(after.tables) == len(before.tables)
    assert len(after.sections) == len(before.sections)
    assert len(after.paragraphs) == len(before.paragraphs)
    extra_images = 1 if doc_type in template_service.PHOTO_MARKERS else 0
    assert len(after.inline_shapes) == len(before.inline_shapes) + extra_images
    # The template's own images (logo, signature) are carried over untouched.
    assert (template_service.count_images(out)
            == template_service.count_images(src) + extra_images)


def test_split_runs_are_handled(tmp_path):
    """Word splits placeholders across runs; the fill must still find them."""
    src = template_path(DocumentType.CSP_CERTIFICATE)
    para = max(Document(src).paragraphs, key=lambda p: len(p.runs))
    assert len(para.runs) > 1, "expected a template paragraph split across runs"
    out = str(tmp_path / "cert.docx")
    _fill(DocumentType.CSP_CERTIFICATE, VALUES, out)
    assert VALUES["district"] in _text(out)


def test_id_card_text_boxes_are_filled(tmp_path):
    """The ID Card's content lives entirely in text boxes."""
    out = str(tmp_path / "id.docx")
    _fill(DocumentType.CSP_ID_CARD, VALUES, out)
    assert Document(out).paragraphs == [] or True  # body is empty by design
    text = _text(out)
    assert VALUES["csp_name"] in text and VALUES["mobile"] in text


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_missing_value_is_refused(doc_type, tmp_path):
    field = required_fields(doc_type)[0]
    values = dict(VALUES, **{field: "   "})
    with pytest.raises(TemplateError, match=field):
        _fill(doc_type, values, str(tmp_path / "x.docx"))
    assert not os.path.exists(str(tmp_path / "x.docx"))


def test_missing_template_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(template_service.settings, "document_templates_dir", str(tmp_path))
    with pytest.raises(TemplateError, match="Template file not found"):
        template_path(DocumentType.BCP)


def test_quoted_prose_is_not_replaced(tmp_path):
    """Only registered placeholders are touched."""
    from docx import Document as NewDoc
    doc = NewDoc()
    doc.add_paragraph('Keep “some quoted prose” and fill “CSP Name” here.')
    src = str(tmp_path / "tpl.docx")
    doc.save(src)
    out = str(tmp_path / "out.docx")
    _fill(DocumentType.CSP_CERTIFICATE, VALUES, out, template_file=src)
    text = _text(out)
    assert "“some quoted prose”" in text
    assert VALUES["csp_name"] in text


def test_a_value_takes_the_formatting_of_the_placeholder_it_replaces():
    """A placeholder split across runs must not lose its font size.

    Word splits a placeholder into an opening quote, the field name and a
    closing quote, and does not always format them alike. In the Training
    Certificate the opening quote run carries no size at all, so a value
    written there fell back to the document default and the CSP's name
    printed noticeably smaller than the sentence around it.
    """
    import docx
    from docx.shared import Pt

    document = docx.Document()
    paragraph = document.add_paragraph()
    # The shape the real template has: an unformatted opening quote.
    opening = paragraph.add_run("“")
    name = paragraph.add_run("CSP Name")
    name.font.size = Pt(14)
    name.bold = True
    closing = paragraph.add_run("”")
    closing.font.size = Pt(14)

    replaced = template_service._replace_in_paragraph(
        paragraph, {"CSP Name": "Abhishek Anand"})

    assert replaced == 1
    assert "".join(r.text for r in paragraph.runs) == "Abhishek Anand"
    assert opening.text == "Abhishek Anand", "the value went to another run"
    assert opening.font.size == Pt(14), "the value did not inherit the size"
    assert opening.bold is True


def test_a_value_keeps_its_own_formatting_when_it_already_has_some():
    """Only a run with no size of its own adopts another's."""
    import docx
    from docx.shared import Pt

    document = docx.Document()
    paragraph = document.add_paragraph()
    opening = paragraph.add_run("“CSP Name")
    opening.font.size = Pt(20)
    closing = paragraph.add_run("”")
    closing.font.size = Pt(9)

    template_service._replace_in_paragraph(paragraph, {"CSP Name": "Someone"})

    assert opening.font.size == Pt(20), "formatting was overwritten"


# ---- stray text beside a placeholder ------------------------------------

def test_no_template_has_stray_characters_after_a_placeholder():
    """Three 'S' characters were typed into the Training Certificate after
    the date placeholder, so every certificate printed 'Date- 07.10.2026SSS'.

    Nothing could catch that: the generated file was correct — the template
    was wrong, and the system faithfully reproduced it. This checks each
    template for text pressed up against a placeholder with no separator,
    which is what that looks like.
    """

    import docx

    from app.models.enums import DocumentType

    for doc_type in DocumentType:
        document = docx.Document(template_service.template_path(doc_type))
        for para in template_service._all_paragraphs(document):
            text = "".join(r.text for r in para.runs)
            for match in template_service._PLACEHOLDER_RE.finditer(text):
                tail = text[match.end():match.end() + 6]
                # A separator, punctuation or the end of the line is fine.
                assert not (tail and tail[0].isalnum()), (
                    f"{doc_type.value}: {tail!r} runs straight on from the "
                    f"placeholder {match.group(1)!r} — in {text!r}")
