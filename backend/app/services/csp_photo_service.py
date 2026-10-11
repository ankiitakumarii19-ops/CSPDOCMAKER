"""
CSP DocMaker — getting a CSP's photograph from Zoho CRM

The sequence, as specified:

    search the CRM by the CSP's contact number
      -> confirm the CSP code on the record matches
      -> download every PDF attached to it
      -> take the clearest photograph out of them
      -> keep only that photograph; delete the source documents

The KYC packs hold Aadhaar and PAN scans, so nothing from them is retained
beyond the cropped face. The PDFs are written to a temporary directory and
deleted in a finally block, including when extraction fails.

Nothing here is best-effort: when the photo cannot be obtained the caller is
told why, so the RM can be asked for it instead of a document going out with
a placeholder face.
"""

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings
from app import telemetry

logger = logging.getLogger(__name__)

settings = get_settings()

# Reasons a photo could not be obtained. Each is something an RM or an
# administrator can actually act on.
NOT_CONFIGURED = "zoho_not_configured"
NO_RECORD = "no_matching_crm_record"
NO_ATTACHMENTS = "no_documents_attached"
NO_PHOTO_IN_DOCUMENTS = "no_photograph_in_the_documents"
CRM_ERROR = "crm_unavailable"

# A file named for the photograph is tried before the rest of the pack.
PHOTO_NAME_HINT = "photo"

REASON_TEXT = {
    NOT_CONFIGURED: "Zoho CRM is not configured, so the photo could not be fetched.",
    NO_RECORD: "No CRM record matches this CSP's contact number and details.",
    NO_ATTACHMENTS: "The CRM record has no documents attached.",
    NO_PHOTO_IN_DOCUMENTS: "None of the attached documents contained a usable photograph.",
    CRM_ERROR: "The CRM could not be reached.",
}


@dataclass
class PhotoResult:
    ok: bool
    path: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = None      # which attachment it came from
    detail: Optional[str] = None

    @property
    def message(self) -> str:
        if self.ok:
            return f"Photo extracted from {os.path.basename(self.source or '')}."
        return REASON_TEXT.get(self.reason, self.detail or "Photo unavailable.")


def photo_directory() -> str:
    directory = os.path.join(settings.document_output_dir, "photos")
    os.makedirs(directory, exist_ok=True)
    return directory


def stored_photo_path(csp_id: str) -> str:
    from app.services.document_service import _safe_folder_name
    return os.path.join(photo_directory(), f"{_safe_folder_name(csp_id)}.png")


@telemetry.traced("find_photo_in_crm", "csp_photo_service")
def fetch_photo(csp) -> PhotoResult:
    """Fetch and store this CSP's photograph from the CRM.

    Returns a PhotoResult. On success the photograph is saved and its path
    returned; the caller is responsible for putting it on the CSP record.
    """
    from app.services import photo_extraction, zoho_client

    if not zoho_client.is_configured():
        return PhotoResult(False, reason=NOT_CONFIGURED)

    try:
        matches = zoho_client.find_csp_records(csp)
        if not matches:
            logger.info(
                "csp_photo_service: no CRM record matched CSP %s in any "
                "module", csp.csp_id,
            )
            return PhotoResult(False, reason=NO_RECORD)

        # A CSP can exist in both modules. sbi_kiosk matches on the code but
        # usually carries nothing; the Lead carries the KYC pack. So every
        # match is tried, not just the first.
        packs = []
        for module, record in matches:
            files = zoho_client.attachments(record["id"], module=module)
            pdfs = [a for a in files
                    if (a.get("File_Name") or "").lower().endswith(".pdf")]
            logger.info(
                "csp_photo_service: CSP %s matched in %s with %d "
                "attachment(s), %d PDF(s)",
                csp.csp_id, module, len(files), len(pdfs),
            )
            if pdfs:
                packs.append((module, record, pdfs))
    except zoho_client.ZohoError as e:
        logger.error("csp_photo_service: CRM error for CSP %s: %s", csp.csp_id, e)
        return PhotoResult(False, reason=CRM_ERROR, detail=str(e))

    if not packs:
        return PhotoResult(False, reason=NO_ATTACHMENTS)

    scratch = tempfile.mkdtemp(prefix=f"kyc_{csp.csp_id}_")
    try:
        last_error = None
        tried_any = False

        for module, record, pdfs in packs:
            # A file named for the photograph is tried on its own first; the
            # rest of the pack is the fallback. A misleading name therefore
            # costs a little time, not a photo.
            named = [a for a in pdfs
                     if PHOTO_NAME_HINT in (a.get("File_Name") or "").lower()]
            rest = [a for a in pdfs if a not in named]

            for attempt in (r for r in (named, rest) if r):
                downloaded = []
                for attachment in attempt:
                    target = os.path.join(scratch, attachment["File_Name"])
                    try:
                        zoho_client.download_attachment(
                            record["id"], attachment["id"], target,
                            module=module)
                        downloaded.append(target)
                    except zoho_client.ZohoError as e:
                        logger.warning(
                            "csp_photo_service: could not download %s: %s",
                            attachment.get("File_Name"), e)

                if not downloaded:
                    continue
                tried_any = True

                destination = stored_photo_path(csp.csp_id)
                try:
                    _, source = photo_extraction.extract_best_photo(
                        downloaded, destination)
                except photo_extraction.PhotoNotFound as e:
                    last_error = e
                    logger.info(
                        "csp_photo_service: CSP %s — nothing usable in %s",
                        csp.csp_id,
                        ", ".join(os.path.basename(d) for d in downloaded))
                    continue

                logger.info(
                    "csp_photo_service: CSP %s — photo taken from %s (%s)",
                    csp.csp_id, os.path.basename(source), module)
                return PhotoResult(True, path=destination, source=source)

        if not tried_any:
            return PhotoResult(False, reason=CRM_ERROR,
                               detail="No attachment could be downloaded.")

        return PhotoResult(False, reason=NO_PHOTO_IN_DOCUMENTS,
                           detail=str(last_error) if last_error else None)

    finally:
        # The KYC pack holds identity documents; none of it is kept.
        shutil.rmtree(scratch, ignore_errors=True)
