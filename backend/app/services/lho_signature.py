"""The authorised signature and stamp printed on each LHO's documents.

All four supplied templates carry one signature-and-stamp picture. Since
No. 242 (25 Nov 2026) that picture is the Gurugram stamp, and it is the
signature for every LHO that has no picture of its own.

An LHO gets its own signature by placing a picture in the signatures folder
named after it — `patna.png`, `patna.jpg` or `patna.jpeg` (case and spaces
do not matter: "Patna", " PATNA " and "patna" all find `patna.*`). When a
document is made for a CSP of that LHO, the template's signature picture is
replaced by the LHO's own, resized to fit the same box so the page layout
does not move.

The template's signature is recognised by being byte-for-byte the same as
`default.png` in the signatures folder. A template uploaded later with some
other signature is left alone, and the mismatch is logged loudly so a
missing LHO signature is never silent.
"""

from __future__ import annotations

import io
import logging
import os
import re
from typing import Optional

from docx.oxml.ns import qn
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_NAME = "default.png"
_EXTENSIONS = (".png", ".jpg", ".jpeg")


def signatures_dir() -> str:
    return get_settings().signatures_dir


def default_path() -> str:
    return os.path.join(signatures_dir(), DEFAULT_NAME)


def _slug(lho: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (lho or "").strip().lower()).strip("_")


def own_signature_path(lho: Optional[str]) -> Optional[str]:
    """The LHO's own signature picture, or None when it uses the default."""
    slug = _slug(lho or "")
    if not slug or slug == "default":
        return None
    for ext in _EXTENSIONS:
        path = os.path.join(signatures_dir(), slug + ext)
        if os.path.isfile(path):
            return path
    return None


def signature_for(lho: Optional[str]) -> str:
    """Path of the signature printed on this LHO's documents."""
    return own_signature_path(lho) or default_path()


def _fit(box_cx: int, box_cy: int, width_px: int, height_px: int):
    """The largest size with the picture's shape that fits inside the box."""
    aspect = width_px / height_px
    if box_cx / box_cy > aspect:
        return int(box_cy * aspect), box_cy
    return box_cx, int(box_cx / aspect)


def _resize_drawing(blip, width_px: int, height_px: int) -> None:
    """Fit the drawing that holds `blip` to the new picture's shape."""
    node = blip
    while node is not None and node.tag not in (qn("wp:inline"), qn("wp:anchor")):
        node = node.getparent()
    if node is None:
        return
    extent = node.find(qn("wp:extent"))
    if extent is None:
        return
    cx, cy = _fit(int(extent.get("cx")), int(extent.get("cy")), width_px, height_px)
    extent.set("cx", str(cx))
    extent.set("cy", str(cy))
    for ext in node.iter(qn("a:ext")):
        # a:ext also appears inside a:extLst with a uri and no size; only
        # the picture's own size (cx/cy) is touched.
        if ext.get("cx") is not None:
            ext.set("cx", str(cx))
            ext.set("cy", str(cy))


def _story_parts(doc):
    """Every existing part that can hold a picture: body, headers, footers.

    Walked from the package rather than through `section.header`, which
    would create a header for a section that has none.
    """
    seen = set()
    for part in doc.part.package.iter_parts():
        if id(part) in seen or not hasattr(part, "get_or_add_image"):
            continue
        seen.add(id(part))
        yield part


def apply(doc, lho: Optional[str]) -> Optional[str]:
    """Put this LHO's own signature in place of the default one.

    Returns the path of the signature now printed, or None when the
    document keeps the default.
    """
    own = own_signature_path(lho)
    if own is None:
        return None
    # No. 247: the pictures in this folder are Eko's (its signatory and
    # stamps). Another workspace chooses its own on Document templates →
    # Signatures; these are never put on its documents.
    from app.workspace_context import current_workspace_id
    from app.services.workspace_settings import EKO_WORKSPACE
    ws = current_workspace_id()
    if ws is not None and str(ws) != str(EKO_WORKSPACE):
        return None

    default = default_path()
    if not os.path.isfile(default):
        raise FileNotFoundError(
            f"The default signature is missing ({default}). It is what tells "
            f"the template's signature apart from its other pictures, so "
            f"{lho}'s own signature cannot be put in.")
    with open(default, "rb") as f:
        default_blob = f.read()
    with open(own, "rb") as f:
        own_blob = f.read()
    with Image.open(io.BytesIO(own_blob)) as im:
        width_px, height_px = im.size

    swapped = 0
    for part in _story_parts(doc):
        old_ids = [rid for rid, rel in part.rels.items()
                   if not rel.is_external and "image" in rel.reltype
                   and rel.target_part.blob == default_blob]
        if not old_ids:
            continue
        new_id, _ = part.get_or_add_image(io.BytesIO(own_blob))
        for blip in part.element.iter(qn("a:blip")):
            if blip.get(qn("r:embed")) in old_ids:
                blip.set(qn("r:embed"), new_id)
                _resize_drawing(blip, width_px, height_px)
                swapped += 1
        for rid in old_ids:
            # Nothing points at it any more, so the default signature is not
            # left hidden inside the file.
            part.drop_rel(rid)

    if not swapped:
        logger.error(
            "lho_signature.apply: %s has its own signature (%s) but this "
            "template's signature is not the default one, so it could not be "
            "replaced — the document carries the template's signature.",
            lho, own)
        return None
    logger.info("lho_signature.apply: %s signature %s put in (%d place(s))",
                lho, os.path.basename(own), swapped)
    return own
