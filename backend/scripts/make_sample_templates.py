"""Make the sample document designs a new workspace starts with (No. 247).

    python scripts/make_sample_templates.py

Reads the four supplied designs (templates/documents) and writes copies to
templates/samples with every trace of Eko taken out: a made-up organisation,
bank, people, phone numbers, addresses and emails; the Eko logo replaced by a
plain "Your logo" box; the signature and stamp replaced by a sample one.
Placeholders, layout, photo boxes and backgrounds are untouched, so the
samples fill exactly like the originals.

The output is checked before it is written: no "eko" anywhere in the files
(text, links, file names inside), none of the original logo or signature
pictures left, and every placeholder still there. Run it again only when the
supplied designs change; the result is committed.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

SOURCE = os.path.join(ROOT, "templates", "documents")
TARGET = os.path.join(ROOT, "templates", "samples")
FILES = ("Appointment__Letter.docx", "BCP.docx", "ID_Card.docx",
         "Training_Certificate.docx")

ORG = "Sample Organisation Pvt Ltd"

# Longest first: a shorter one must not eat part of a longer one.
REPLACE = [
    ("EKO BHARAT VENTURES PVT. LTD. (Formerly known as EKO INDIA FINANCIAL "
     "SERVICES PVT. LTD.)", ORG.upper()),
    ("on behalf of State Bank of India through its National Business "
     "Correspondent, Eko Bharat Ventures Private Limited",
     f"on behalf of Sample Bank through its Business Correspondent, {ORG}"),
    ("linked with State Bank of India Branch", "linked with Sample Bank Branch"),
    ("Plot No 68, Phase IV, Udyog Vihar, Sec- 18 Gurgaon, Haryana, 122022",
     "12 Sample Road, Sample City 100001"),
    ("547, Mandakini Enclave, Alaknanda New Delhi - 110019,",
     "34 Example Lane, Sample City 100002, "),
    ("CIN:U65191DL2007PTC168253", "CIN: SAMPLE000000"),
    ("Tel/faxNo.:+91.124.4385445", "Tel: 0000 000000"),
    ("Eko Bharat Ventures Private Limited", ORG),
    ("Eko Bharat Ventures Pvt. Ltd.", ORG),
    ("Eko Bharat Ventures Pvt Ltd", ORG),
    ("Eko is pleased to appoint", "Sample Organisation is pleased to appoint"),
    ("SBI Kiosk Customer Service Point", "Customer Service Point"),
    ("SBI CUSTOMER SERVICE POINT", "CUSTOMER SERVICE POINT"),
    ("State Bank of India", "Sample Bank"),
    ("Kiosk Connect (Complaint Portal)", "Sample complaint portal"),
    ("Ganesh.kumar@eko.co.in", "regional.head@example.com"),
    ("info@eko.co.in", "info@example.com"),
    ("www.eko.in", "www.example.com"),
    ("Ganesh Kumar", "Sample Regional Head"),
    ("9217060639", "1800000000"),
    ("9821946420", "9000000000"),
    ("1A85", "SB00"),
]
FORBIDDEN = re.compile(r"eko|ganesh|state bank|\bsbi\b|udyog|alaknanda|"
                       r"mandakini|9217060639|9821946420|1a85|4385445|U65191", re.I)


# ---- pictures -------------------------------------------------------------------

def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                       # Pillow < 10.1
        return ImageFont.load_default()


def sample_logo(width: int, height: int) -> bytes:
    """A plain grey 'Your logo' box the size of the picture it replaces."""
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = max(2, min(width, height) // 12)
    d.rounded_rectangle((pad, pad, width - pad, height - pad),
                        radius=max(4, min(width, height) // 8),
                        fill=(236, 239, 243, 255), outline=(150, 158, 170, 255),
                        width=max(2, min(width, height) // 60))
    font = _font(max(12, min(width // 5, height // 3)))
    text = "Your logo"
    box = d.textbbox((0, 0), text, font=font)
    d.text(((width - box[2]) / 2, (height - box[3]) / 2), text,
           fill=(110, 118, 130, 255), font=font)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


def sample_signature(width: int = 900, height: int = 605) -> bytes:
    """A made-up signature over a round 'SAMPLE' stamp."""
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # The stamp.
    cx, cy, r = int(width * 0.62), int(height * 0.48), int(height * 0.36)
    purple = (88, 70, 160, 230)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=purple, width=8)
    d.ellipse((cx - r + 26, cy - r + 26, cx + r - 26, cy + r - 26), outline=purple, width=4)
    for text, dy, size in (("SAMPLE", -40, 64), ("ORGANISATION", 30, 40)):
        font = _font(size)
        box = d.textbbox((0, 0), text, font=font)
        d.text((cx - box[2] / 2, cy + dy - box[3] / 2), text, fill=purple, font=font)
    # The signature: a loose, made-up scrawl.
    navy = (20, 40, 120, 255)
    points = []
    for i in range(0, 361):
        t = i / 360
        x = width * 0.08 + t * width * 0.78
        y = height * 0.55 + math.sin(t * math.pi * 7) * height * 0.11 * (1 - t * 0.6) \
            - math.sin(t * math.pi * 2) * height * 0.08
        points.append((x, y))
    d.line(points, fill=navy, width=9, joint="curve")
    d.line([(width * 0.12, height * 0.80), (width * 0.88, height * 0.74)],
           fill=navy, width=6)
    font = _font(40)
    d.text((width * 0.08, height * 0.86), "Sample Signatory", fill=navy, font=font)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


SIGNATURE = sample_signature()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- text ----------------------------------------------------------------------

def _replace_in_paragraph(p) -> None:
    """Replace across the paragraph's runs without disturbing their formats:
    the new words go where the old ones began, the rest of the old ones is
    removed from the runs they spilled into."""
    nodes = [t for t in p.iter(qn("w:t"))]
    if not nodes:
        return
    for old, new in REPLACE:
        while True:
            texts = [n.text or "" for n in nodes]
            joined = "".join(texts)
            at = joined.find(old)
            if at < 0:
                break
            end = at + len(old)
            pos = 0
            placed = False
            for n, text in zip(nodes, texts):
                start, stop = pos, pos + len(text)
                pos = stop
                if stop <= at or start >= end:
                    continue
                a, b = max(at, start) - start, min(end, stop) - start
                if not placed:
                    n.text = text[:a] + new + text[b:]
                    placed = True
                else:
                    n.text = text[:a] + text[b:]
                n.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _parts(doc):
    seen = set()
    for part in doc.part.package.iter_parts():
        if id(part) in seen:
            continue
        seen.add(id(part))
        yield part


def clean(path: str) -> bytes:
    from app.services import lho_signature
    with open(lho_signature.default_path(), "rb") as f:
        eko_signature = f.read()

    doc = Document(path)
    for part in _parts(doc):
        element = getattr(part, "element", None)
        if element is not None:
            for p in element.iter(qn("w:p")):
                _replace_in_paragraph(p)
        rels = getattr(part, "rels", {})
        for rid, rel in list(rels.items()):
            if rel.is_external:
                target = rel.target_ref
                if FORBIDDEN.search(target or ""):
                    rel._target = ("mailto:info@example.com" if target.startswith("mailto:")
                                   else "https://www.example.com")
                continue
            if "image" not in rel.reltype:
                continue
            image_part = rel.target_part
            blob = image_part.blob
            if blob == eko_signature:
                image_part._blob = SIGNATURE
            elif _is_logo(blob):
                with Image.open(io.BytesIO(blob)) as im:
                    image_part._blob = sample_logo(*im.size)
    out = io.BytesIO()
    doc.save(out)
    data = out.getvalue()
    # Image parts keep their names (image1.png); a JPEG name holding a PNG is
    # fine for Word, but rename nothing so every relationship still points
    # at the same part.
    return data


# The Eko logo, in the two sizes the designs carry.
LOGO_PREFIXES = ("5cc05b38", "f5f999ec")


def _is_logo(blob: bytes) -> bool:
    return sha(blob)[:8] in LOGO_PREFIXES


def check(name: str, original: str, data: bytes) -> None:
    from app.services import template_service as ts
    problems = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            raw = z.read(info)
            if FORBIDDEN.search(info.filename):
                problems.append(f"file name {info.filename}")
            if info.filename.endswith((".xml", ".rels")):
                text = raw.decode("utf-8", "replace")
                for m in FORBIDDEN.finditer(re.sub(r"<[^>]+>", "", text)):
                    problems.append(f"{info.filename}: …{m.group(0)}…")
                for m in FORBIDDEN.finditer(" ".join(re.findall(r'Target="([^"]+)"', text))):
                    problems.append(f"{info.filename} link: {m.group(0)}")
            elif sha(raw)[:8] in LOGO_PREFIXES:
                problems.append(f"Eko logo still in {info.filename}")
    from app.services import lho_signature
    with open(lho_signature.default_path(), "rb") as f:
        if f.read() in [zipfile.ZipFile(io.BytesIO(data)).read(i)
                        for i in zipfile.ZipFile(io.BytesIO(data)).namelist()]:
            problems.append("Eko's signature still inside")
    before = set(_placeholders(Document(original), ts))
    after = set(_placeholders(Document(io.BytesIO(data)), ts))
    if before != after:
        problems.append(f"placeholders changed: {sorted(before ^ after)}")
    if problems:
        raise SystemExit(f"{name}: not clean —\n  " + "\n  ".join(problems))


def _placeholders(doc, ts):
    for para in ts._all_paragraphs(doc):
        for m in ts._PLACEHOLDER_RE.finditer("".join(r.text for r in para.runs)):
            yield m.group(1).strip()


def main() -> None:
    os.makedirs(TARGET, exist_ok=True)
    for name in FILES:
        source = os.path.join(SOURCE, name)
        data = clean(source)
        check(name, source, data)
        with open(os.path.join(TARGET, name), "wb") as f:
            f.write(data)
        print(f"{name}: {len(data):,} bytes, clean")
    with open(os.path.join(TARGET, "sample-signature.png"), "wb") as f:
        f.write(SIGNATURE)
    print("sample-signature.png written")


if __name__ == "__main__":
    main()
