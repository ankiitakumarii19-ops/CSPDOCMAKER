"""
CSP DocMaker — Pulling the CSP's photograph out of a KYC PDF

The KYC packs are photographs of paper: every page is one full-page scan with
no text layer and no separate image objects, so there is nothing to "pick" —
the CSP's photo is a region inside a scanned page.

On the EKO "Customer Service Point – ASSOCIATE Application Form" (page 3 of
the pack) a passport photograph is pasted into a printed box near the top
right. That box is what this looks for: the largest dense, roughly
passport-shaped rectangle in the top-right of the page.

It is deliberately strict. A wrong crop means a CSP receives an ID card
showing somebody's Aadhaar scan or a bank stamp, so every candidate has to
pass shape, size and content checks. When nothing passes, this returns
nothing and the caller alerts the RM — refusing is always better than
guessing.

Only the cropped photograph is kept. The source PDF is never stored.
"""

import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# The form's photo box sits in the top-right. Searched generously, as scans
# are skewed and cropped inconsistently.
SEARCH_REGION = (0.58, 0.02, 1.00, 0.45)   # left, top, right, bottom (fractions)

ANALYSIS_DPI = 100     # enough to find the photo
EXTRACT_DPI = 400      # what the crop is finally rendered at

# Analysis works on block averages rather than pixels. At 100 dpi a 16-pixel
# block is about 4mm: thin pen strokes and printed rules average away to
# paper, while a pasted photograph stays a solid block. This is the whole
# trick — at full resolution, handwriting looks just as "dark" as a face.
BLOCK = 16

# A block counts as photo-like when it is meaningfully darker than the page's
# own paper tone, or carries real colour. Both are measured against the page,
# because these scans range from near-white to distinctly grey.
DARKER_THAN_PAPER = 22
COLOURFUL = 14

# A passport photo is 35x45mm — 0.78 wide-to-tall. Allow for hand-trimmed
# photos and skewed scans, but not for a square stamp or a wide logo.
MIN_ASPECT = 0.50
MAX_ASPECT = 1.15

# 35x45mm at 100 dpi is ~138x177 px, so ~8x11 blocks. Requiring a good margin
# under that still excludes text lines, which are one or two blocks tall.
MIN_BLOCKS_WIDE = 5
MIN_BLOCKS_TALL = 6

# A photograph fills its own bounding box; an L of form rules does not.
MIN_SOLIDITY = 0.55

# Pages to try, in order: the application form first, then the rest.
DEFAULT_PAGE_ORDER_HINT = 3

# Shape and density are not enough on their own. Tested against a real pack,
# a crop of the applicant's Aadhaar card — "GOVERNMENT OF INDIA" over a QR
# code — scored 0.88 solidity at a 0.82 aspect ratio and sailed through every
# geometric check. Put on an ID card, that would have shown a CSP their own
# QR code where their face belongs.
#
# So a candidate must also contain a face. This is a Haar cascade: a fixed,
# offline, deterministic classifier that ships with OpenCV. No model is
# downloaded, no service is called, and the same input always gives the same
# answer.
REQUIRE_FACE = True
FACE_MIN_SIZE_FRACTION = 0.10   # ignore specks when searching for a face

# A face being present is not enough either. Pulled from a real CRM record,
# a crop of an Aadhaar card contained a genuine face and passed — but the face
# filled only 5% of it, the rest being card. In a passport photograph the face
# dominates. Measured on real documents:
#
#     real photos          0.17, 0.24, 0.26
#     Aadhaar card crop    0.05
#
# This is also what "pick the clear image" means when several PDFs on a record
# each yield a candidate: the clearest is the one that is actually a portrait.
MIN_FACE_FRACTION = 0.12

# A single image covering this much of the sheet means the page is
# the photograph rather than a document containing one.
WHOLE_PAGE_MIN_COVERAGE = 0.55


class PhotoNotFound(Exception):
    """No region in the document could be trusted to be the CSP's photo."""


@dataclass
class Candidate:
    page: int          # 1-based
    box: Tuple[float, float, float, float]   # fractions of the page
    fill: float
    aspect: float
    score: float


def _page_order(page_count: int) -> List[int]:
    """Page 3 first — the application form — then every other page."""
    order = []
    if page_count >= DEFAULT_PAGE_ORDER_HINT:
        order.append(DEFAULT_PAGE_ORDER_HINT - 1)
    order.extend(i for i in range(page_count) if i not in order)
    return order


def photo_mask(region_image):
    """Block-average the region and mark the blocks that look like a photo.

    Averaging first is what makes this work: a pen stroke covers a small part
    of its block and averages back to paper, while a photograph darkens every
    block it covers.
    """
    import numpy as np

    pixels = np.asarray(region_image.convert("RGB"), dtype=np.float32)
    height, width, _ = pixels.shape
    height -= height % BLOCK
    width -= width % BLOCK
    if height < BLOCK or width < BLOCK:
        return np.zeros((0, 0), dtype=bool)

    blocks = (
        pixels[:height, :width]
        .reshape(height // BLOCK, BLOCK, width // BLOCK, BLOCK, 3)
        .mean(axis=(1, 3))
    )
    brightness = blocks.max(axis=2)
    saturation = blocks.max(axis=2) - blocks.min(axis=2)

    # The page's own paper tone, not a fixed value: these scans run from
    # near-white to clearly grey.
    paper = float(np.median(brightness))
    return (brightness < paper - DARKER_THAN_PAPER) | (saturation > COLOURFUL)


_face_cascade = None


def _get_face_cascade():
    """Load the Haar cascade once and reuse it."""
    global _face_cascade
    if _face_cascade is None:
        import cv2
        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if _face_cascade.empty():
            raise RuntimeError(
                "OpenCV's frontal-face cascade could not be loaded — photo "
                "extraction cannot verify that a crop contains a face."
            )
    return _face_cascade


def face_fraction(image) -> float:
    """How much of the image the largest face covers, 0 when there is none."""
    import cv2
    import numpy as np

    grey = cv2.equalizeHist(np.asarray(image.convert("L"), dtype=np.uint8))
    height, width = grey.shape
    minimum = (int(width * FACE_MIN_SIZE_FRACTION),
               int(height * FACE_MIN_SIZE_FRACTION))
    faces = _get_face_cascade().detectMultiScale(
        grey, scaleFactor=1.1, minNeighbors=5, minSize=minimum)
    if len(faces) == 0:
        return 0.0
    return max((w * h) / (width * height) for (_, _, w, h) in faces)


def contains_face(image) -> bool:
    """Whether the image is a portrait — a face, and one that dominates it."""
    return face_fraction(image) >= MIN_FACE_FRACTION


def trim_border(image):
    """Shave the pasted photo's dark frame off the edges.

    The photos are physically stuck onto the form and most carry a dark
    printed border, plus a shadow where the paper lifts. Left in, that shows
    on the ID card as a black stripe down the side of the face.

    Only edges are removed, and only while they stay much darker than the
    picture as a whole, so this cannot eat into dark hair or clothing.
    """
    import numpy as np

    grey = np.asarray(image.convert("L"), dtype=np.float32)
    height, width = grey.shape
    if height < 20 or width < 20:
        return image

    # Judged against the picture's own middle, which is the face.
    middle = grey[height // 4: 3 * height // 4, width // 4: 3 * width // 4]
    frame_is_darker_than = float(np.median(middle)) * 0.70

    # The frame is not always at the very edge — usually there is a strip of
    # white form paper outside it first. So rather than eating inward from the
    # edge, find the darkest line near each side; if it is clearly darker than
    # the picture, that is the frame, and the photo starts just inside it.
    limit_x, limit_y = max(4, width // 6), max(4, height // 6)
    pad = 2

    def frame_position(lines, limit, from_start: bool):
        """Index of the frame line within `limit` of this side, or None."""
        band = lines[:limit] if from_start else lines[-limit:]
        if band.size == 0:
            return None
        index = int(band.argmin())
        if band[index] >= frame_is_darker_than:
            return None
        return index if from_start else lines.size - limit + index

    columns = grey.mean(axis=0)
    rows = grey.mean(axis=1)

    found = frame_position(columns, limit_x, True)
    left = min(found + 1 + pad, limit_x) if found is not None else 0

    found = frame_position(columns, limit_x, False)
    right = max(found - pad, width - limit_x) if found is not None else width

    found = frame_position(rows, limit_y, True)
    top = min(found + 1 + pad, limit_y) if found is not None else 0

    found = frame_position(rows, limit_y, False)
    bottom = max(found - pad, height - limit_y) if found is not None else height

    # The frame is a band, not a single line, and the photo often casts a
    # shadow beside it. Having cut at the darkest line, shave whatever dark
    # edge is still left — bounded by the same one-sixth limit.
    while left < limit_x and columns[left] < frame_is_darker_than:
        left += 1
    while right > width - limit_x and columns[right - 1] < frame_is_darker_than:
        right -= 1
    while top < limit_y and rows[top] < frame_is_darker_than:
        top += 1
    while bottom > height - limit_y and rows[bottom - 1] < frame_is_darker_than:
        bottom -= 1

    if right - left < width // 2 or bottom - top < height // 2:
        return image  # something went wrong; keep the original

    if (left, top, right, bottom) != (0, 0, width, height):
        logger.info(
            "photo_extraction: trimmed border l=%d t=%d r=%d b=%d",
            left, top, width - right, height - bottom,
        )
    return image.crop((left, top, right, bottom))


def _components(mask):
    """Every connected group of True blocks, as (size, x0, y0, x1, y1)."""
    import numpy as np

    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found = []

    for start_y in range(height):
        for start_x in range(width):
            if not mask[start_y, start_x] or seen[start_y, start_x]:
                continue
            stack = [(start_y, start_x)]
            seen[start_y, start_x] = True
            cells = []
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if (0 <= ny < height and 0 <= nx < width
                                and mask[ny, nx] and not seen[ny, nx]):
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            found.append((len(cells), min(xs), min(ys), max(xs) + 1, max(ys) + 1))

    return found


def _examine_page(document, page_index: int) -> Optional[Candidate]:
    """Look for a photograph in one page's top-right corner."""
    import io

    from PIL import Image

    page = document[page_index]
    pixmap = page.get_pixmap(dpi=ANALYSIS_DPI)
    page_image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    page_width, page_height = page_image.size

    left = int(page_width * SEARCH_REGION[0])
    top = int(page_height * SEARCH_REGION[1])
    right = int(page_width * SEARCH_REGION[2])
    bottom = int(page_height * SEARCH_REGION[3])
    region = page_image.crop((left, top, right, bottom))

    mask = photo_mask(region)
    if mask.size == 0:
        return None

    best: Optional[Candidate] = None
    for size, bx0, by0, bx1, by1 in _components(mask):
        blocks_wide, blocks_tall = bx1 - bx0, by1 - by0
        if blocks_wide < MIN_BLOCKS_WIDE or blocks_tall < MIN_BLOCKS_TALL:
            continue

        aspect = blocks_wide / blocks_tall
        if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
            continue

        solidity = size / (blocks_wide * blocks_tall)
        if solidity < MIN_SOLIDITY:
            continue

        # Closest to 35x45mm wins, with a nudge towards the solider candidate.
        score = solidity - abs(aspect - (35 / 45))
        if best is not None and score <= best.score:
            continue

        # The decisive check, and the last one because it is the costliest:
        # a candidate that holds no face is not this person's photograph.
        if REQUIRE_FACE:
            crop = region.crop((bx0 * BLOCK, by0 * BLOCK,
                                bx1 * BLOCK, by1 * BLOCK))
            if not contains_face(crop):
                logger.debug(
                    "photo_extraction: page %d candidate rejected — no face",
                    page_index + 1,
                )
                continue

        fractions = (
            (left + bx0 * BLOCK) / page_width,
            (top + by0 * BLOCK) / page_height,
            (left + bx1 * BLOCK) / page_width,
            (top + by1 * BLOCK) / page_height,
        )
        best = Candidate(page=page_index + 1, box=fractions, fill=solidity,
                         aspect=aspect, score=score)

    return best


def find_photo(pdf_path: str) -> Candidate:
    """Locate the CSP's photograph, or raise PhotoNotFound."""
    import pymupdf

    document = pymupdf.open(pdf_path)
    try:
        for page_index in _page_order(len(document)):
            candidate = _examine_page(document, page_index)
            if candidate is not None:
                logger.info(
                    "photo_extraction: found a photo on page %d of %s "
                    "(fill %.0f%%, aspect %.2f)",
                    candidate.page, pdf_path, candidate.fill * 100, candidate.aspect,
                )
                return candidate
    finally:
        document.close()

    raise PhotoNotFound(
        f"No region of {pdf_path} could be confidently identified as the CSP's "
        "photograph. The RM must supply one."
    )


def whole_page_candidate(pdf_path: str) -> Candidate:
    """The page itself, when the page IS the photograph.

    The region finder looks for a photo-sized block surrounded by paper. A
    CRM file called "Photo <name>.pdf" is often one scanned photograph
    filling the whole sheet, so there is no surrounding paper to find and
    the search comes back empty.

    Here the page is taken whole and the white margin trimmed off. The face
    check downstream still decides whether it is really a portrait, so this
    widens where a photo may be found without weakening what counts as one.
    """
    import pymupdf

    document = pymupdf.open(pdf_path)
    try:
        for index, page in enumerate(document):
            images = page.get_images(full=True)
            if len(images) != 1:
                continue
            area = abs(page.rect.width * page.rect.height)
            if area <= 0:
                continue
            covered = sum(abs(r.width * r.height)
                          for r in page.get_image_rects(images[0][0]))
            if covered / area < WHOLE_PAGE_MIN_COVERAGE:
                continue
            # Crop to the image's own rectangle, not the whole sheet: the
            # page carries a white margin and often a dark scanner edge, and
            # neither belongs on an ID card.
            rect = max(page.get_image_rects(images[0][0]),
                       key=lambda r: abs(r.width * r.height))
            box = (
                max(rect.x0 / page.rect.width, 0.0),
                max(rect.y0 / page.rect.height, 0.0),
                min(rect.x1 / page.rect.width, 1.0),
                min(rect.y1 / page.rect.height, 1.0),
            )
            logger.info(
                "photo_extraction: page %d of %s is a single image covering "
                "%.0f%% of the sheet — cropping to the image itself",
                index + 1, os.path.basename(pdf_path), covered / area * 100,
            )
            return Candidate(
                page=index + 1, box=box, fill=covered / area,
                aspect=(rect.width / rect.height) if rect.height else 0.0,
                score=0.0)
    finally:
        document.close()

    raise PhotoNotFound(
        f"{os.path.basename(pdf_path)} holds no photo-shaped region and is "
        f"not a single full-page image.")


def extract_photo(pdf_path: str, output_path: str) -> Candidate:
    """Find the photograph and write it out as a PNG.

    Returns the candidate that was used. Raises PhotoNotFound when the
    document holds nothing that passes the checks.
    """
    import io
    import os

    import pymupdf
    from PIL import Image

    try:
        candidate = find_photo(pdf_path)
    except PhotoNotFound:
        # No photo-shaped block — the page may be the photograph itself.
        candidate = whole_page_candidate(pdf_path)

    document = pymupdf.open(pdf_path)
    try:
        page = document[candidate.page - 1]
        pixmap = page.get_pixmap(dpi=EXTRACT_DPI)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        width, height = image.size
        x0, y0, x1, y1 = candidate.box
        crop = trim_border(image.crop((int(x0 * width), int(y0 * height),
                                       int(x1 * width), int(y1 * height))))
    finally:
        document.close()

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    crop.save(output_path, "PNG", optimize=True)
    logger.info(
        "photo_extraction: wrote %dx%d photo to %s",
        crop.size[0], crop.size[1], output_path,
    )
    return candidate


def extract_best_photo(pdf_paths, output_path: str):
    """Take the clearest photograph across several documents.

    A CRM record often carries a handful of PDFs with no useful names, so
    every one is tried and the best portrait wins. "Clearest" is how much of
    the crop the face fills: a passport photograph is mostly face, whereas a
    crop of an identity card is mostly card.

    Returns (candidate, source_pdf). Raises PhotoNotFound when no document
    yields a portrait, which is the signal to alert the RM.
    """
    import os
    import tempfile

    from PIL import Image

    best = None            # (fraction, candidate, temp_file, source)
    failures = []

    for pdf_path in pdf_paths:
        handle, scratch = tempfile.mkstemp(suffix=".png", prefix="photo_")
        os.close(handle)
        try:
            candidate = extract_photo(pdf_path, scratch)
            fraction = face_fraction(Image.open(scratch))
        except PhotoNotFound:
            os.remove(scratch)
            failures.append(os.path.basename(pdf_path))
            continue
        except Exception as e:
            os.remove(scratch)
            failures.append(f"{os.path.basename(pdf_path)} ({type(e).__name__})")
            logger.warning("photo_extraction: %s could not be read: %s", pdf_path, e)
            continue

        logger.info("photo_extraction: %s -> face fills %.0f%% of the crop",
                    os.path.basename(pdf_path), fraction * 100)

        if best is None or fraction > best[0]:
            if best is not None:
                os.remove(best[2])
            best = (fraction, candidate, scratch, pdf_path)
        else:
            os.remove(scratch)

    if best is None:
        raise PhotoNotFound(
            "None of the documents contained a usable photograph"
            + (f" (tried: {', '.join(failures)})" if failures else "")
            + ". The RM must supply one."
        )

    fraction, candidate, scratch, source = best
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    os.replace(scratch, output_path)
    logger.info(
        "photo_extraction: chose %s (face %.0f%% of the crop) out of %d document(s)",
        os.path.basename(source), fraction * 100, len(list(pdf_paths)),
    )
    return candidate, source
