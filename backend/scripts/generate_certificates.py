"""Generate CSP Certificates directly from Google Sheet rows.

Reads specific rows from the live CSP data sheet and generates
CSP Certificate DOCX files without needing a database or server.

Usage:
    # Generate certificates for rows 11 to 14 (1-indexed, including header)
    .venv/Scripts/python.exe scripts/generate_certificates.py --rows 11-14

    # Generate certificates for specific rows
    .venv/Scripts/python.exe scripts/generate_certificates.py --rows 11,12,13,14

    # Generate all four document types instead of just the certificate
    .venv/Scripts/python.exe scripts/generate_certificates.py --rows 11-14 --all-docs

Files land in backend/generated_documents/<CSP Code>/.
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.models.enums import DocumentType  # noqa: E402
from app.services.csp_gsheet_service import _get_sheets_service  # noqa: E402
from app.services.csp_mapping import map_sheet_row  # noqa: E402
from app.services import template_service  # noqa: E402
from app.services import document_service  # noqa: E402

settings = get_settings()

# The CSP Certificate does not need a photo, so it can be generated
# for any CSP that has the five required fields filled in.
CSP_CERTIFICATE_FIELDS = set(
    template_service.PLACEHOLDER_FIELDS[DocumentType.CSP_CERTIFICATE].values()
)


def parse_row_spec(spec: str) -> list[int]:
    """Parse a row specification like '11-14' or '11,12,13,14'.

    Returns 0-indexed data row numbers (excluding header).
    The user specifies 1-indexed sheet rows (row 1 = header).
    """
    rows = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            rows.extend(range(int(start), int(end) + 1))
        else:
            rows.append(int(part))
    # Convert from 1-indexed sheet rows to 0-indexed data rows
    # Row 1 is the header, so data row 0 is sheet row 2
    return [r - 2 for r in rows]  # subtract 2: 1 for 0-index, 1 for header


def read_specific_rows(row_indices: list[int]) -> list[dict[str, str]]:
    """Read specific data rows from the Google Sheet.

    Args:
        row_indices: 0-indexed data row indices (header excluded).

    Returns:
        List of dicts mapping header → value for the requested rows.
    """
    sheet_id = settings.google_sheets_csp_sheet_id
    sheet_name = settings.google_sheets_csp_sheet_name

    if not sheet_id:
        print("ERROR: GOOGLE_SHEETS_CSP_SHEET_ID is not configured in .env")
        sys.exit(1)

    service = _get_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=sheet_name)
        .execute()
    )
    values = result.get("values", [])

    if not values or len(values) < 2:
        print(f"ERROR: No data found in sheet '{sheet_name}'")
        sys.exit(1)

    headers = [h.strip() for h in values[0]]
    all_data_rows = values[1:]

    print(f"Sheet has {len(headers)} columns and {len(all_data_rows)} data rows")
    print(f"Headers: {headers}\n")

    selected = []
    for idx in row_indices:
        if idx < 0 or idx >= len(all_data_rows):
            print(f"WARNING: Row index {idx + 2} is out of range "
                  f"(sheet has rows 2–{len(all_data_rows) + 1}), skipping")
            continue
        row = all_data_rows[idx]
        record = {}
        for i, header in enumerate(headers):
            record[header] = row[i].strip() if i < len(row) else ""
        selected.append(record)

    return selected


def build_csp_like(mapped: dict[str, str]):
    """Build a lightweight object that looks like a CSPRecord for template filling.

    We don't need a database — just an object with the right attributes.
    """

    class FakeCSP:
        def __init__(self, fields):
            # Set the business key
            self.csp_id = fields.get("csp_code", "UNKNOWN")
            self.csp_code = fields.get("csp_code", "")
            self.certificate_date = None
            # Set every field from the mapping
            for attr, value in fields.items():
                setattr(self, attr, value)

        def __repr__(self):
            return f"<FakeCSP {self.csp_id} name={getattr(self, 'name', '?')}>"

    return FakeCSP(mapped)


def main():
    parser = argparse.ArgumentParser(
        description="Generate CSP Certificates from Google Sheet rows"
    )
    parser.add_argument(
        "--rows", required=True,
        help="Sheet rows to process, e.g. '11-14' or '11,12,13,14' "
             "(1-indexed, row 1 = header)"
    )
    parser.add_argument(
        "--all-docs", action="store_true",
        help="Generate all four document types, not just the CSP Certificate"
    )
    parser.add_argument(
        "--out", default=None,
        help="Output directory (default: backend/generated_documents/)"
    )
    args = parser.parse_args()

    row_indices = parse_row_spec(args.rows)
    print(f"Requesting sheet rows: {[i + 2 for i in row_indices]}")
    print(f"(0-indexed data rows: {row_indices})\n")

    # Read the rows from Google Sheets
    rows = read_specific_rows(row_indices)
    if not rows:
        print("No valid rows to process.")
        return

    print(f"Read {len(rows)} row(s) from the sheet\n")

    # Decide which documents to generate
    if args.all_docs:
        doc_types = [
            DocumentType.CSP_ID_CARD,
            DocumentType.CSP_CERTIFICATE,
            DocumentType.TRAINING_CERTIFICATE,
            DocumentType.BCP,
        ]
    else:
        doc_types = [DocumentType.CSP_CERTIFICATE]

    output_base = args.out or settings.document_output_dir
    os.makedirs(output_base, exist_ok=True)

    generated_count = 0
    failed_count = 0

    for i, raw_row in enumerate(rows):
        # Map sheet headers to CSP field names
        mapped = map_sheet_row(raw_row)
        csp_code = mapped.get("csp_code", "UNKNOWN")

        print(f"{'=' * 60}")
        print(f"Row {row_indices[i] + 2}: CSP Code = {csp_code}")
        print(f"  Name:     {mapped.get('name', '(blank)')}")
        print(f"  Address:  {mapped.get('address', '(blank)')}")
        print(f"  District: {mapped.get('district', '(blank)')}")
        print(f"  State:    {mapped.get('state', '(blank)')}")
        print(f"  Branch:   {mapped.get('branch_name', '(blank)')}")

        # Build a fake CSP record
        csp = build_csp_like(mapped)

        for doc_type in doc_types:
            doc_label = template_service.BUILTIN_LABELS.get(doc_type, doc_type.value)

            # Check if this doc type needs a photo
            needs_photo = doc_type in template_service.PHOTO_MARKERS
            if needs_photo:
                photo = (mapped.get("photo_url") or "").strip()
                if not photo or not os.path.isfile(photo):
                    if not settings.photo_placeholder_allowed:
                        print(f"  SKIP {doc_label}: no photo and placeholders disabled")
                        failed_count += 1
                        continue

            try:
                output_dir = os.path.join(output_base, csp_code)
                os.makedirs(output_dir, exist_ok=True)

                filepath = document_service.generate_document(
                    csp, doc_type, output_dir,
                    certificate_date_value=date.today(),
                )
                print(f"  OK {doc_label} -> {filepath}")
                generated_count += 1
            except Exception as e:
                print(f"  FAIL {doc_label}: {type(e).__name__}: {e}")
                failed_count += 1

    print(f"\n{'=' * 60}")
    print(f"Done: {generated_count} document(s) generated, {failed_count} failed")
    print(f"Output directory: {os.path.abspath(output_base)}")


if __name__ == "__main__":
    main()
