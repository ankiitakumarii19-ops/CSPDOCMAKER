"""A full-page scan is only a photo when a face fills it (tracker No. 191).

Found on a live Zoho Lead: a police character certificate, scanned as one
image covering the page, was taken whole as the CSP's photograph. Real faces
are personal data and not kept with the code, so the face check is stood in
for where a face is needed.
"""

import io

import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.services import photo_extraction


def _full_page_scan_pdf(path):
    """A PDF whose only page is one image covering the sheet: a 'document'."""
    page_image = Image.new("RGB", (850, 1100), "white")
    draw = ImageDraw.Draw(page_image)
    for y in range(80, 1000, 40):
        draw.rectangle((60, y, 790, y + 14), fill=(40, 40, 40))   # lines of text
    buf = io.BytesIO()
    page_image.save(buf, "PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    doc.close()


def test_a_scanned_document_page_is_not_taken_as_the_photo(tmp_path):
    pdf = tmp_path / "Police Verification.pdf"
    _full_page_scan_pdf(pdf)
    with pytest.raises(photo_extraction.PhotoNotFound):
        photo_extraction.extract_photo(str(pdf), str(tmp_path / "out.png"))
    assert not (tmp_path / "out.png").exists()


def test_a_full_page_photograph_is_still_taken(tmp_path, monkeypatch):
    pdf = tmp_path / "Photo.pdf"
    _full_page_scan_pdf(pdf)
    monkeypatch.setattr(photo_extraction, "contains_face", lambda image: True)
    candidate = photo_extraction.extract_photo(str(pdf), str(tmp_path / "out.png"))
    assert candidate.page == 1
    assert (tmp_path / "out.png").exists()


def test_the_photo_saves_across_disks(tmp_path, monkeypatch):
    """On the server /tmp and the photo folder are different filesystems:
    a plain rename fails there with Errno 18, so the save must not rely on
    it (found on the first live run)."""
    import errno
    import os

    pdf = tmp_path / "Photo.pdf"
    _full_page_scan_pdf(pdf)
    monkeypatch.setattr(photo_extraction, "contains_face", lambda image: True)
    monkeypatch.setattr(photo_extraction, "face_fraction", lambda image: 0.3)

    def no_cross_device(src, dst, *a, **k):
        raise OSError(errno.EXDEV, "Invalid cross-device link")
    monkeypatch.setattr(os, "rename", no_cross_device)
    monkeypatch.setattr(os, "replace", no_cross_device)

    out = tmp_path / "photos" / "1A000001.png"
    photo_extraction.extract_best_photo([str(pdf)], str(out))
    assert out.exists()


def test_best_photo_refuses_when_every_pdf_is_a_document(tmp_path):
    pdf = tmp_path / "Character Certificate.pdf"
    _full_page_scan_pdf(pdf)
    with pytest.raises(photo_extraction.PhotoNotFound):
        photo_extraction.extract_best_photo([str(pdf)], str(tmp_path / "out.png"))
