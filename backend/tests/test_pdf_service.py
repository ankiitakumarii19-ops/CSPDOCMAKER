"""DOCX → PDF conversion via LibreOffice headless.

The conversion tests need LibreOffice and skip without it, so the suite still
runs on a machine that has not installed it. The strictness tests — a missing
binary, a missing file, a non-PDF result — do not need it and always run,
because those are the paths that must never let a bad document through.
"""

import os

import pytest

from app.services import pdf_service, template_service
from app.models.enums import DocumentType

needs_libreoffice = pytest.mark.skipif(
    not pdf_service.is_available(),
    reason="LibreOffice is not installed on this machine",
)


def test_find_libreoffice_prefers_the_configured_path(monkeypatch, tmp_path):
    fake = tmp_path / "soffice.exe"
    fake.write_bytes(b"x")
    monkeypatch.setattr(pdf_service.settings, "libreoffice_path", str(fake))
    assert pdf_service.find_libreoffice() == str(fake)


def test_a_configured_path_that_does_not_exist_is_not_used(monkeypatch, tmp_path):
    """A pinned path that is wrong must fail loudly, not fall back silently."""
    monkeypatch.setattr(
        pdf_service.settings, "libreoffice_path", str(tmp_path / "nope.exe"))
    assert pdf_service.find_libreoffice() is None


def test_conversion_refuses_when_libreoffice_is_missing(monkeypatch, tmp_path):
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"not really a docx")
    monkeypatch.setattr(pdf_service, "find_libreoffice", lambda: None)
    with pytest.raises(pdf_service.PDFConversionError, match="not installed"):
        pdf_service.convert_to_pdf(str(docx))


def test_conversion_refuses_a_missing_file(tmp_path):
    with pytest.raises(pdf_service.PDFConversionError, match="file not found"):
        pdf_service.convert_to_pdf(str(tmp_path / "nothing.docx"))


def test_a_zero_exit_code_is_not_treated_as_success(monkeypatch, tmp_path):
    """LibreOffice can exit 0 and write nothing; that must still fail."""
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"x")
    monkeypatch.setattr(pdf_service, "find_libreoffice", lambda: "soffice")

    class _Result:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(pdf_service.subprocess, "run", lambda *a, **k: _Result())
    with pytest.raises(pdf_service.PDFConversionError, match="produced no PDF"):
        pdf_service.convert_to_pdf(str(docx))


def test_a_result_that_is_not_a_pdf_is_rejected(monkeypatch, tmp_path):
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"x")
    monkeypatch.setattr(pdf_service, "find_libreoffice", lambda: "soffice")

    class _Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(*args, **kwargs):
        # Write a file with the right name but the wrong content.
        (tmp_path / "a.pdf").write_bytes(b"This is not a PDF")
        return _Result()

    monkeypatch.setattr(pdf_service.subprocess, "run", fake_run)
    with pytest.raises(pdf_service.PDFConversionError, match="not a PDF"):
        pdf_service.convert_to_pdf(str(docx))
    assert not (tmp_path / "a.pdf").exists(), "the bad file must be cleaned up"


def test_an_empty_pdf_is_rejected(monkeypatch, tmp_path):
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"x")
    monkeypatch.setattr(pdf_service, "find_libreoffice", lambda: "soffice")

    class _Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(*args, **kwargs):
        (tmp_path / "a.pdf").write_bytes(b"")
        return _Result()

    monkeypatch.setattr(pdf_service.subprocess, "run", fake_run)
    with pytest.raises(pdf_service.PDFConversionError):
        pdf_service.convert_to_pdf(str(docx))


def test_a_timeout_is_reported_not_swallowed(monkeypatch, tmp_path):
    import subprocess

    docx = tmp_path / "a.docx"
    docx.write_bytes(b"x")
    monkeypatch.setattr(pdf_service, "find_libreoffice", lambda: "soffice")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=1)

    monkeypatch.setattr(pdf_service.subprocess, "run", fake_run)
    with pytest.raises(pdf_service.PDFConversionError, match="timed out"):
        pdf_service.convert_to_pdf(str(docx))


def test_each_conversion_uses_its_own_profile(monkeypatch, tmp_path):
    """Concurrent LibreOffice runs collide unless each gets a fresh profile."""
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"x")
    monkeypatch.setattr(pdf_service, "find_libreoffice", lambda: "soffice")
    seen = []

    class _Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(command, *args, **kwargs):
        seen.append(next(c for c in command if c.startswith("-env:")))
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
        return _Result()

    monkeypatch.setattr(pdf_service.subprocess, "run", fake_run)
    pdf_service.convert_to_pdf(str(docx))
    pdf_service.convert_to_pdf(str(docx))
    assert seen[0] != seen[1], "two conversions shared a LibreOffice profile"


# ---- Real conversion, only where LibreOffice is installed ----------------

@needs_libreoffice
def test_a_real_template_converts_to_a_readable_pdf(tmp_path):
    """Convert an actual supplied template, not a synthetic document."""
    source = template_service.template_path(DocumentType.CSP_CERTIFICATE)
    working_copy = tmp_path / "CSP Certificate.docx"
    working_copy.write_bytes(open(source, "rb").read())

    pdf_path = pdf_service.convert_to_pdf(str(working_copy))

    assert os.path.isfile(pdf_path)
    assert pdf_path.endswith(".pdf")
    with open(pdf_path, "rb") as fh:
        assert fh.read(5) == b"%PDF-"
    assert os.path.getsize(pdf_path) > 1000, "a real PDF should not be tiny"


@needs_libreoffice
def test_convert_all_returns_a_pdf_for_every_input(tmp_path):
    sources = []
    for doc_type in (DocumentType.CSP_CERTIFICATE, DocumentType.BCP):
        src = template_service.template_path(doc_type)
        dest = tmp_path / os.path.basename(src)
        dest.write_bytes(open(src, "rb").read())
        sources.append(str(dest))

    pairs = pdf_service.convert_all(sources)

    assert len(pairs) == 2
    for docx_path, pdf_path in pairs:
        assert docx_path in sources
        assert os.path.isfile(pdf_path)
