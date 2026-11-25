"""No. 242: each LHO's signature and stamp, run against the real templates.

Every template carries the default signature (the Gurugram stamp). An LHO
with its own picture in the signatures folder (Patna) gets that picture on
its documents instead, in the same box, and the default is not left hidden
inside the file.
"""

import os

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.models.enums import DocumentType
from app.services import lho_signature, template_service
from tests.test_template_service import VALUES, _fill

ALL_TYPES = list(DocumentType)


def _blob(path):
    with open(path, "rb") as f:
        return f.read()


def _images(path):
    doc = Document(path)
    return [rel.target_part.blob
            for part in lho_signature._story_parts(doc)
            for rel in part.rels.values()
            if not rel.is_external and "image" in rel.reltype]


def _signature_extent(path, blob):
    """(cx, cy) of the drawing that shows `blob`."""
    doc = Document(path)
    for part in lho_signature._story_parts(doc):
        ids = {rid for rid, rel in part.rels.items()
               if not rel.is_external and "image" in rel.reltype
               and rel.target_part.blob == blob}
        for blip in part.element.iter(qn("a:blip")):
            if blip.get(qn("r:embed")) in ids:
                node = blip
                while node.tag not in (qn("wp:inline"), qn("wp:anchor")):
                    node = node.getparent()
                ext = node.find(qn("wp:extent"))
                return int(ext.get("cx")), int(ext.get("cy"))
    raise AssertionError("signature drawing not found")


def test_signature_files_are_in_place():
    assert os.path.isfile(lho_signature.default_path())
    assert lho_signature.own_signature_path("Patna")


@pytest.mark.parametrize("lho", ["Patna", "patna", " PATNA "])
def test_patna_is_found_whatever_the_spelling(lho):
    assert lho_signature.signature_for(lho).lower().endswith(("patna.png", "patna.jpg", "patna.jpeg"))


@pytest.mark.parametrize("lho", ["Lucknow", "Bhopal", "", None, "default"])
def test_other_lhos_use_the_default(lho):
    assert lho_signature.own_signature_path(lho) is None
    assert lho_signature.signature_for(lho) == lho_signature.default_path()


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_every_template_carries_the_default_signature(doc_type):
    path = template_service.template_path(doc_type)
    assert _images(path).count(_blob(lho_signature.default_path())) == 1


@pytest.mark.parametrize("doc_type", ALL_TYPES)
@pytest.mark.parametrize("lho", ["Lucknow", None])
def test_other_lhos_get_the_default_signature(doc_type, lho, tmp_path):
    out = str(tmp_path / "out.docx")
    _fill(doc_type, VALUES, out, lho=lho)
    images = _images(out)
    assert _blob(lho_signature.default_path()) in images
    assert _blob(lho_signature.own_signature_path("Patna")) not in images


@pytest.mark.parametrize("doc_type", ALL_TYPES)
def test_patna_gets_its_own_signature_in_the_same_box(doc_type, tmp_path):
    default, patna = (_blob(lho_signature.default_path()),
                      _blob(lho_signature.own_signature_path("Patna")))
    src = template_service.template_path(doc_type)
    out = str(tmp_path / "out.docx")
    _fill(doc_type, VALUES, out, lho="Patna")

    images = _images(out)
    assert patna in images
    assert default not in images  # not left hidden in the file
    # Same number of pictures as any other document from this template.
    extra = 1 if doc_type in template_service.PHOTO_MARKERS else 0
    assert template_service.count_images(out) == template_service.count_images(src) + extra

    # Fits the box the default occupies, touching it on one side.
    box_cx, box_cy = _signature_extent(src, default)
    cx, cy = _signature_extent(out, patna)
    assert cx <= box_cx and cy <= box_cy
    assert cx == box_cx or cy == box_cy


def test_a_template_without_the_default_signature_is_left_alone(tmp_path, caplog):
    """An uploaded template with a different signature is not touched, and
    the mismatch is logged as an error rather than passing silently."""
    doc = Document(template_service.template_path(DocumentType.BCP))
    default = _blob(lho_signature.default_path())
    for part in lho_signature._story_parts(doc):
        for rel in part.rels.values():
            if not rel.is_external and "image" in rel.reltype and rel.target_part.blob == default:
                rel.target_part._blob = b"\x89PNG-something-else"
    with caplog.at_level("ERROR"):
        assert lho_signature.apply(doc, "Patna") is None
    assert "could not be" in caplog.text
