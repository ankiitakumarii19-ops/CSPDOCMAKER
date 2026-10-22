"""
CSP DocMaker — reading, mapping and editing an uploaded template

An admin uploads a .docx. Three questions follow, and this answers all three
without the admin needing to know how the system works inside:

  1. What placeholders does it contain?  Read out of the file itself.
  2. What fills each one?                Guessed from the name, then corrected.
  3. Where does the photograph go?       The paragraph the photo replaces.

On editing the wording in the browser: the text is edited RUN BY RUN, in
place, and the file is never rebuilt. Converting a .docx to HTML and back
would lose the text boxes the ID Card is built from, the VML frame that makes
the photograph passport size, and the embedded signature. Editing the runs
leaves all of that untouched — the only thing that changes is the words.
"""

import hashlib
import io
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from docx import Document
from docx.oxml.ns import qn

from app.services import template_service as ts

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024          # a .docx template, not a library
DOCX_MAGIC = b"PK\x03\x04"                   # a .docx is a zip


class TemplateUploadError(ValueError):
    """The uploaded file cannot be used as a template."""


# ---- what a placeholder is called, and what fills it --------------------

def _norm(text: str) -> str:
    """Compare placeholder names ignoring case, spacing and punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def known_vocabulary() -> Dict[str, str]:
    """Placeholder name -> canonical field, as the supplied templates use them.

    Built from the four templates rather than written out again, so a
    template that follows the existing naming maps itself.
    """
    vocabulary: Dict[str, str] = {}
    for mapping in ts.PLACEHOLDER_FIELDS.values():
        for text, field in mapping.items():
            vocabulary.setdefault(_norm(text), field)
    return vocabulary


# Names an admin is likely to use that the supplied templates never did.
# Kept small and obvious: a guess that is wrong prints the wrong value on an
# official document, so anything doubtful is left for the admin to map.
_ALIASES: Dict[str, str] = {
    "name": "csp_name",
    "csp": "csp_name",
    "code": "csp_code",
    "kiosk code": "csp_code",
    "mobile": "mobile",
    "mobile number": "mobile",
    "phone": "mobile",
    "phone number": "mobile",
    "csp mobile number": "mobile",
    "email": "email",
    "email id": "email",
    "e mail": "email",
    "branch": "branch_name",
    "date": "certificate_date",
    "month year": "certificate_month_year",
    "asm name": "asm_name",
    "asm email id": "asm_email",
    "dc": "dc",
    "lho": "lho",
    "gender": "gender",
}


def auto_map(placeholders) -> Tuple[Dict[str, str], List[str]]:
    """Guess what fills each placeholder. Returns (mapped, unmapped).

    Only exact matches on a known name are taken. A near-miss is reported as
    unmapped for the admin to decide: printing the wrong field on a
    certificate is worse than asking one question.
    """
    vocabulary = {**known_vocabulary(), **_ALIASES}
    mapped: Dict[str, str] = {}
    unmapped: List[str] = []
    for text in placeholders:
        field = vocabulary.get(_norm(text))
        if field:
            mapped[text] = field
        else:
            unmapped.append(text)
    return mapped, sorted(unmapped)


# ---- reading an uploaded file ------------------------------------------

def _open(source) -> Document:
    if isinstance(source, (bytes, bytearray)):
        return Document(io.BytesIO(bytes(source)))
    return Document(source)


def validate_upload(data: bytes, filename: str = "") -> None:
    """Refuse anything that is not a usable .docx, before it is stored."""
    if not data:
        raise TemplateUploadError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise TemplateUploadError(
            f"That file is {len(data) // 1024 // 1024}MB. A template must be "
            f"under {MAX_UPLOAD_BYTES // 1024 // 1024}MB."
        )
    if not data.startswith(DOCX_MAGIC):
        raise TemplateUploadError(
            "That is not a .docx file. Save it from Word as .docx — the older "
            ".doc format cannot be read."
        )
    try:
        _open(data)
    except Exception as e:
        raise TemplateUploadError(
            f"That .docx could not be opened: {type(e).__name__}. It may be "
            f"corrupt, or password protected."
        ) from e


def read_placeholders(source) -> List[str]:
    """Every placeholder in the file, in the order it first appears."""
    doc = _open(source)
    found: List[str] = []
    for para in ts._all_paragraphs(doc):
        text = "".join(run.text for run in para.runs)
        for match in ts._PLACEHOLDER_RE.finditer(text):
            name = match.group(1).strip()
            if name and name not in found:
                found.append(name)
    return found


_PHOTO_HINTS = ("photo", "photograph", "affix")


def guess_photo_marker(source) -> Optional[str]:
    """The paragraph that looks like it is where the photograph goes.

    A guess, shown to the admin to confirm — never applied silently. A wrong
    marker replaces the wrong paragraph with someone's face.
    """
    doc = _open(source)
    for para in ts._all_paragraphs(doc):
        text = "".join(run.text for run in para.runs).strip()
        if not text or len(text) > 80:
            continue
        lowered = text.lower()
        if any(hint in lowered for hint in _PHOTO_HINTS):
            if not ts._PLACEHOLDER_RE.search(text):
                # A photo box drawn as a table cell spreads its caption over
                # several lines ("Affix Passport" / "Size Photo" /
                # "(35 × 45 mm)"); the marker is the whole cell's text.
                cell = para._p.getparent()
                if cell is not None and cell.tag == qn("w:tc"):
                    whole = ts._squash(" ".join(
                        "".join(t.text or "" for t in p.iter(qn("w:t")))
                        for p in cell.findall(qn("w:p"))))
                    if whole and len(whole) <= 80:
                        return whole
                return text
    return None


def read_paragraphs(source) -> List[dict]:
    """The document's text, addressable for editing.

    Only paragraphs that carry text are returned; the index is the position
    among all paragraphs, so an edit can be applied back to the right one.
    """
    doc = _open(source)
    out: List[dict] = []
    for index, para in enumerate(ts._all_paragraphs(doc)):
        text = "".join(run.text for run in para.runs)
        if not text.strip():
            continue
        out.append({
            "index": index,
            "text": text,
            "has_placeholder": bool(ts._PLACEHOLDER_RE.search(text)),
        })
    return out


def inspect(source) -> dict:
    """Everything the admin screen needs to show about an uploaded file."""
    placeholders = read_placeholders(source)
    mapped, unmapped = auto_map(placeholders)
    return {
        "placeholders": placeholders,
        "mapped": mapped,
        "unmapped": unmapped,
        "paragraphs": read_paragraphs(source),
        "photo_marker": guess_photo_marker(source),
    }


# ---- editing the wording, without touching the layout -------------------

def _placeholders_in(text: str) -> set:
    return {m.group(1).strip() for m in ts._PLACEHOLDER_RE.finditer(text or "")}


def apply_paragraph_edits(source, edits: Dict[int, str]) -> bytes:
    """Rewrite the wording of the given paragraphs. Returns the new .docx.

    The new text goes into the paragraph's FIRST run and the rest are
    emptied, so the paragraph keeps its own formatting and the document keeps
    its structure. Nothing is rebuilt: images, text boxes, the VML photo
    frame and the embedded signature are all carried through untouched.
    """
    doc = _open(source)
    paragraphs = list(ts._all_paragraphs(doc))

    for raw_index, new_text in edits.items():
        index = int(raw_index)
        if index < 0 or index >= len(paragraphs):
            raise TemplateUploadError(
                f"There is no paragraph {index} in this template.")
        para = paragraphs[index]
        if not para.runs:
            raise TemplateUploadError(
                f"Paragraph {index} has no text to replace.")

        old = "".join(r.text for r in para.runs)
        lost = _placeholders_in(old) - _placeholders_in(new_text)
        if lost:
            raise TemplateUploadError(
                f"That edit removes {sorted(lost)} from the document. A "
                f"placeholder that disappears is a value that stops being "
                f"printed — put it back, or remove it from the mapping first."
            )

        para.runs[0].text = new_text
        for run in para.runs[1:]:
            run.text = ""

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- keeping the four supplied documents in step ------------------------

async def sync_builtin_templates(session) -> int:
    """Give each built-in row the mapping that currently lives in code.

    The migration that created `document_templates` seeded the four supplied
    documents by name only — it could not read their placeholder maps,
    because a migration must not depend on the template files being present.

    So the rows exist with an empty mapping while the real one is still in
    `template_service.PLACEHOLDER_FIELDS`. Until both agree, the admin screen
    shows the supplied documents as "unmapped", which is not true.

    Only a built-in with no mapping of its own is touched, so an admin who
    has since changed one keeps their change. Returns how many were filled.
    """
    from sqlalchemy import select

    from app.models.document_template import DocumentTemplate
    from app.models.enums import DocumentType

    by_code = {d.name: d for d in DocumentType}
    rows = (await session.execute(
        select(DocumentTemplate).where(DocumentTemplate.is_builtin.is_(True))
    )).scalars().all()

    filled = 0
    for row in rows:
        doc_type = by_code.get(row.code)
        if doc_type is None:
            continue
        if not row.placeholder_map:
            row.placeholder_map = dict(ts.PLACEHOLDER_FIELDS.get(doc_type, {}))
            filled += 1
        if row.photo_marker is None:
            row.photo_marker = ts.PHOTO_MARKERS.get(doc_type)
        # The file on disk is the one generation reads, so keep the name in
        # step with whatever it has been renamed to in Word.
        try:
            row.filename = os.path.basename(ts.template_path(doc_type))
        except Exception as e:
            # Not fatal — the stored name is kept — but never silent: a
            # missing template file is worth knowing about at start-up.
            logger.warning("document_template_service: template file for %s "
                           "not found, keeping stored name %r: %s: %s",
                           row.code, row.filename, type(e).__name__, e)

    if filled:
        await session.commit()
        logger.info(
            "document_template_service.sync_builtin_templates: filled the "
            "mapping for %d supplied template(s)", filled,
        )
    return filled


async def sync_builtin_data_sources(session) -> int:
    """Record this workspace's existing Google Sheets as data sources.

    The sheets were configured in the environment long before data sources
    were a thing in the database. Registering them makes the configuration
    visible and editable instead of invisible and hard-coded — and it means
    the first workspace is described the same way every later one will be,
    rather than being a special case the code has to remember.

    Nothing about how the sheets are read changes. This records what is
    already true. Idempotent: an existing source is left alone.
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.data_source import (
        GOOGLE_SHEET, PURPOSE_AUTHORIZATION, PURPOSE_DIRECTORY,
        PURPOSE_RECORDS, DataSource,
    )
    from app.services import csp_mapping

    settings = get_settings()
    wanted = [
        {
            "name": "CSP records",
            "purpose": PURPOSE_RECORDS,
            "connection": {
                "spreadsheet_id": settings.google_sheets_csp_sheet_id,
                "tab": settings.google_sheets_csp_sheet_name,
                "tabs": [settings.google_sheets_csp_sheet_name,
                         settings.google_sheets_subko_sheet_name],
            },
            "column_map": dict(csp_mapping.SHEET_COLUMN_TO_FIELD),
            "sync_interval_minutes": settings.csp_sync_interval_minutes,
        },
        {
            "name": "Territory directory (INFO)",
            "purpose": PURPOSE_DIRECTORY,
            "connection": {
                "spreadsheet_id": settings.google_sheets_csp_sheet_id,
                "tab": settings.google_sheets_info_tab_name,
            },
            "column_map": {},
            "sync_interval_minutes": settings.csp_sync_interval_minutes,
        },
        {
            "name": "Authorization",
            "purpose": PURPOSE_AUTHORIZATION,
            "connection": {
                "spreadsheet_id": settings.google_sheets_id,
                "tabs": [settings.google_sheets_rm_sheet_name,
                         settings.google_sheets_admin_sheet_name],
            },
            "column_map": {},
            "sync_interval_minutes":
                settings.google_sheets_sync_interval_minutes,
        },
    ]

    existing = {
        s.name for s in
        (await session.execute(select(DataSource))).scalars().all()
    }

    added = 0
    for spec in wanted:
        if spec["name"] in existing:
            continue
        session.add(DataSource(
            kind=GOOGLE_SHEET,
            # The credential is an environment key, never a value stored here.
            secret_ref="GOOGLE_SHEETS_CREDENTIALS_FILE",
            active=True,
            **spec,
        ))
        added += 1

    if added:
        await session.commit()
        logger.info(
            "document_template_service.sync_builtin_data_sources: recorded "
            "%d existing Google Sheet source(s)", added,
        )
    return added


async def sync_builtin_dashboards(session) -> int:
    """Give the system dashboard its widgets, and offer the verification one.

    The migration created the permanent dashboard but could not fill it: a
    migration cannot read the metric registry. This does.

    It also creates the CSP verification dashboard, marked removable —
    it matters while a workspace is collecting CSP details and stops
    mattering once that is done, at which point a Super Admin retires it
    and the data behind it stays exactly where it is.

    Idempotent. A dashboard an admin has since edited, hidden or deleted is
    left alone: only an empty system dashboard is filled, and the
    verification one is created only if it has never existed.
    """
    from sqlalchemy import select

    from app.models.dashboard import (
        BREAKDOWN, METRIC_CARD, SYSTEM_SLUG, TABLE, Dashboard, DashboardWidget,
    )

    changed = 0

    system = (await session.execute(
        select(Dashboard).where(Dashboard.slug == SYSTEM_SLUG)
    )).scalars().first()

    if system is not None and not system.widgets:
        for position, (kind, metric, title, width) in enumerate([
            (METRIC_CARD, "documents.generated", "Generated", 1),
            (METRIC_CARD, "documents.mailed", "Mailed", 1),
            (METRIC_CARD, "documents.pending", "Pending", 1),
            (METRIC_CARD, "documents.failed", "Failed", 1),
            (TABLE, "documents.by_type", "By document", 4),
        ]):
            system.widgets.append(DashboardWidget(
                kind=kind, metric=metric, title=title, width=width,
                position=position, config={},
            ))
        changed += 1

    verification = (await session.execute(
        select(Dashboard).where(Dashboard.slug == "csp-verification")
    )).scalars().first()

    if verification is None:
        verification = Dashboard(
            slug="csp-verification",
            name="CSP Data & Verification",
            description=(
                "Where each CSP is in confirming their own details. Retire "
                "this once collection is finished — the data stays."
            ),
            icon="fa-clipboard-check",
            is_system=False,       # removable, deliberately
            active=True,
            position=1,
        )
        for position, (kind, metric, title, width) in enumerate([
            (METRIC_CARD, "verification.total", "CSPs total", 1),
            (METRIC_CARD, "verification.confirmed", "Confirmed", 1),
            (METRIC_CARD, "verification.waiting_on_csp", "Waiting on CSP", 1),
            (METRIC_CARD, "verification.not_contacted", "Not contacted", 1),
            (METRIC_CARD, "data.missing_csp_details", "Missing own details", 1),
            (METRIC_CARD, "data.missing_org_details", "Missing hierarchy", 1),
            (METRIC_CARD, "data.missing_photo", "Missing photo", 1),
            (METRIC_CARD, "verification.expired", "Links expired", 1),
            (BREAKDOWN, "verification.documents_held",
             "Documents CSPs already hold", 2),
            (TABLE, "verification.recent_submissions", "Recent submissions", 2),
        ]):
            verification.widgets.append(DashboardWidget(
                kind=kind, metric=metric, title=title, width=width,
                position=position, config={},
            ))
        session.add(verification)
        changed += 1

    if changed:
        await session.commit()
        logger.info(
            "document_template_service.sync_builtin_dashboards: seeded %d "
            "dashboard(s)", changed,
        )
    return changed


async def sync_builtin_messages(session, signature: str | None = None) -> int:
    """Give a workspace the wording it starts with.

    Chasing missing data is universal — every workspace gets it, because a
    document cannot be issued without the data and somebody has to be
    asked. What is NOT universal is how it is said. These are supplied as
    a starting point, marked built-in so they cannot be deleted, and fully
    editable: a customer's tone, languages and signature are theirs.

    `signature` replaces the "— Team Eko" / "— Team" sign-off — a new
    workspace set up from the chat signs with its own name (No. 117).
    """
    from sqlalchemy import select

    from app.models.messaging import (
        EMAIL, PURPOSE_DATA_REQUEST, PURPOSE_DOCUMENTS_READY,
        PURPOSE_MISSING_DATA, WHATSAPP, MessageTemplate,
    )

    supplied = [
        {
            "purpose": PURPOSE_DATA_REQUEST,
            "name": "Ask the CSP to confirm their details",
            "channel_kind": WHATSAPP,
            "languages": ["en", "hi", "hi-Latn"],
            "body": (
                # First sentence changed 22 Oct 2026 (No. 136): a new
                # template for the WhatsApp platform (see migration
                # c3e5a7b9d1f4).
                "Namaste {name}, please confirm your details for your CSP "
                "documents. Open this link, check what is already "
                "filled, correct anything wrong, and submit. You can submit "
                "only ONCE, so please check carefully before you send.\n\n"
                "{link}\n\n"
                "नमस्ते {name}, आपके CSP दस्तावेज़ों के लिए आपकी जानकारी की "
                "पुष्टि आवश्यक है। कृपया ऊपर दिए गए लिंक पर जाकर पहले से भरी "
                "जानकारी देखें, कुछ गलत हो तो सुधारें और जमा करें। आप केवल एक ही "
                "बार जमा कर सकते हैं।\n\n"
                "Namaste {name}, aapke CSP documents ke liye aapki details "
                "confirm karni hain. Upar diye gaye link par jaakar pehle se "
                "bhari hui details dekhein, kuch galat ho to sudhaarein aur "
                "submit karein. Aap sirf EK HI BAAR submit kar sakte hain.\n\n"
                "— Team Eko"
            ),
        },
        {
            "purpose": PURPOSE_MISSING_DATA,
            "name": "Tell the CSP what is missing",
            "channel_kind": WHATSAPP,
            "languages": ["en", "hi"],
            "body": (
                "Namaste {name}, these details are still needed before your "
                "documents can be issued: {fields}. Please open this link to "
                "supply them.\n\n{link}\n\n"
                "नमस्ते {name}, आपके दस्तावेज़ जारी करने के लिए यह जानकारी "
                "चाहिए: {fields}।\n\n— Team Eko"
            ),
        },
        {
            "purpose": PURPOSE_DOCUMENTS_READY,
            "name": "Send the finished documents",
            "channel_kind": EMAIL,
            "subject": "Your CSP documents",
            "languages": ["en"],
            "body": (
                "Dear {name},\n\nYour documents are attached.\n\n"
                "If anything on them is wrong, please contact your "
                "Relationship Manager.\n\n— Team"
            ),
        },
    ]

    if signature:
        for spec in supplied:
            body = spec["body"].replace("— Team Eko", f"— {signature}")
            if body.endswith("— Team"):
                body = body[:-len("— Team")] + f"— {signature}"
            spec["body"] = body

    existing = {
        t.name for t in
        (await session.execute(select(MessageTemplate))).scalars().all()
    }

    added = 0
    for spec in supplied:
        if spec["name"] in existing:
            continue
        session.add(MessageTemplate(is_builtin=True, active=True, **spec))
        added += 1

    if added:
        await session.commit()
        logger.info(
            "document_template_service.sync_builtin_messages: supplied %d "
            "message template(s)", added,
        )
    return added
