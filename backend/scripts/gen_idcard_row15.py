"""One-off: generate CSP ID Card for row 15 with the provided photo."""
import os
import sys
import shutil
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.models.enums import DocumentType
from app.services.csp_gsheet_service import _get_sheets_service
from app.services.csp_mapping import map_sheet_row
from app.services import document_service
from app.services.pdf_service import convert_to_pdf

settings = get_settings()

# 1. Read row 15 from the sheet
service = _get_sheets_service()
result = service.spreadsheets().values().get(
    spreadsheetId=settings.google_sheets_csp_sheet_id,
    range=settings.google_sheets_csp_sheet_name,
).execute()
values = result.get("values", [])
headers = [h.strip() for h in values[0]]
row = values[14]  # row 15 = index 14 (0-based including header)
raw = {headers[i]: row[i].strip() if i < len(row) else "" for i in range(len(headers))}
mapped = map_sheet_row(raw)
csp_code = mapped.get("csp_code", "UNKNOWN")
csp_name = mapped.get("name", "?")
print(f"CSP: {csp_code} - {csp_name}")

# 2. Copy the provided photo
PHOTO_SRC = (
    r"C:\Users\ankii\.gemini\antigravity-ide\brain"
    r"\6ed3263a-f80b-465f-9324-4ea050bcfb80"
    r"\.user_uploaded\media_1791540578250.png"
)
photo_dir = os.path.join("generated_documents", csp_code)
os.makedirs(photo_dir, exist_ok=True)
photo_dest = os.path.join(photo_dir, "csp_photo.png")
shutil.copy2(PHOTO_SRC, photo_dest)
print(f"Photo saved: {photo_dest}")


# 3. Build a lightweight CSP-like object with the photo
class FakeCSP:
    def __init__(self, fields, photo_path):
        self.csp_id = fields.get("csp_code", "UNKNOWN")
        self.csp_code = fields.get("csp_code", "")
        self.certificate_date = None
        for attr, value in fields.items():
            setattr(self, attr, value)
        self.photo_url = photo_path


csp = FakeCSP(mapped, photo_dest)

# 4. Generate ID Card DOCX
output_dir = os.path.join("generated_documents", csp_code)
filepath = document_service.generate_document(
    csp, DocumentType.CSP_ID_CARD, output_dir,
    certificate_date_value=date.today(),
)
print(f"ID Card DOCX: {filepath}")

# 5. Convert to PDF
pdf = convert_to_pdf(filepath)
size_kb = round(os.path.getsize(pdf) / 1024, 1)
print(f"ID Card PDF:  {pdf} ({size_kb} KB)")
