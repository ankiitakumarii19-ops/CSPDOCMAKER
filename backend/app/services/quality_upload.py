"""
CSP DocMaker — "Upload document" on Data quality (No. 171)

A PDF, Word (.docx) or text (.txt / .md) file is read into lines and split
into the four sections by its headings — fixed rules, no AI, no OCR (D1,
D11): a scanned PDF has no text to read and says so.

  Heading → section
    "Context", "What the app reads", "Data sources"        → context
    "Harness", "How the app checks itself", "Self-checks"  → harness
    "Guardrails", "Rules"                                  → guardrails
    "Knowledge Base", "FAQ", "Questions and answers"       → knowledge

  Inside a section
    context / harness  "<name>: <text>" lines, matched to the existing rows
                       by name (a new sheet or check cannot be added in
                       words — the code would not read or run it). A
                       following "How: …" line sets a check's "how".
    guardrails         each line or list item is one rule;
                       "<rule>: <detail>" splits the two.
    knowledge          "Q: … / A: …" pairs, or a line ending in "?" followed
                       by its answer. A sub-heading becomes the category.

Nothing is saved here: the result is shown for review, and the page saves
what the person keeps. Lines that fit nowhere come back as "not placed".
"""

import io
import logging
import re
from typing import List, Optional, Tuple

from app.services import quality_texts

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
KINDS = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "txt"}

SECTIONS = [
    ("context", re.compile(r"\bcontext\b|what the app reads|data sources?", re.I)),
    ("harness", re.compile(r"\bharness\b|how the app checks|self[- ]?checks?", re.I)),
    ("guardrails", re.compile(r"guard ?rails?|\brules\b", re.I)),
    ("knowledge", re.compile(r"knowledge|\bfaqs?\b|questions?\s*(and|&)\s*answers?|\bq\s*&\s*a\b", re.I)),
]
_BULLET = re.compile(r"^\s*(?:[-*•▪◦·]|\d{1,3}[.)]|[a-z][.)])\s+", re.I)
_SPLIT = re.compile(r"\s*(?::|\s[—–-]\s)\s*")
_Q = re.compile(r"^(?:q(?:uestion)?\s*[:.)-])\s*", re.I)
_A = re.compile(r"^(?:a(?:nswer)?\s*[:.)-])\s*", re.I)
_HOW = re.compile(r"^how\s*:\s*", re.I)


class UploadError(ValueError):
    """The file cannot be read, with a message fit to show."""


# ---- reading the file ------------------------------------------------------

def kind_of(filename: str) -> str:
    name = (filename or "").lower()
    for ext, kind in KINDS.items():
        if name.endswith(ext):
            return kind
    raise UploadError("Please upload a PDF, Word (.docx) or text (.txt) file.")


def read_lines(filename: str, data: bytes) -> List[Tuple[str, int]]:
    """[(text, heading level)] — level 0 = ordinary line, 1..6 = heading."""
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadError("The file is larger than 5 MB.")
    kind = kind_of(filename)
    try:
        if kind == "pdf":
            lines = _pdf(data)
        elif kind == "docx":
            lines = _docx(data)
        else:
            lines = _txt(data)
    except UploadError:
        raise
    except Exception as e:
        logger.warning("quality_upload.read_lines: %s could not be read: "
                       "%s: %s", filename, type(e).__name__, e)
        raise UploadError(f"The file could not be read ({type(e).__name__}). "
                          f"Is it a real {kind.upper()} file?")
    lines = [(" ".join(t.split()), lvl) for t, lvl in lines]
    lines = [(t, lvl) for t, lvl in lines if t]
    if not lines:
        raise UploadError("No text was found in the file. A scanned PDF "
                          "(a picture of a page) cannot be read.")
    return lines


def _pdf(data: bytes) -> List[Tuple[str, int]]:
    import fitz  # PyMuPDF

    out = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            out += [(line, 0) for line in page.get_text("text").splitlines()]
    return out


def _docx(data: bytes) -> List[Tuple[str, int]]:
    from docx import Document

    doc = Document(io.BytesIO(data))
    out = []
    for p in doc.paragraphs:
        style = (p.style.name if p.style is not None else "") or ""
        m = re.match(r"heading\s*(\d)", style, re.I)
        level = int(m.group(1)) if m else (1 if style.lower() == "title" else 0)
        out.append((p.text, level))
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if len(cells) >= 2:
                out.append((f"{cells[0]}: {' — '.join(cells[1:])}", 0))
            elif cells:
                out.append((cells[0], 0))
    return out


def _txt(data: bytes) -> List[Tuple[str, int]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    out = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        out.append((m.group(2), len(m.group(1))) if m else (line, 0))
    return out


# ---- splitting it into sections ------------------------------------------

def _section_of(text: str) -> Optional[str]:
    for name, pattern in SECTIONS:
        if pattern.search(text):
            return name
    return None


def _is_heading(text: str, level: int) -> bool:
    if level:
        return True
    # In a PDF or plain text a heading is a short line naming a section.
    bare = text.strip().rstrip(":").strip()
    return (len(bare.split()) <= 6 and not bare.endswith((".", "?"))
            and _section_of(bare) is not None and not _BULLET.match(text))


def _strip_bullet(text: str) -> str:
    return _BULLET.sub("", text).strip()


def _pair(text: str) -> Tuple[str, str]:
    parts = _SPLIT.split(_strip_bullet(text), maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (parts[0].strip(), "")


def split(lines: List[Tuple[str, int]], context_rows: List[dict],
          harness_rows: List[dict]) -> dict:
    """What the file says for each section, ready for review."""
    found = {"context": {}, "harness": {}, "guardrails": [], "knowledge": [],
             "unplaced": []}
    section, category = None, "General"
    any_heading = False
    question, answer = None, []

    def close_question():
        nonlocal question, answer
        if question:
            text = " ".join(answer).strip()
            if text:
                found["knowledge"].append({"question": question[:300],
                                           "answer": text[:4000],
                                           "category": category[:100]})
            else:
                found["unplaced"].append(question)
        question, answer = None, []

    last_check = None
    for text, level in lines:
        named = _section_of(text) if _is_heading(text, level) else None
        if level == 0 and named == section:
            named = None    # a short line in its own section is content
        if named is not None or (level and section == "knowledge"):
            if named and (level <= 2 or section is None):
                close_question()
                section, category, last_check = named, "General", None
                any_heading = True
                continue
            if section == "knowledge":
                # A sub-heading inside the Knowledge Base: its category.
                close_question()
                category = text.strip().rstrip(":")
                continue

        target = section
        if target is None:
            # No heading yet: place the line by its shape.
            plain = _strip_bullet(text)
            if _Q.match(plain) or plain.endswith("?") or (question and not _is_heading(text, level)):
                target = "knowledge"
            elif re.match(r"^(never|always|must|do not|don't|no )", plain, re.I):
                target = "guardrails"
            else:
                found["unplaced"].append(text)
                continue

        if target == "knowledge":
            plain = _strip_bullet(text)
            if _Q.match(plain):
                close_question()
                question = _Q.sub("", plain)
            elif _A.match(plain) and question:
                answer.append(_A.sub("", plain))
            elif plain.endswith("?") and not answer:
                if question:
                    question = f"{question} {plain}"
                else:
                    question = plain
            elif plain.endswith("?"):
                close_question()
                question = plain
            elif question:
                answer.append(plain)
            else:
                found["unplaced"].append(text)
        elif target == "guardrails":
            title, detail = _pair(text)
            if len(title) > 120:            # a sentence, not "title: detail"
                title, detail = _strip_bullet(text), ""
            found["guardrails"].append({"title": title[:200], "detail": detail[:1000]})
        elif target == "harness":
            plain = _strip_bullet(text)
            if _HOW.match(plain) and last_check:
                found["harness"][last_check]["how"] = _HOW.sub("", plain)[:1000]
                continue
            name, words = _pair(text)
            row = quality_texts.find_row(name, harness_rows, "name") if words else None
            if row is None:
                found["unplaced"].append(text)
                continue
            last_check = row["key"]
            found["harness"][row["key"]] = {"key": row["key"], "name": row["name"],
                                            "watches": words[:1000], "how": row["how"]}
        elif target == "context":
            name, words = _pair(text)
            row = quality_texts.find_row(name, context_rows, "label") if words else None
            if row is None:
                found["unplaced"].append(text)
                continue
            found["context"][row["key"]] = {"key": row["key"], "label": row["label"],
                                            "used_for": words[:1000]}
    close_question()

    return {
        "context": list(found["context"].values()),
        "harness": list(found["harness"].values()),
        "guardrails": found["guardrails"][:quality_texts.MAX_GUARDRAILS],
        "knowledge": found["knowledge"],
        "unplaced": found["unplaced"][:200],
        "headings_found": any_heading,
    }
