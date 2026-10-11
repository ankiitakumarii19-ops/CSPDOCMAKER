"""
CSP DocMaker — DOCX → PDF Conversion

Converts generated DOCX documents to PDF with LibreOffice in headless mode.
The same binary and the same command line run on the Windows development
machine and on the Linux deployment target, so a PDF approved here is
produced by the same process in production.

Why LibreOffice and not Word: the templates place most of their content in
text boxes, and Word and LibreOffice lay text boxes out differently. Using one
renderer everywhere means the output cannot drift between dev and production.

Conversion is deliberately strict. LibreOffice can exit 0 without writing a
file, so success is decided by the output file existing and carrying a PDF
header — never by the exit code alone. A document that fails to convert must
not be sent to a CSP.
"""

import logging
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from app.config import get_settings
from app import telemetry

logger = logging.getLogger(__name__)

settings = get_settings()

PDF_MAGIC = b"%PDF-"

# Where the Windows installer puts soffice.exe. On Linux it is normally on
# PATH, so shutil.which finds it without a hard-coded path.
_WINDOWS_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
_POSIX_NAMES = ("soffice", "libreoffice")


class PDFConversionError(Exception):
    """Raised when a DOCX could not be converted to a valid PDF."""


def find_libreoffice() -> Optional[str]:
    """Locate the LibreOffice binary, or None when it is not installed.

    An explicit LIBREOFFICE_PATH always wins, so a non-standard install (or a
    specific version on the server) can be pinned without touching code.
    """
    configured = (settings.libreoffice_path or "").strip()
    if configured:
        return configured if os.path.isfile(configured) else None

    for name in _POSIX_NAMES:
        found = shutil.which(name)
        if found:
            return found

    if platform.system() == "Windows":
        for candidate in _WINDOWS_CANDIDATES:
            if os.path.isfile(candidate):
                return candidate

    return None


def is_available() -> bool:
    """Whether PDF conversion can run on this machine."""
    return find_libreoffice() is not None


def _require_libreoffice() -> str:
    binary = find_libreoffice()
    if binary is None:
        raise PDFConversionError(
            "LibreOffice is not installed or could not be found. PDF conversion "
            "requires it (install it, or set LIBREOFFICE_PATH to soffice"
            f"{'.exe' if platform.system() == 'Windows' else ''})."
        )
    return binary


def _looks_like_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(len(PDF_MAGIC)) == PDF_MAGIC
    except OSError:
        return False


def convert_to_pdf(
    docx_path: str,
    output_dir: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> str:
    """Convert one DOCX to PDF and return the PDF path.

    Args:
        docx_path: The generated DOCX to convert.
        output_dir: Where to write the PDF. Defaults to the DOCX's directory.
        timeout_seconds: Hard limit on the conversion. Defaults to the
            configured PDF_CONVERSION_TIMEOUT_SECONDS.

    Raises:
        PDFConversionError: LibreOffice is missing, failed, timed out, or did
            not produce a readable PDF.
    """
    if not os.path.isfile(docx_path):
        raise PDFConversionError(f"Cannot convert: file not found: {docx_path}")

    binary = _require_libreoffice()
    timeout = timeout_seconds or settings.pdf_conversion_timeout_seconds
    target_dir = output_dir or os.path.dirname(os.path.abspath(docx_path))
    os.makedirs(target_dir, exist_ok=True)

    expected_pdf = os.path.join(
        target_dir, Path(docx_path).with_suffix(".pdf").name
    )

    # Two LibreOffice processes sharing a user profile collide and one of them
    # silently produces nothing, so every conversion gets a throwaway profile.
    # This is what makes concurrent conversions safe.
    profile_dir = tempfile.mkdtemp(prefix=f"lo_profile_{uuid.uuid4().hex[:8]}_")
    profile_uri = Path(profile_dir).as_uri()

    command = [
        binary,
        f"-env:UserInstallation={profile_uri}",
        "--headless",
        "--norestore",
        "--invisible",
        "--nolockcheck",
        "--nodefault",
        "--convert-to", "pdf:writer_pdf_Export",
        "--outdir", target_dir,
        os.path.abspath(docx_path),
    ]

    from app import telemetry

    try:
        with telemetry.external_call("libreoffice", "convert_to_pdf",
                                     file=os.path.basename(docx_path)):
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired as e:
        error = PDFConversionError(
            f"PDF conversion timed out after {timeout}s for "
            f"{os.path.basename(docx_path)}."
        )
        error.failure_kind = telemetry.TIMEOUT
        raise error from e
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    # LibreOffice reports success in the exit code even when it writes nothing,
    # so the output file is the only trustworthy signal.
    if not os.path.isfile(expected_pdf):
        stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
        stdout = (result.stdout or b"").decode("utf-8", "replace").strip()
        error = PDFConversionError(
            f"LibreOffice produced no PDF for {os.path.basename(docx_path)} "
            f"(exit={result.returncode}). stdout={stdout!r} stderr={stderr!r}"
        )
        error.failure_kind = "empty"
        logger.error("pdf_service: %s", error, extra={"failure_kind": "empty",
                                                       "service": "libreoffice"})
        raise error

    if not _looks_like_pdf(expected_pdf):
        os.remove(expected_pdf)
        error = PDFConversionError(
            f"LibreOffice wrote a file that is not a PDF for "
            f"{os.path.basename(docx_path)}."
        )
        error.failure_kind = "malformed"
        logger.error("pdf_service: %s", error, extra={"failure_kind": "malformed",
                                                       "service": "libreoffice"})
        raise error

    if os.path.getsize(expected_pdf) == 0:
        os.remove(expected_pdf)
        raise PDFConversionError(
            f"LibreOffice wrote an empty PDF for {os.path.basename(docx_path)}."
        )

    logger.info(
        "pdf_service.convert_to_pdf: %s -> %s (%d bytes)",
        os.path.basename(docx_path), os.path.basename(expected_pdf),
        os.path.getsize(expected_pdf),
    )
    return expected_pdf


@telemetry.traced("convert_to_pdf_all", "pdf_service")
def convert_all(
    docx_paths: List[str],
    output_dir: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Convert several DOCX files, returning (docx_path, pdf_path) pairs.

    Raises PDFConversionError on the first failure: a CSP must never receive a
    partial set of documents.
    """
    converted: List[Tuple[str, str]] = []
    for docx_path in docx_paths:
        converted.append((docx_path, convert_to_pdf(docx_path, output_dir)))
    return converted
