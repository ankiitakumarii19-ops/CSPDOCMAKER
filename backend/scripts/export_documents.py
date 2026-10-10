"""Pull stored documents out of PostgreSQL so you can open them.

Documents live in the database as bytes, which is what makes them survive a
redeploy — but it also means you cannot double-click them. This writes them
back out as ordinary files.

    # every CSP, newest version of each document
    .venv/Scripts/python.exe scripts/export_documents.py

    # one CSP, PDFs only
    .venv/Scripts/python.exe scripts/export_documents.py --csp 1A850466 --format pdf

    # every version ever generated, not just the newest
    .venv/Scripts/python.exe scripts/export_documents.py --all-versions

    # just list what is stored, write nothing
    .venv/Scripts/python.exe scripts/export_documents.py --list

Files land in backend/exported_documents/<CSP ID>/ unless --out says otherwise.
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.stored_document import StoredDocument  # noqa: E402
from app.services import document_storage_service as storage  # noqa: E402

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "exported_documents",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csp", help="only this CSP ID")
    parser.add_argument("--format", choices=["pdf", "docx"],
                        help="only this file format")
    parser.add_argument("--all-versions", action="store_true",
                        help="export every version, not just the newest")
    parser.add_argument("--list", action="store_true",
                        help="show what is stored and exit")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )

    with Session(engine) as session:
        query = select(StoredDocument)
        if args.csp:
            query = query.where(StoredDocument.csp_id == args.csp)
        if args.format:
            query = query.where(StoredDocument.file_format == args.format.upper())
        rows = session.execute(
            query.order_by(StoredDocument.csp_id,
                           StoredDocument.document_type,
                           StoredDocument.file_format,
                           StoredDocument.version.desc())
        ).scalars().all()

        if not rows:
            print("Nothing stored matches that.")
            return

        # Newest version of each (csp, type, format) unless asked for all.
        if not args.all_versions:
            seen = set()
            newest = []
            for row in rows:
                key = (row.csp_id, row.document_type, row.file_format)
                if key not in seen:
                    seen.add(key)
                    newest.append(row)
            rows = newest

        by_csp = defaultdict(list)
        for row in rows:
            by_csp[row.csp_id].append(row)

        total_bytes = 0
        for csp_id, documents in sorted(by_csp.items()):
            print(f"\n{csp_id}")
            target = os.path.join(args.out, csp_id)

            for row in documents:
                intact = storage.verify_integrity(row)
                flag = "" if intact else "   !! CHECKSUM MISMATCH"
                line = (f"  v{row.version}  {row.document_type.value:<22}"
                        f"{row.file_format.value:<5}{row.file_size:>9,} bytes{flag}")

                if args.list:
                    print(line)
                    continue

                if not intact:
                    print(line + "  — not written")
                    continue

                os.makedirs(target, exist_ok=True)
                # Version in the name so --all-versions cannot overwrite itself.
                name = (f"{row.document_type.value}_v{row.version}"
                        f".{row.file_format.value.lower()}")
                path = os.path.join(target, name)
                with open(path, "wb") as fh:
                    fh.write(row.file_data)
                total_bytes += row.file_size
                print(line + f"  -> {name}")

        if not args.list:
            print(f"\nWrote {len(rows)} file(s), {total_bytes:,} bytes, to {args.out}")

    engine.dispose()


main()
