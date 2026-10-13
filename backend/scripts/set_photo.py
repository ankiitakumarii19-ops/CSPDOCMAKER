"""Give a CSP a photo by hand, and show it in the CSP sheet (tracker No. 91).

    python scripts/set_photo.py <CSP code> <image file>

On the server (the file copied into the container first):

    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        cp "1A852458.png" api:/tmp/1A852458.png
    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec api python scripts/set_photo.py 1A852458 /tmp/1A852458.png

Saves it as the CSP's photo, makes the 35 x 45 mm passport version printed
on the documents, keeps both in the database, and writes it into the
sheet's Photo column (where the sheet script turns it into a picture).
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import telemetry  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.csp_record import CSPRecord  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import (  # noqa: E402
    csp_photo_service, csp_photo_store, sheet_photo, studio_photo,
)
from app.workspace_context import workspace  # noqa: E402

EKO = "sbi-kiosk-csp"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csp_code")
    ap.add_argument("image")
    ap.add_argument("--workspace", default=EKO, help="workspace slug (default: Eko)")
    a = ap.parse_args()
    telemetry.setup("cspdocmaker-script", "WARNING")

    try:
        with Image.open(a.image) as im:
            im.verify()
            fmt = (im.format or "").lower()
    except Exception as e:
        print(f"Not an image I can read: {a.image} ({type(e).__name__})")
        return 1
    ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}.get(fmt)
    if not ext:
        print(f"Unsupported image type {fmt!r}: use JPG, PNG or WEBP.")
        return 1

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        ws = db.execute(select(Workspace).where(Workspace.slug == a.workspace)).scalar_one_or_none()
    if ws is None:
        print(f"No workspace {a.workspace!r}.")
        return 1

    with workspace(ws.id), Session(engine) as db:
        csp = db.execute(select(CSPRecord).where(
            (CSPRecord.csp_id == a.csp_code) | (CSPRecord.csp_code == a.csp_code))).scalars().first()
        if csp is None:
            print(f"No CSP {a.csp_code} in {a.workspace} (has the sheet been read yet?).")
            return 1

        dest = os.path.join(csp_photo_service.photo_directory(), f"{csp.csp_id}{ext}")
        shutil.copyfile(a.image, dest)
        csp.photo_url = dest
        print(f"{csp.csp_id} ({csp.name}): photo saved")

        passport = studio_photo.make(dest)
        print("  passport version (35 x 45 mm): " + ("made" if passport else
              "could not be made — documents will say so; the photo as given is kept"))

        changed = csp_photo_store.capture(db, csp)
        db.commit()
        print("  in the database: " + (", ".join(changed) or "already up to date"))

    shown = sheet_photo.push(csp.csp_id, ws.id)
    print(f"  in the sheet: {shown['status']}" + (f" ({shown['reason']})" if shown["status"] != "written" else
          " — the sheet script turns it into a picture within a few minutes"))
    return 0 if shown["status"] in ("written", "skipped") else 2


if __name__ == "__main__":
    sys.exit(main())
