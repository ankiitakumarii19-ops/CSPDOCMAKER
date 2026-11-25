"""
CSP DocMaker — which signature a document carries, by rule (No. 247)

A workspace uploads signature pictures and writes rules:

    on <this document | every document>,
    when <column> of the CSP is one of <values>   (or: every CSP),
    print <signature>.

The first active rule that matches, in the order the admin set, wins. With
no rule matching, a document is made exactly as before (its own signature;
for the supplied four, the LHO's picture from the server folder,
lho_signature.py).

Where the signature sits in a template is document_templates.signature_spot:

    "picture:<sha256>"  that picture inside the file is replaced, resized to
                        the same box so the page does not move;
    "text:<paragraph>"  that paragraph (e.g. "Authorised signatory") becomes
                        the signature picture, at most 5 x 2.5 cm.
    NULL                a supplied document: its signature picture (the one
                        identical to templates/signatures/default.png).

A document whose spot is a paragraph has no signature of its own, so a CSP no
rule matches is refused (the document would otherwise print the paragraph's
text) — the message says to add an "every other CSP" rule.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

# The CSP's columns a rule may look at: key on csp_records -> what it is
# called on screen.
COLUMNS: List[Tuple[str, str]] = [
    ("lho", "LHO"),
    ("state", "State"),
    ("district", "District"),
    ("ao", "AO"),
    ("rbo_name", "RBO"),
    ("branch_name", "Branch name"),
    ("branch_code", "Branch code"),
    ("dc", "DC"),
    ("circle_head", "Circle head"),
    ("rm_name", "RM"),
    ("asm_name", "ASM"),
    ("csp_code", "CSP code"),
    ("csp_id", "CSP ID"),
    ("gender", "Gender"),
    ("status", "Status"),
]
COLUMN_KEYS = {key for key, _ in COLUMNS}
LABELS = dict(COLUMNS)

MAX_BYTES = 2 * 1024 * 1024
MAX_SIZE = (1500, 800)
CACHE_SECONDS = 30
# A signature put where a paragraph was: at most this big, shape kept.
TEXT_SPOT_BOX_EMU = (int(5.0 * 360000), int(2.5 * 360000))


class SignatureError(ValueError):
    """A picture or rule that cannot be used; the message says why."""


@dataclass
class Rule:
    id: str
    document_code: Optional[str]
    column: str
    values: List[str]
    signature_id: str
    signature_name: str
    active: bool = True
    image: Optional[bytes] = None
    width: int = 0
    height: int = 0


def norm(value) -> str:
    """'  PATNA ', 'Patna' and 'patna' are the same value."""
    return " ".join(str(value or "").split()).lower()


def record_of(csp) -> Dict[str, str]:
    """The CSP's values a rule may look at."""
    return {key: str(getattr(csp, key, None) or "") for key in COLUMN_KEYS}


def check_picture(data: bytes) -> Tuple[bytes, int, int]:
    """The PNG kept for an uploaded signature: PNG / JPEG / WEBP only (an
    SVG can carry script), at most 2 MB in, turned upright, at most
    1500 x 800, transparency kept."""
    if not data:
        raise SignatureError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise SignatureError("The picture is larger than 2 MB. Please use a smaller one.")
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise SignatureError("Please use a PNG, JPEG or WEBP picture.")
            image = ImageOps.exif_transpose(image).convert("RGBA")
            image.thumbnail(MAX_SIZE, Image.LANCZOS)
            out = io.BytesIO()
            image.save(out, "PNG", optimize=True)
            return out.getvalue(), image.width, image.height
    except SignatureError:
        raise
    except (UnidentifiedImageError, OSError) as e:
        raise SignatureError("That file is not a picture that can be read. "
                             "Please use a PNG, JPEG or WEBP.") from e


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def first_match(rules: List[Rule], code: str,
                record: Dict[str, str]) -> Optional[Rule]:
    """The rule that decides this CSP's signature on this document."""
    for rule in rules:
        if not rule.active:
            continue
        if rule.document_code and rule.document_code != code:
            continue
        if not rule.column:
            return rule
        wanted = {norm(v) for v in rule.values if norm(v)}
        if norm(record.get(rule.column)) in wanted:
            return rule
    return None


def describe(rule: Rule, document_names: Optional[Dict[str, str]] = None) -> str:
    """The rule in words: 'Appointment Letter, LHO is Patna → Patna sign'."""
    doc = ((document_names or {}).get(rule.document_code, rule.document_code)
           if rule.document_code else "Every document")
    if not rule.column:
        when = "every other CSP"
    else:
        when = f"{LABELS.get(rule.column, rule.column)} is " + " or ".join(rule.values)
    return f"{doc}, {when} → {rule.signature_name}"


# ---- reading the rules (generation runs in a worker, without async) ------

_lock = threading.Lock()
_cache: Dict[Optional[uuid.UUID], Tuple[float, List[Rule]]] = {}


def forget(workspace_id=None) -> None:
    with _lock:
        if workspace_id is None:
            _cache.clear()
        else:
            _cache.pop(uuid.UUID(str(workspace_id)), None)


def _read() -> List[Rule]:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.signature import Signature, SignatureRule

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(SignatureRule, Signature)
                .join(Signature, Signature.id == SignatureRule.signature_id)
                .where(SignatureRule.active.is_(True))
                .order_by(SignatureRule.position, SignatureRule.created_at)
            ).all()
            return [Rule(id=str(r.id), document_code=r.document_code,
                         column=r.column_name or "",
                         values=list(r.match_values or []),
                         signature_id=str(s.id), signature_name=s.name,
                         active=r.active, image=bytes(s.image),
                         width=s.width, height=s.height)
                    for r, s in rows]
    finally:
        engine.dispose()


def rules() -> List[Rule]:
    """This workspace's active rules, through a 30-second cache.

    A failure to read is NOT treated as "no rules": that would quietly print
    the wrong signature. It raises, and the document job fails and is tried
    again.
    """
    ws = current_workspace_id()
    key = uuid.UUID(str(ws)) if ws else None
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    loaded = _read()
    with _lock:
        _cache[key] = (time.monotonic(), loaded)
    return loaded


# ---- putting the signature in ---------------------------------------------

def default_spot() -> Optional[str]:
    """A supplied document's signature: its picture equal to default.png."""
    from app.services import lho_signature
    path = lho_signature.default_path()
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return "picture:" + sha256(f.read())


def spot_for(code: str) -> Optional[str]:
    from app.services import document_registry
    try:
        spec = document_registry.get(code)
    except KeyError:
        return None
    if spec.signature_spot:
        return spec.signature_spot
    return default_spot() if spec.is_builtin else None


def pictures_in(doc) -> Dict[str, dict]:
    """Every picture inside a document: sha256 -> {blob, width, height,
    content_type, count}."""
    from app.services import lho_signature
    from docx.oxml.ns import qn
    from PIL import Image

    found: Dict[str, dict] = {}
    for part in lho_signature._story_parts(doc):
        used = {blip.get(qn("r:embed")) for blip in part.element.iter(qn("a:blip"))}
        for rid, rel in part.rels.items():
            if rel.is_external or "image" not in rel.reltype or rid not in used:
                continue
            blob = rel.target_part.blob
            key = sha256(blob)
            if key in found:
                found[key]["count"] += 1
                continue
            try:
                with Image.open(io.BytesIO(blob)) as im:
                    size = im.size
            except Exception:  # an EMF / WMF picture Pillow cannot measure
                size = (0, 0)
            found[key] = {"blob": blob, "width": size[0], "height": size[1],
                          "content_type": getattr(rel.target_part, "content_type",
                                                  "application/octet-stream"),
                          "count": 1}
    return found


def _replace_picture(doc, checksum: str, rule: Rule) -> int:
    from app.services import lho_signature
    from docx.oxml.ns import qn

    swapped = 0
    for part in lho_signature._story_parts(doc):
        old_ids = [rid for rid, rel in part.rels.items()
                   if not rel.is_external and "image" in rel.reltype
                   and sha256(rel.target_part.blob) == checksum]
        if not old_ids:
            continue
        new_id, _ = part.get_or_add_image(io.BytesIO(rule.image))
        for blip in part.element.iter(qn("a:blip")):
            if blip.get(qn("r:embed")) in old_ids:
                blip.set(qn("r:embed"), new_id)
                lho_signature._resize_drawing(blip, rule.width, rule.height)
                swapped += 1
        for rid in old_ids:
            if rid != new_id:
                part.drop_rel(rid)
    return swapped


def _replace_paragraph(doc, marker: str, rule: Rule) -> bool:
    from docx.shared import Emu

    from app.services import lho_signature
    from app.services import template_service as ts

    para = ts._photo_marker_paragraph(doc, marker)
    if para is None:
        return False
    runs = para.runs
    if not runs:
        return False
    for run in runs[1:]:
        run.text = ""
    runs[0].text = ""
    cx, cy = lho_signature._fit(*TEXT_SPOT_BOX_EMU, rule.width or 1, rule.height or 1)
    runs[0].add_picture(io.BytesIO(rule.image), width=Emu(cx), height=Emu(cy))
    return True


def apply(doc, code: str, record: Optional[Dict[str, str]]) -> Optional[str]:
    """Put the rule-chosen signature in. Returns the signature's name, or
    None when no rule decides it (the document is then made as before).

    Raises template_service.TemplateError when a rule chose a signature but
    it cannot be put where the template says, or when the template's spot is
    a paragraph and no rule covers this CSP — a wrong or missing signature
    on an official document is worse than a document made later.
    """
    if record is None:
        return None
    from app.services.template_service import TemplateError

    spot = spot_for(code)
    hit = first_match(rules(), code, record)
    if hit is None:
        if spot and spot.startswith("text:"):
            raise TemplateError(
                f"{code}: no signature rule covers this CSP, and the template's "
                f"signature place is a line of text ({spot[5:]!r}). Add a rule "
                f"for every other CSP in Document templates → Signatures.")
        return None
    if not spot:
        if hit.document_code:
            raise TemplateError(
                f"{code}: a signature rule chose '{hit.signature_name}' but "
                f"nobody has said where this document's signature goes — "
                f"Document templates → {code} → Signature.")
        logger.warning("signature_rules.apply: %s has no signature place; the "
                       "every-document rule (%s) does not apply to it.",
                       code, hit.signature_name)
        return None

    if spot.startswith("picture:"):
        placed = _replace_picture(doc, spot[len("picture:"):], hit) > 0
    elif spot.startswith("text:"):
        placed = _replace_paragraph(doc, spot[len("text:"):], hit)
    else:
        placed = False
    if not placed:
        raise TemplateError(
            f"{code}: the signature place chosen for this document is not in "
            f"its current file, so '{hit.signature_name}' cannot be put in. "
            f"Choose it again in Document templates → {code} → Signature.")
    logger.info("signature_rules.apply: %s ← %s (rule %s)", code,
                hit.signature_name, hit.id)
    return hit.signature_name
