"""
CSP DocMaker — take a CSP's photo from the CSP sheet's Photo column

Decided 14 Oct 2026 (tracker No. 99). Staff put each CSP's photo in that
CSP's row, in the Photo column of KOData / SUBKOData. The Sheets API does
not return pictures (a Photo cell reads as empty), so the spreadsheet is
exported as an Excel file through the Drive API: Google writes every
picture into it, anchored at the cell it sits in, byte for byte as it was
put in the sheet. The picture whose anchor is in a row's Photo cell is that
row's CSP's photo; the row's "CSP Code" cell says whose.

A row with more than one picture in its Photo cell is ambiguous and is not
used: a wrong face on an ID Card is worse than asking for the photo.

The export is reused for CACHE_SECONDS, so a request for several CSPs (or
the pending-request run going through many) downloads it once.
"""

import io
import logging
import os
import posixpath
import re
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple
from xml.etree import ElementTree

from app import telemetry
from app.config import get_settings

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CACHE_SECONDS = 60

CODE_HEADER = "CSP Code"
PHOTO_HEADER = "Photo"

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
_R_ID = f"{{{_NS['r']}}}id"
_R_EMBED = f"{{{_NS['r']}}}embed"

# Reasons a photo was not taken from the sheet — each one actionable.
NOT_CONFIGURED = "sheet_not_configured"
NOT_IN_SHEET = "csp_not_in_sheet"
NO_PICTURE = "no_picture_in_photo_cell"
AMBIGUOUS = "several_pictures_in_photo_cell"
SHEET_ERROR = "sheet_unavailable"

REASON_TEXT = {
    NOT_CONFIGURED: "The CSP sheet is not configured.",
    NOT_IN_SHEET: "This CSP's code is not in the CSP sheet.",
    NO_PICTURE: "The CSP's Photo cell in the sheet has no picture.",
    AMBIGUOUS: "The CSP's Photo cell in the sheet has more than one picture.",
    SHEET_ERROR: "The CSP sheet could not be read.",
}


class SheetPhotoError(RuntimeError):
    """The workbook could not be exported or read."""


@dataclass
class SheetPicture:
    data: bytes
    extension: str          # ".jpg", ".png", … as Google stored it
    tab: str
    row: int                # 1-based, as the sheet shows it


@dataclass
class SheetPhotos:
    """Everything the Photo columns hold, by CSP code."""
    pictures: Dict[str, SheetPicture]
    ambiguous: Dict[str, Tuple[str, int]]   # code -> (tab, row)
    codes: set                              # every code seen in the tabs


# ---- reading the exported workbook (pure; tested without Google) --------

def _col_index(ref: str) -> int:
    """0-based column of a cell reference such as 'U15'."""
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _rels(z: zipfile.ZipFile, part: str) -> Dict[str, str]:
    """Relationship id -> target part path, for one part of the package."""
    folder, name = posixpath.split(part)
    rels_part = posixpath.join(folder, "_rels", name + ".rels")
    if rels_part not in z.namelist():
        return {}
    root = ElementTree.fromstring(z.read(rels_part))
    out = {}
    for rel in root.findall("rel:Relationship", _NS):
        target = rel.get("Target", "")
        out[rel.get("Id")] = (target.lstrip("/") if target.startswith("/")
                              else posixpath.normpath(posixpath.join(folder, target)))
    return out


def _shared_strings(z: zipfile.ZipFile) -> list:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t"))
            for si in root.findall("m:si", _NS)]


def _cell_text(cell, strings: list) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{{{_NS['m']}}}t")).strip()
    v = cell.find("m:v", _NS)
    if v is None or v.text is None:
        return ""
    if kind == "s":
        return strings[int(v.text)].strip()
    return v.text.strip()


def _read_tab(z, tab, sheet_part, strings, found: SheetPhotos) -> None:
    root = ElementTree.fromstring(z.read(sheet_part))
    rows = {}
    for row in root.iter(f"{{{_NS['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", _NS):
            cells[_col_index(c.get("r"))] = c
        rows[int(row.get("r"))] = cells
    header = {(_cell_text(c, strings)): i for i, c in rows.get(1, {}).items()}
    code_col, photo_col = header.get(CODE_HEADER), header.get(PHOTO_HEADER)
    if code_col is None or photo_col is None:
        logger.warning("sheet_photo_reader: tab '%s' has no '%s' or '%s' "
                       "column; no photos read from it", tab, CODE_HEADER,
                       PHOTO_HEADER)
        return

    code_by_row = {}
    for n, cells in rows.items():
        if n == 1 or code_col not in cells:
            continue
        code = _cell_text(cells[code_col], strings)
        if code:
            code_by_row[n] = code
            found.codes.add(code)
        photo_cell = cells.get(photo_col)
        if photo_cell is not None and photo_cell.get("vm") is not None:
            # A picture stored *inside* the cell (Excel's "place in cell").
            # Google exports its pictures as anchored ones, so this is not
            # expected; said rather than silently skipped.
            logger.warning("sheet_photo_reader: tab '%s' row %d holds an "
                           "in-cell picture this reader does not support",
                           tab, n)

    by_row: Dict[int, list] = {}
    for rid, drawing_part in _rels(z, sheet_part).items():
        if "/drawings/" not in drawing_part:
            continue
        media = _rels(z, drawing_part)
        drawing = ElementTree.fromstring(z.read(drawing_part))
        for anchor in list(drawing):
            start = anchor.find("xdr:from", _NS)
            blip = anchor.find(".//a:blip", _NS)
            if start is None or blip is None:
                continue
            col = int(start.find("xdr:col", _NS).text)
            row = int(start.find("xdr:row", _NS).text) + 1
            target = media.get(blip.get(_R_EMBED))
            if col != photo_col or row == 1 or not target:
                continue
            by_row.setdefault(row, []).append(target)

    for row, targets in sorted(by_row.items()):
        code = code_by_row.get(row)
        if not code:
            logger.warning("sheet_photo_reader: tab '%s' row %d has a picture "
                           "in the Photo column but no CSP code; not used",
                           tab, row)
            continue
        if len(targets) > 1 or code in found.pictures or code in found.ambiguous:
            # Two pictures for one CSP: which is theirs cannot be told.
            found.pictures.pop(code, None)
            found.ambiguous[code] = (tab, row)
            continue
        found.pictures[code] = SheetPicture(
            data=z.read(targets[0]),
            extension=os.path.splitext(targets[0])[1].lower() or ".png",
            tab=tab, row=row)


def photos_in_workbook(xlsx: bytes, tabs: Iterable[str]) -> SheetPhotos:
    """The pictures in the Photo column of each named tab, by CSP code."""
    found = SheetPhotos(pictures={}, ambiguous={}, codes=set())
    with zipfile.ZipFile(io.BytesIO(xlsx)) as z:
        workbook = ElementTree.fromstring(z.read("xl/workbook.xml"))
        wb_rels = _rels(z, "xl/workbook.xml")
        parts = {s.get("name"): wb_rels.get(s.get(_R_ID))
                 for s in workbook.iter(f"{{{_NS['m']}}}sheet")}
        strings = _shared_strings(z)
        for tab in tabs:
            if not tab or not parts.get(tab):
                continue
            _read_tab(z, tab, parts[tab], strings, found)
    return found


# ---- getting the workbook from Google -----------------------------------

_cache_lock = threading.Lock()
_cache: Optional[Tuple[float, SheetPhotos]] = None


def _export_workbook(sheet_id: str) -> bytes:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    settings = get_settings()
    credentials = service_account.Credentials.from_service_account_file(
        settings.google_sheets_credentials_file, scopes=DRIVE_SCOPES)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    # Traced by telemetry.instrument_google_api like every Google call.
    return drive.files().export(fileId=sheet_id, mimeType=XLSX_MIME).execute()


def sheet_photos(refresh: bool = False) -> SheetPhotos:
    """The Photo columns of the CSP sheet. Raises SheetPhotoError."""
    global _cache
    settings = get_settings()
    sheet_id = settings.google_sheets_csp_sheet_id
    if not sheet_id:
        raise SheetPhotoError(REASON_TEXT[NOT_CONFIGURED])
    with _cache_lock:
        if (not refresh and _cache is not None
                and time.monotonic() - _cache[0] < CACHE_SECONDS):
            return _cache[1]
        try:
            xlsx = _export_workbook(sheet_id)
            found = photos_in_workbook(
                xlsx, (settings.google_sheets_csp_sheet_name,
                       settings.google_sheets_subko_sheet_name))
        except Exception as e:
            raise SheetPhotoError(
                f"{REASON_TEXT[SHEET_ERROR]} {type(e).__name__}: {e}") from e
        logger.info("sheet_photo_reader: %d photo(s) in the sheet's Photo "
                    "column; %d CSP(s) with more than one picture",
                    len(found.pictures), len(found.ambiguous))
        _cache = (time.monotonic(), found)
        return found


def clear_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


@telemetry.traced("find_photo_in_sheet", "sheet_photo_reader")
def fetch_photo(csp):
    """Save this CSP's photo from the sheet. Returns a csp_photo_service
    PhotoResult; on success its path is the saved file."""
    from PIL import Image

    from app.services import csp_photo_service
    from app.services.document_service import _safe_folder_name

    PhotoResult = csp_photo_service.PhotoResult
    code = (getattr(csp, "csp_code", None) or csp.csp_id or "").strip()
    try:
        found = sheet_photos()
    except SheetPhotoError as e:
        logger.error("sheet_photo_reader: CSP %s — %s", csp.csp_id, e,
                     exc_info=True)
        return PhotoResult(False, reason=SHEET_ERROR, detail=str(e))

    picture = found.pictures.get(code) or found.pictures.get(csp.csp_id)
    if picture is None:
        if code in found.ambiguous:
            tab, row = found.ambiguous[code]
            reason = AMBIGUOUS
            detail = f"{REASON_TEXT[reason]} ({tab} row {row})"
        elif code in found.codes or csp.csp_id in found.codes:
            reason = NO_PICTURE
            detail = REASON_TEXT[reason]
        else:
            reason = NOT_IN_SHEET
            detail = REASON_TEXT[reason]
        logger.info("sheet_photo_reader: CSP %s — %s", csp.csp_id, detail)
        return PhotoResult(False, reason=reason, detail=detail)

    try:
        with Image.open(io.BytesIO(picture.data)) as image:
            image.verify()
    except Exception as e:
        detail = (f"The picture in the sheet ({picture.tab} row "
                  f"{picture.row}) is not a readable image "
                  f"({type(e).__name__}: {e})")
        logger.error("sheet_photo_reader: CSP %s — %s", csp.csp_id, detail)
        return PhotoResult(False, reason=NO_PICTURE, detail=detail)

    destination = os.path.join(
        csp_photo_service.photo_directory(),
        f"{_safe_folder_name(csp.csp_id)}{picture.extension}")
    with open(destination, "wb") as fh:
        fh.write(picture.data)
    source = f"the sheet ({picture.tab} row {picture.row})"
    logger.info("sheet_photo_reader: CSP %s — photo taken from %s",
                csp.csp_id, source)
    return PhotoResult(True, path=destination, source=source)
