"""Get the photo of every CSP that has none, from Zoho (tracker No. 191).

    python scripts/fetch_zoho_photos.py --dry-run      # only count who has no photo
    python scripts/fetch_zoho_photos.py --limit 20     # try the first 20
    python scripts/fetch_zoho_photos.py                # try all of them

On the server (Zoho login and the live database are there):

    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec api python scripts/fetch_zoho_photos.py --limit 20

For each CSP with no photo yet, the same steps the app already uses for a new
CSP (csp_photo_service.fetch_photo):

    search Zoho sbi_kiosk (code AND phone must match) and Leads (two of
    phone / name / branch must agree) -> download the KYC PDFs -> take the
    clearest face -> delete the PDFs (Aadhaar / PAN are never kept)

then makes the 35 x 45 mm passport version, files both in the database and
shows the photo in the sheet's Photo column (No. 91; --no-sheet to skip).

Read-only on Zoho. Sends no message to anyone. A CSP that already has a photo
is never touched, so it is safe to run again: it carries on with whoever is
still without one. Every CSP's result is written to a CSV report.
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import telemetry  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.csp_photo import ORIGINAL  # noqa: E402
from app.models.csp_record import CSPRecord  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import (  # noqa: E402
    csp_photo_service, csp_photo_store, sheet_photo, studio_photo, zoho_client,
)
from app.workspace_context import workspace  # noqa: E402

EKO = "sbi-kiosk-csp"

# Zoho errors this many times in a row = the CRM is down or our daily API
# allowance is used up; stop instead of marking every remaining CSP failed.
STOP_AFTER_CRM_ERRORS = 5


def _has_photo(db, csp) -> bool:
    if csp_photo_store.original_path(csp):
        return True
    from app.models.csp_photo import CSPPhoto
    return db.execute(select(CSPPhoto.id).where(
        CSPPhoto.csp_id == csp.csp_id, CSPPhoto.kind == ORIGINAL)).first() is not None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=EKO, help="workspace slug (default: Eko)")
    ap.add_argument("--limit", type=int, default=0, help="try at most this many CSPs")
    ap.add_argument("--only", nargs="*", default=[], help="only these CSP codes")
    ap.add_argument("--pause", type=float, default=1.0,
                    help="seconds between CSPs, to stay inside Zoho's API limits")
    ap.add_argument("--no-sheet", action="store_true",
                    help="do not show the photos in the sheet's Photo column")
    ap.add_argument("--dry-run", action="store_true",
                    help="only list who has no photo; nothing is fetched")
    ap.add_argument("--report", default=None, help="CSV report path")
    a = ap.parse_args()
    telemetry.setup("cspdocmaker-script", "WARNING")

    if not a.dry_run and not zoho_client.is_configured():
        print("Zoho is not configured here (ZOHO_* settings missing). Run this on the server.")
        return 1

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        ws = db.execute(select(Workspace).where(Workspace.slug == a.workspace)).scalar_one_or_none()
    if ws is None:
        print(f"No workspace {a.workspace!r}.")
        return 1

    report = a.report or os.path.join(
        csp_photo_service.photo_directory(),
        f"zoho_photo_report_{datetime.now():%Y%m%d_%H%M}.csv")
    counts = {"found": 0, "not_found": 0, "skipped_has_photo": 0}
    crm_errors_in_a_row = 0
    stopped_early = None

    with workspace(ws.id), Session(engine) as db, open(report, "w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh)
        out.writerow(["csp_code", "name", "result", "reason", "passport_photo", "sheet"])

        query = select(CSPRecord).order_by(CSPRecord.csp_id)
        if a.only:
            query = query.where(CSPRecord.csp_id.in_(a.only) | CSPRecord.csp_code.in_(a.only))
        all_csps = db.execute(query).scalars().all()

        todo = []
        for csp in all_csps:
            if _has_photo(db, csp):
                counts["skipped_has_photo"] += 1
            else:
                todo.append(csp)
        print(f"{len(all_csps)} CSP(s) in {a.workspace}: "
              f"{counts['skipped_has_photo']} already have a photo, {len(todo)} have none.")
        if a.limit:
            todo = todo[:a.limit]

        if a.dry_run:
            for csp in todo:
                out.writerow([csp.csp_id, csp.name, "no photo", "dry run", "", ""])
            print(f"Dry run: nothing fetched. List of the {len(todo)} in {report}")
            return 0

        print(f"Trying {len(todo)} on Zoho...\n")
        for n, csp in enumerate(todo, 1):
            result = csp_photo_service.fetch_photo(csp)
            if result.ok:
                crm_errors_in_a_row = 0
                csp.photo_url = result.path
                passport = studio_photo.make(result.path)
                csp_photo_store.capture(db, csp)
                db.commit()
                sheet = "not asked" if a.no_sheet else sheet_photo.push(csp.csp_id, ws.id)["status"]
                counts["found"] += 1
                out.writerow([csp.csp_id, csp.name, "photo saved",
                              os.path.basename(result.source or ""),
                              "made" if passport else "could not be made", sheet])
                print(f"[{n}/{len(todo)}] {csp.csp_id} {csp.name}: photo saved"
                      + ("" if passport else " (passport version could not be made)"))
            else:
                counts["not_found"] += 1
                out.writerow([csp.csp_id, csp.name, "no photo", result.message, "", ""])
                print(f"[{n}/{len(todo)}] {csp.csp_id} {csp.name}: {result.message}")
                if result.reason == csp_photo_service.CRM_ERROR:
                    crm_errors_in_a_row += 1
                    if crm_errors_in_a_row >= STOP_AFTER_CRM_ERRORS:
                        stopped_early = result.detail or result.message
                        break
                else:
                    crm_errors_in_a_row = 0
            fh.flush()
            time.sleep(a.pause)

    print(f"\nPhotos saved: {counts['found']}   No photo: {counts['not_found']}   "
          f"Already had one: {counts['skipped_has_photo']}")
    if stopped_early:
        print(f"STOPPED: Zoho failed {STOP_AFTER_CRM_ERRORS} times in a row "
              f"({stopped_early}). Run again later; it carries on from where it stopped.")
    print(f"Report: {report}")
    return 2 if stopped_early else 0


if __name__ == "__main__":
    sys.exit(main())
