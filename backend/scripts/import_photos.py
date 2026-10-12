"""File every CSP photo already on disk into the database (tracker No. 89).

    .venv/Scripts/python.exe scripts/import_photos.py

Safe to run again: an unchanged photo is left alone. New photos are filed
automatically from now on; this is for the ones that existed before.
Fetches nothing from Zoho and changes no file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.csp_record import CSPRecord  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import csp_photo_store  # noqa: E402
from app.workspace_context import workspace  # noqa: E402


def main() -> int:
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        workspaces = db.execute(select(Workspace)).scalars().all()
    stored = without = 0
    for ws in workspaces:
        with workspace(ws.id), Session(engine) as db:
            for csp in db.execute(select(CSPRecord).order_by(CSPRecord.csp_id)).scalars():
                if csp_photo_store.original_path(csp) is None:
                    without += 1
                    continue
                changed = csp_photo_store.capture(db, csp)
                db.commit()
                if changed:
                    stored += 1
                    print(f"  {ws.slug}  {csp.csp_id}: {', '.join(changed)}")
    print(f"\n{stored} CSP(s) had photos filed; {without} have no photo on disk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
