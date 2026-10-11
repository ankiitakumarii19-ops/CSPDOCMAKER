"""
CSP DocMaker — DOCX Template Service

Fills the supplied DOCX templates without altering their design.

Placeholders in the templates are field names wrapped in double quotes, e.g.
    "CSP Name"   “CSP Code”   “Making Date”
The value replaces the whole token, quotes included.

Two properties of the real templates drive this implementation:

1. Word splits a placeholder across several runs (`“` + ` Name”`), so a plain
   run-level replace finds almost nothing. Replacement is done per paragraph
   over the concatenated run text, then written back into the runs that the
   placeholder covers, which preserves the formatting of each paragraph.
2. Content lives in body paragraphs, tables, headers, footers and text boxes
   (the ID Card is entirely text boxes), so every paragraph in the package is
   visited.

Only placeholders registered for a document type are replaced, so quoted
prose in a template is never touched by accident. A template that still has
an unreplaced registered placeholder after filling is an error — a document is
never produced with a visible placeholder or a silently empty field.
"""

import logging
import os
import re
from typing import Dict, Iterator, List, Optional

from docx import Document
from docx.image.image import Image as DocxImage
from docx.oxml.ns import qn
from docx.shared import Emu, Inches
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.config import get_settings
from app.models.enums import DocumentType

logger = logging.getLogger(__name__)

settings = get_settings()

# Straight and curly double quotes, as produced by Word autocorrect.
_OPEN_QUOTES = '"“”'
_PLACEHOLDER_RE = re.compile(f"[{_OPEN_QUOTES}]([^{_OPEN_QUOTES}]{{1,60}}?)[{_OPEN_QUOTES}]")

# ---------------------------------------------------------------------------
# The five dictionaries below describe the four SUPPLIED documents.
#
# They are no longer the list of what this system can produce — that comes
# from `document_templates` via document_registry, so a document an admin
# uploaded answers exactly like one that shipped. These remain as the
# fallback the registry uses when the database cannot be reached, and as the
# source the supplied rows were seeded from.
#
# Do not add a fifth document here. Upload it.
# ---------------------------------------------------------------------------

BUILTIN_LABELS: Dict[DocumentType, str] = {
    DocumentType.CSP_ID_CARD: "CSP ID Card",
    # Renamed by the user on 11 Oct 2026 (tracker No. 57). The internal code
    # stays CSP_CERTIFICATE so the documents already stored keep their type.
    DocumentType.CSP_CERTIFICATE: "Appointment Letter",
    DocumentType.TRAINING_CERTIFICATE: "Training Certificate",
    DocumentType.BCP: "Business Continuity Plan (BCP)",
}

# Template file names as supplied.
TEMPLATE_FILES: Dict[DocumentType, str] = {
    DocumentType.CSP_ID_CARD: "ID Card.docx",
    DocumentType.CSP_CERTIFICATE: "Appointment Letter.docx",
    DocumentType.TRAINING_CERTIFICATE: "Training Certificate.docx",
    DocumentType.BCP: "BCP.docx",
}

# Placeholder text inside the template → canonical field name.
# Taken from the supplied templates; nothing here is inferred.
PLACEHOLDER_FIELDS: Dict[DocumentType, Dict[str, str]] = {
    DocumentType.CSP_ID_CARD: {
        "CSP Name": "csp_name",
        "CSP Code": "csp_code",
        "Branch Name": "branch_name",
        "Branch Code": "branch_code",
        "Address": "address",
        "Contact Number": "mobile",
    },
    DocumentType.CSP_CERTIFICATE: {
        "CSP Name": "csp_name",
        "CSP Code": "csp_code",
        "Address": "address",
        "District": "district",
        "State": "state",
    },
    DocumentType.TRAINING_CERTIFICATE: {
        "CSP Name": "csp_name",
        "CSP Code": "csp_code",
        "Branch Name": "branch_name",
        "Branch Code": "branch_code",
        "Making Date": "certificate_date",
    },
    DocumentType.BCP: {
        "CSP Name": "csp_name",
        "CSP Code": "csp_code",
        "Branch Name": "branch_name",
        "Branch Code": "branch_code",
        # The BCP's "Module" row is filled from the sheet's AO column, and the
        # template's placeholder is named after that column.
        "AO": "ao",
        "RBO Name": "rbo_name",
        "Address": "address",
        "CSP Contact Number": "mobile",
        "CSP Email ID": "email",
        "Making Month, year": "certificate_month_year",
        "ASM": "asm_name",
        "ASM Email": "asm_email",
        "ASM Contact Number": "asm_contact",
    },
}


# The CSP photo is not a quoted placeholder: the templates carry a marker
# paragraph whose text is replaced by the image. The signature is already
# embedded in the supplied templates, so nothing is inserted for it.
# The paragraph whose whole text is replaced by the CSP's photograph.
# Matched on the paragraph's exact stripped text, so renaming one in Word
# stops generation with a clear error rather than producing a document with
# the marker still printed on it.
# Since 11 Oct 2026 both are a 35 x 45 mm table cell holding three lines —
# "Affix Passport" / "Size Photo" / "(35 × 45 mm)" — so a marker is matched
# against a whole cell's text as well as a single paragraph's.
PHOTO_MARKERS: Dict[DocumentType, str] = {
    DocumentType.CSP_ID_CARD: "Affix Passport Size Photo (35 × 45 mm)",
    DocumentType.TRAINING_CERTIFICATE: "Affix Passport Size Photo (35 × 45 mm)",
}

IMAGE_FIELDS: Dict[DocumentType, tuple] = {
    doc_type: ("photo",) for doc_type in PHOTO_MARKERS
}

# The CSP photo is sized as a passport photograph: 35mm x 45mm. The image is
# scaled to fit inside that box with its aspect ratio kept, so it is never
# larger than a passport photo whatever the source dimensions are. A source
# that is not 35:45 leaves a margin on one axis rather than being stretched.
PASSPORT_WIDTH_INCHES = 35 / 25.4    # 1.378"
PASSPORT_HEIGHT_INCHES = 45 / 25.4   # 1.772"

# TEMPORARY: until CSP photos are extracted from the CRM PDFs, a plain
# placeholder box is inserted so the rest of the pipeline can be exercised.
# Turn PHOTO_PLACEHOLDER_ALLOWED off and the photo becomes required data.
PLACEHOLDER_PHOTO = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "assets", "placeholder_photo.png")


def code_of(doc_type) -> str:
    """The stored code for a document, whether it came as an enum member or
    as a plain string from an uploaded template."""
    from app.services import document_registry as registry

    return registry.code_of(doc_type)


class TemplateError(RuntimeError):
    """Raised when a template is missing, or cannot be filled completely."""


def _same_name(a: str, b: str) -> bool:
    """Compare template filenames treating a space and an underscore alike.

    'CSP Certificate.docx' and 'CSP_Certificate.docx' are the same template.
    Saving one from Word under the other spelling is an ordinary thing to do
    and must not read as a missing template.
    """
    def key(name: str) -> str:
        return name.strip().lower().replace("_", " ").replace("  ", " ")
    return key(a) == key(b)


def template_path(doc_type: DocumentType) -> str:
    """Absolute path of the supplied template for a document type."""
    from app.services import document_registry as registry

    try:
        filename = registry.get(doc_type).filename
    except KeyError as e:
        raise TemplateError(str(e)) from e
    if not filename:
        raise TemplateError(
            f"{code_of(doc_type)} has no template file. Upload one "
            f"from the Document Templates screen."
        )

    directory = settings.document_templates_dir
    path = os.path.join(directory, filename)
    if os.path.isfile(path):
        return path

    # Fall back to a differently-spelled file in the same directory. Word's
    # '~$' lock files are skipped: they appear while a template is open for
    # editing, are not documents, and would fail to parse.
    try:
        entries = os.listdir(directory)
    except OSError:
        entries = []
    for entry in entries:
        if entry.startswith("~$") or not entry.lower().endswith(".docx"):
            continue
        if _same_name(entry, filename):
            found = os.path.join(directory, entry)
            logger.info(
                "template_service.template_path: %s resolved to '%s' "
                "(registered as '%s')", code_of(doc_type), entry,
                filename,
            )
            return found

    raise TemplateError(
        f"Template file not found for {code_of(doc_type)}: {path}. "
        f"Place the supplied '{filename}' in {directory}."
    )


def template_source(doc_type):
    """The template document itself, as something python-docx can open.

    A supplied template is a file on disk, where it has always been. An
    uploaded one lives in the database. Callers do not care which.
    """
    import io as _io

    from app.services import document_registry as registry

    try:
        spec = registry.get(doc_type)
    except KeyError as e:
        raise TemplateError(str(e)) from e

    if spec.file_data:
        return _io.BytesIO(spec.file_data)
    return template_path(doc_type)


def placeholders_for(doc_type) -> Dict[str, str]:
    """Placeholder text -> field, from configuration."""
    from app.services import document_registry as registry

    try:
        return registry.placeholder_map(doc_type)
    except KeyError as e:
        raise TemplateError(str(e)) from e


def photo_marker_for(doc_type):
    from app.services import document_registry as registry

    try:
        return registry.photo_marker(doc_type)
    except KeyError:
        return None


def required_fields(doc_type) -> List[str]:
    """Canonical field names the template needs, in template order."""
    return sorted(set(placeholders_for(doc_type).values()))


def _iter_paragraphs(container) -> Iterator[Paragraph]:
    """Every paragraph in a document part: body, tables, and text boxes."""
    for para in getattr(container, "paragraphs", []):
        yield para
    for table in getattr(container, "tables", []):
        yield from _iter_table_paragraphs(table)
    # Text boxes are not exposed by python-docx; walk the XML for them.
    element = getattr(container, "element", None)
    if element is None:
        element = getattr(container, "_element", None)
    if element is not None:
        for txbx in element.iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}txbxContent"
        ):
            for p_el in txbx.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
            ):
                yield Paragraph(p_el, container)


def _iter_table_paragraphs(table: Table) -> Iterator[Paragraph]:
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                yield para
            for nested in cell.tables:
                yield from _iter_table_paragraphs(nested)


def _all_paragraphs(doc: Document) -> Iterator[Paragraph]:
    yield from _iter_paragraphs(doc)
    for section in doc.sections:
        for part in (section.header, section.footer,
                     section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if part is not None:
                yield from _iter_paragraphs(part)


def _replace_in_paragraph(para: Paragraph, values: Dict[str, str]) -> int:
    """Replace registered placeholders in one paragraph. Returns how many.

    Works on the concatenated run text so placeholders split across runs are
    found, then writes the result back across the runs the match spans. The
    run where a placeholder starts keeps its formatting and receives the
    value; the remainder of the match is removed from the following runs.
    """
    runs = para.runs
    if not runs:
        return 0
    text = "".join(run.text for run in runs)
    if not any(q in text for q in _OPEN_QUOTES):
        return 0

    replaced = 0
    # Right to left so earlier offsets stay valid.
    for match in reversed(list(_PLACEHOLDER_RE.finditer(text))):
        name = match.group(1).strip()
        if name not in values:
            continue  # quoted prose, or a placeholder for another document
        value = values[name]
        start, end = match.span()

        offset = 0
        receiving = None
        spanned = []
        for run in runs:
            run_len = len(run.text)
            run_start, run_end = offset, offset + run_len
            offset = run_end
            if run_end <= start or run_start >= end:
                continue
            spanned.append(run)
            local_start = max(start - run_start, 0)
            local_end = min(end - run_start, run_len)
            head = run.text[:local_start]
            tail = run.text[local_end:]
            # The value goes into the first run the match touches.
            if run_start <= start and receiving is None:
                receiving = run
                run.text = head + value + tail
            else:
                run.text = head + tail

        if receiving is not None:
            _adopt_placeholder_formatting(receiving, spanned, runs)
        replaced += 1

    return replaced


# ---- the salutation before the CSP's name ------------------------------
#
# The templates carry the literal text "Shri/Ms/Mrs." so one printed form
# covers everyone. Once the CSP's gender is known the alternatives read as
# an oversight, so the one that applies replaces the lot.
#
# This is not a quoted placeholder — it is ordinary prose — so it is matched
# as literal text, and like a placeholder it is usually split across several
# runs by Word.
SALUTATION_TOKEN = "Shri/Ms/Mrs."

SALUTATIONS: Dict[str, str] = {
    "male": "Mr.",
    "female": "Mrs./Miss",
}


def salutation_for(gender: str) -> str:
    """The form of address for a gender, or '' when it is not known.

    An unknown gender leaves the template's own "Shri/Ms/Mrs." in place.
    Guessing from a name would be wrong often enough to matter, and a
    certificate addressing someone incorrectly is worse than one that keeps
    the general form.
    """
    return SALUTATIONS.get((gender or "").strip().lower(), "")


def _replace_literal(para: Paragraph, needle: str, replacement: str) -> int:
    """Replace literal text that may be split across runs.

    The run where the match starts keeps its own formatting and receives the
    replacement, so the new text inherits the size, weight and font of the
    prose it sits in rather than of whatever run happened to follow.
    """
    runs = para.runs
    if not runs:
        return 0
    text = "".join(run.text for run in runs)
    if needle not in text:
        return 0

    count = 0
    for match in reversed(list(re.finditer(re.escape(needle), text))):
        start, end = match.span()
        offset = 0
        receiving = None
        for run in runs:
            run_start, run_end = offset, offset + len(run.text)
            offset = run_end
            if run_end <= start or run_start >= end:
                continue
            local_start = max(start - run_start, 0)
            local_end = min(end - run_start, len(run.text))
            head, tail = run.text[:local_start], run.text[local_end:]
            if run_start <= start and receiving is None:
                receiving = run
                run.text = head + replacement + tail
            else:
                run.text = head + tail
        count += 1
    return count


# Run properties, in the order the WordprocessingML schema requires them.
# Word tolerates a lot, but not an rPr whose children are out of sequence.
_RPR_ORDER = ("w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:strike",
              "w:color", "w:sz", "w:szCs", "w:u", "w:vertAlign")


# Of those, the ones that decide whether the value LOOKS like the prose it
# sits in. Weight and slant are deliberate styling and are never borrowed
# from outside the placeholder; size and typeface are not.
_APPEARANCE_TAGS = ("w:rFonts", "w:sz", "w:szCs")


def _adopt_placeholder_formatting(receiving, spanned, siblings=()) -> None:
    """Complete the receiving run's formatting from the rest of the placeholder.

    A placeholder is usually split across runs — an opening quote, the field
    name, a closing quote — and Word does not give them the same formatting.
    In the Training Certificate the opening quote carries an explicit font but
    no size, while the name carries a size but no font at all.

    The value lands in the first of those runs, so whatever that run is
    missing has to be filled in. It is filled in PROPERTY BY PROPERTY, not by
    taking another run's formatting wholesale: replacing the lot fixed the
    size but discarded the explicit Calibri, and the value then fell back to
    the theme font — Aptos — printing the CSP's name in a different typeface
    from the sentence around it.

    What the receiving run already states is always kept; only the gaps are
    filled, from the first run in the same placeholder that states them.
    """
    from copy import deepcopy

    element = receiving._element
    own = element.find(qn("w:rPr"))

    def has(rpr, tag) -> bool:
        return rpr is not None and rpr.find(qn(tag)) is not None

    def donate(tag, pool):
        for run in pool:
            if run is receiving:
                continue
            donor_rpr = run._element.find(qn("w:rPr"))
            if has(donor_rpr, tag):
                return deepcopy(donor_rpr.find(qn(tag)))
        return None

    # What is missing, and which run can supply it.
    donations = {}
    for tag in _RPR_ORDER:
        if has(own, tag):
            continue
        node = donate(tag, spanned)
        if node is None and tag in _APPEARANCE_TAGS:
            # Nothing in the placeholder states it either. Fall back to the
            # prose around it: in the CSP Certificate the whole "CSP Name"
            # placeholder carries no size, while the sentence it sits in is
            # 22pt, so the name printed at the 11pt document default.
            node = donate(tag, siblings)
        if node is not None:
            donations[tag] = node

    if not donations:
        return

    merged = deepcopy(own) if own is not None else None
    if merged is None:
        merged = element.makeelement(qn("w:rPr"), {})
    for tag, node in donations.items():
        merged.append(node)

    # Put the children back into schema order.
    ordered = sorted(
        list(merged),
        key=lambda child: _RPR_ORDER.index(child.tag.split("}")[-1].join(("w:", "")))
        if child.tag.split("}")[-1].join(("w:", "")) in _RPR_ORDER else len(_RPR_ORDER),
    )
    for child in list(merged):
        merged.remove(child)
    for child in ordered:
        merged.append(child)

    if own is not None:
        element.remove(own)
    element.insert(0, merged)


PASSPORT_ASPECT = PASSPORT_WIDTH_INCHES / PASSPORT_HEIGHT_INCHES   # 0.778

# When a source is too tall it is trimmed mostly from the bottom, because the
# head belongs near the top of a passport photograph.
PASSPORT_TOP_BIAS = 0.25


def touch_up(photo_path: str) -> str:
    """A light, studio-style touch-up. Returns a new file's path.

    Confirmed 11 Oct 2026 (tracker No. 58): make the photo look
    professional WITHOUT changing the look or the face. So only the tone of
    the picture changes, the way a good photo print would:

      * colour balance — a yellow or blue cast is pulled half-way to
        neutral, never further;
      * contrast — a gentle auto-levels, so a dull grey scan reads crisp;
      * brightness — a dark photo is lifted a little; a well-lit one is
        left alone;
      * a light sharpen.

    Every pixel stays where it was: nothing is cropped, moved, stretched,
    smoothed, added or removed, so the face and its shape are exactly the
    camera's. The original file is never changed.
    """
    import tempfile

    from PIL import Image, ImageFilter, ImageOps, ImageStat

    with Image.open(photo_path) as source:
        image = source.convert("RGB")

    # 1. Colour balance: grey-world, at half strength, gains capped.
    means = ImageStat.Stat(image).mean
    grey = sum(means) / 3 or 1
    gains = [min(1.15, max(0.87, 1 + ((grey / (m or 1)) - 1) * 0.5))
             for m in means]
    bands = [band.point(lambda v, g=g: min(255, int(v * g + 0.5)))
             for band, g in zip(image.split(), gains)]
    image = Image.merge("RGB", bands)

    # 2. Contrast: auto-levels ignoring the extreme 1%, blended 60%.
    image = Image.blend(image, ImageOps.autocontrast(image, cutoff=1), 0.6)

    # 3. Brightness: only a dark photo is lifted, and only a little.
    luminance = ImageStat.Stat(image.convert("L")).mean[0]
    if luminance < 115:
        gamma = max(0.8, min(1.0, (luminance / 128) ** 0.5))
        table = [min(255, int(255 * (v / 255) ** gamma + 0.5))
                 for v in range(256)]
        image = image.point(table * 3)

    # 4. A light sharpen.
    image = image.filter(ImageFilter.UnsharpMask(radius=1.5, percent=60,
                                                 threshold=3))

    handle, destination = tempfile.mkstemp(suffix=".png", prefix="touchup_")
    os.close(handle)
    image.save(destination, "PNG", optimize=True)
    return destination


def passport_crop(photo_path: str) -> str:
    """Return a copy of the photo cropped to passport proportions (35:45).

    Confirmed rule: every photograph on every document is a passport
    photograph. Merely scaling a square scan to fit inside 35mm x 45mm
    would leave it 35mm x 35mm — fitted, but not passport size. So the
    source is cropped to the passport ratio first and then placed at the
    full 35mm x 45mm.

    The crop is centred horizontally; vertically it keeps the top, since
    that is where the head is. Returns the original path when the image is
    already the right shape.
    """
    import tempfile

    from PIL import Image

    with Image.open(photo_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        if not width or not height:
            return photo_path

        ratio = width / height
        if abs(ratio - PASSPORT_ASPECT) < 0.01:
            return photo_path

        if ratio > PASSPORT_ASPECT:
            # Too wide: trim the sides evenly.
            new_width = max(1, int(round(height * PASSPORT_ASPECT)))
            left = (width - new_width) // 2
            box = (left, 0, left + new_width, height)
        else:
            # Too tall: trim mostly from below, keeping head room.
            new_height = max(1, int(round(width / PASSPORT_ASPECT)))
            top = int((height - new_height) * PASSPORT_TOP_BIAS)
            box = (0, top, width, top + new_height)

        handle, destination = tempfile.mkstemp(suffix=".png", prefix="passport_")
        os.close(handle)
        image.crop(box).save(destination, "PNG", optimize=True)

    logger.info(
        "template_service: cropped %s from %.3f to the passport ratio %.3f",
        os.path.basename(photo_path), ratio, PASSPORT_ASPECT,
    )
    return destination


def passport_size() -> tuple:
    """Exactly 35mm x 45mm, as python-docx lengths.

    Not derived from the image: the image is cropped to this shape first,
    so every photo on every document comes out the same physical size.
    """
    return Inches(PASSPORT_WIDTH_INCHES), Inches(PASSPORT_HEIGHT_INCHES)


# The containers a photo frame is built from. A template may use any of
# them, so all three are handled rather than only the one the ID Card uses.
_VML_TEXTBOX_TAG = "{urn:schemas-microsoft-com:vml}textbox"
_BODYPR_TAGS = (
    "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}bodyPr",
    "{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr",
)


def _zero_cell_margins(tc) -> None:
    """Remove a table cell's inner padding, in place."""
    from docx.oxml import OxmlElement

    tc_pr = tc.find(qn("w:tcPr"))
    if tc_pr is None:
        tc_pr = OxmlElement("w:tcPr")
        tc.insert(0, tc_pr)
    margins = tc_pr.find(qn("w:tcMar"))
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side in ("top", "left", "bottom", "right"):
        node = margins.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            margins.append(node)
        node.set(qn("w:w"), "0")
        node.set(qn("w:type"), "dxa")


# LibreOffice reserves this much on each side of a VML text box, on top of
# whatever `inset` asks for. Measured, not guessed: with inset="0,0,0,0" a
# left-aligned image starts 3.21mm inside the frame and a right-aligned one
# ends 3.19mm inside it; with inset="10mm,..." the gap becomes 13.21mm, so
# the amount is additive and cannot be turned off. Negative insets are
# clamped to zero, so the only way to give a 35mm photograph 35mm of room
# is to make its frame wider by this much on each side.
_LIBREOFFICE_SIDE_INSET_PT = 9.1          # 3.21mm

# The same LibreOffice reserve applies inside a TABLE CELL photo box (the
# design used since 11 Oct 2026): a 35 mm photo in a 35 mm cell started
# 3.19 mm in from the left border and ran 3.2 mm past the right one — the
# "gap on the left" the user saw on 12 Oct (tracker No. 76). Cell margins,
# border spacing, alignment and indents were all already zero; the reserve
# cannot be turned off, so the photo is pulled left by exactly that much.
# Measured: gap 3.19 mm -> 0.00 mm on the ID Card and Training Certificate.
_LIBREOFFICE_CELL_OFFSET_TWIPS = 181       # 3.19mm


def _pull_left_in_cell(para) -> None:
    """Start the photo exactly at the cell's left border (see above)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Twips

    fmt = para.paragraph_format
    fmt.left_indent = Twips(-_LIBREOFFICE_CELL_OFFSET_TWIPS)
    fmt.right_indent = Twips(0)
    fmt.first_line_indent = Twips(0)
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT


def _style_properties(shape) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (shape.get("style") or "").split(";"):
        if ":" in part:
            key, _, value = part.partition(":")
            out[key.strip()] = value.strip()
    return out


def _widen_vml_frame(shape) -> None:
    """Grow a photo frame sideways so the photograph fits inside it.

    The frame is drawn exactly 35mm wide — the width of the photograph —
    which leaves nothing for the padding LibreOffice insists on, so the
    image is pushed sideways and hangs off the edge of the card. Widening
    the frame by that padding on each side and moving it left by the same
    amount puts the photograph back on exactly the rectangle the template
    drew for it.

    The frame is then left unpainted: a photograph covers it completely, so
    its white fill and outline would only show as a border in the wrong
    place. An unfilled template, with no photograph, keeps both.

    Sizes written in anything but points are left alone rather than
    guessed at.
    """
    if shape is None:
        return
    style = _style_properties(shape)
    width, margin = style.get("width", ""), style.get("margin-left", "")
    if not width.endswith("pt") or not margin.endswith("pt"):
        return
    try:
        width_pt = float(width[:-2])
        margin_pt = float(margin[:-2])
    except ValueError:
        return

    style["width"] = f"{width_pt + 2 * _LIBREOFFICE_SIDE_INSET_PT:g}pt"
    style["margin-left"] = f"{margin_pt - _LIBREOFFICE_SIDE_INSET_PT:g}pt"
    shape.set("style", ";".join(f"{k}:{v}" for k, v in style.items()))

    shape.set("filled", "f")
    shape.set("stroked", "f")
    if shape.get("fillcolor"):
        del shape.attrib["fillcolor"]


def _clear_frame_padding(para: Paragraph) -> None:
    """Make room for a photo that is exactly as large as its frame.

    A photo frame is drawn at 35mm x 45mm and the photograph is placed at
    35mm x 45mm, so anything sitting between the two pushes the image down
    and out of the frame, where it is silently clipped.

    On the ID Card that was 50pt of space before the caption — which is what
    centred the words 'Affix Passport Size Photo' inside the empty box, and
    what cut the face off at the eyes once a real photograph replaced them.
    A text box's inset and a table cell's margins do the same thing in the
    other direction, so all three are cleared.

    Only the paragraph the photo goes into and the frame immediately around
    it are touched. Nothing else in the template moves.
    """
    fmt = para.paragraph_format
    fmt.space_before = 0
    fmt.space_after = 0
    fmt.line_spacing = 1.0

    element = para._p
    while element is not None:
        if element.tag == _VML_TEXTBOX_TAG:
            element.set("inset", "0,0,0,0")
            _widen_vml_frame(element.getparent())
        elif element.tag in _BODYPR_TAGS:
            for side in ("lIns", "tIns", "rIns", "bIns"):
                element.set(side, "0")
        elif element.tag == qn("w:tc"):
            _zero_cell_margins(element)
        element = element.getparent()


def _insert_photo(doc: Document, doc_type: DocumentType, photo_path: str) -> bool:
    """Replace the template's photo marker paragraph with the image.

    Returns True when the marker was found and the image inserted.
    """
    marker = photo_marker_for(doc_type)
    if not marker:
        return False
    width, height = passport_size()
    # A checked AI studio portrait when there is one (No. 61); otherwise the
    # CSP's own photo with the light touch-up.
    from app.services import photo_portrait, studio_photo
    portrait = photo_portrait.studio_portrait(photo_path)
    if portrait is None and settings.photo_white_background:
        # White background and passport framing, real face (No. 67). It is
        # already touched up, so it is treated like a finished portrait.
        portrait = studio_photo.make(photo_path)
    cropped = passport_crop(portrait or photo_path)
    if portrait and cropped == portrait:
        # Never hand the cached portrait to the clean-up below.
        import shutil, tempfile
        handle, copy = tempfile.mkstemp(suffix=".png", prefix="portrait_")
        os.close(handle)
        shutil.copyfile(portrait, copy)
        cropped = copy
    if settings.photo_touch_up and not portrait:
        finished = touch_up(cropped)
        if cropped != photo_path:
            try:
                os.remove(cropped)
            except OSError:
                pass
        cropped = finished
    try:
        para = _photo_marker_paragraph(doc, marker)
        if para is None:
            return False
        for run in para.runs[1:]:
            run.text = ""
        target = para.runs[0]
        target.text = ""
        _clear_frame_padding(para)
        if para._p.getparent().tag == qn("w:tc"):
            _pull_left_in_cell(para)
        target.add_picture(cropped, width=width, height=height)
        return True
    finally:
        if cropped != photo_path:
            try:
                os.remove(cropped)
            except OSError:
                pass


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def _photo_marker_paragraph(doc: Document, marker: str, remove_rest=True):
    """The paragraph the photo goes into, or None.

    Either one paragraph whose text is the marker, or a table cell whose
    paragraphs together read as the marker (the 35 x 45 mm cell used since
    11 Oct 2026). For a cell, the first line receives the photo and the
    other lines are removed, so nothing else takes up room in the cell.
    """
    wanted = _squash(marker)
    for para in _all_paragraphs(doc):
        if para.runs and _squash("".join(r.text for r in para.runs)) == wanted:
            return para

    for part in _document_parts(doc):
        element = getattr(part, "element", None)
        if element is None:
            element = getattr(part, "_element", None)
        if element is None:
            continue
        for tc in element.iter(qn("w:tc")):
            paras = [Paragraph(p, part) for p in tc.findall(qn("w:p"))]
            if _squash(" ".join(p.text for p in paras)) != wanted:
                continue
            lines = [p for p in paras if p.text.strip()]
            first = lines[0]
            if remove_rest:
                for p in paras:
                    if p is not first:
                        p._p.getparent().remove(p._p)
            return first
    return None


def _document_parts(doc: Document):
    yield doc
    for section in doc.sections:
        for part in (section.header, section.footer,
                     section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if part is not None:
                yield part


def has_photo_marker(path: str, doc_type) -> bool:
    """True when a generated file still shows the unreplaced photo marker."""
    marker = photo_marker_for(doc_type)
    if not marker:
        return False
    return _photo_marker_paragraph(Document(path), marker,
                                   remove_rest=False) is not None


def count_images(path: str) -> int:
    """Number of image parts in a DOCX package."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        # A folder entry ("word/media/") is not an image; Word sometimes
        # writes one when a template is re-saved.
        return len([n for n in z.namelist()
                    if n.startswith("word/media/") and not n.endswith("/")])


def _trim_repeated_address(values: Dict[str, str],
                           placeholders: Dict[str, str]) -> Dict[str, str]:
    """Drop the district, state and pincode from an address that repeats them.

    Only for a template that already prints the district or the state in
    their own right. The CSP Certificate does, and read:

        Samvapur belghat gorakhpur up 273404, DIST- Gorakhpur, Uttar Pradesh

    The ID Card and the BCP print the address and nothing else, so for
    them the tail is the only place the district and pincode appear and
    trimming it would lose them. Deciding from the template's own
    placeholders rather than from the document's name means an uploaded
    template gets the same treatment without being named here.
    """
    fields = set(placeholders.values())
    if "address" not in fields or not (fields & {"district", "state"}):
        return values

    from app.services.csp_mapping import address_without_district_state

    trimmed = address_without_district_state(
        values.get("address", ""),
        district=values.get("district", ""),
        state=values.get("state", ""),
    )
    if trimmed == values.get("address", ""):
        return values

    logger.info("template_service: trimmed the address printed beside its "
                "own district and state")
    return {**values, "address": trimmed}


def values_for(doc_type, values: Dict[str, str]) -> Dict[str, str]:
    """The values as this particular template will print them.

    Anything that depends on which template is being filled belongs here,
    so that the filler and the validator cannot disagree. They did once:
    the certificate's address was trimmed on the way in but not on the way
    out, and validation then looked for text the document was never going
    to contain.
    """
    return _trim_repeated_address(values, placeholders_for(doc_type))


def fill_template(
    doc_type: DocumentType,
    values: Dict[str, str],
    output_path: str,
    template_file: Optional[str] = None,
    photo_path: Optional[str] = None,
) -> str:
    """Fill a supplied template and save the result.

    Args:
        doc_type: Which document to produce.
        values: Canonical field name → value. Every field in
            required_fields(doc_type) must be present and non-empty.
        output_path: Where to write the generated DOCX.
        template_file: Override the template path (tests only).

    Returns:
        output_path.

    Raises:
        TemplateError: template missing, a required value missing/empty, or a
            registered placeholder still present after filling.
    """
    source = template_file or template_source(doc_type)
    placeholders = placeholders_for(doc_type)

    missing = sorted(
        field for field in set(placeholders.values())
        if not str(values.get(field, "")).strip()
    )
    if missing:
        raise TemplateError(
            f"Cannot fill {code_of(doc_type)}: no value for "
            f"{', '.join(missing)}."
        )

    values = values_for(doc_type, values)

    # Placeholder text → the value it is replaced with.
    by_placeholder = {
        text: str(values[field]).strip() for text, field in placeholders.items()
    }

    doc = Document(source)

    # Address the CSP by the form that applies to them. Done before the
    # placeholders so the name that follows is untouched by it.
    salutation = salutation_for(values.get("gender", ""))
    if salutation:
        for para in _all_paragraphs(doc):
            _replace_literal(para, SALUTATION_TOKEN, salutation)

    # "bearing KO/Sub-KO Code ..." becomes "KO Code" or "Sub-KO Code" by the
    # length of the CSP code (No. 57). An unknown length keeps the general
    # wording rather than guessing.
    from app.services import ko_level
    level_label = ko_level.label_for(values.get("csp_code", ""))
    if level_label:
        for para in _all_paragraphs(doc):
            _replace_literal(para, ko_level.TOKEN, level_label)

    replaced = 0
    for para in _all_paragraphs(doc):
        replaced += _replace_in_paragraph(para, by_placeholder)

    marker = photo_marker_for(doc_type)
    if marker:
        if not photo_path or not os.path.isfile(photo_path):
            raise TemplateError(
                f"Cannot fill {code_of(doc_type)}: photo image not found "
                f"({photo_path or 'no path given'})."
            )
        if not _insert_photo(doc, doc_type, photo_path):
            raise TemplateError(
                f"{code_of(doc_type)}: photo marker {marker!r} not found in "
                f"the template."
            )

    leftover = _find_leftover_placeholders(doc, set(placeholders))
    if leftover:
        raise TemplateError(
            f"{code_of(doc_type)}: placeholder(s) still present after filling: "
            f"{', '.join(sorted(leftover))}. The template may have changed."
        )
    if replaced == 0:
        raise TemplateError(
            f"{code_of(doc_type)}: no placeholders were found in this template."
        )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc.save(output_path)
    logger.info(
        "template_service.fill_template: %s → %s (%d placeholder(s) replaced)",
        code_of(doc_type), output_path, replaced,
    )
    return output_path


def find_leftover_placeholders_in_file(path: str, doc_type: DocumentType) -> set:
    """Registered placeholders still present in a generated file."""
    return _find_leftover_placeholders(
        Document(path), set(placeholders_for(doc_type)))


def _find_leftover_placeholders(doc: Document, known: set) -> set:
    """Registered placeholders still present in the document."""
    leftover = set()
    for para in _all_paragraphs(doc):
        for match in _PLACEHOLDER_RE.finditer("".join(r.text for r in para.runs)):
            name = match.group(1).strip()
            if name in known:
                leftover.add(name)
    return leftover
