"""
CSP DocMaker — Zoho CRM client

Read-only access to the CRM, used to find a CSP and fetch the KYC document
their photograph is extracted from.

Access tokens last an hour and Zoho rate-limits how often a refresh token may
be exchanged, so the token is cached and reused. Minting one per call gets the
integration throttled within minutes — which is exactly what happened while
this was being built.

What the CRM actually looks like, confirmed against the live account:

  * CSPs live in the custom module ``sbi_kiosk`` ("SBI Kiosk Farming").
  * The CSP code is held inconsistently: some records carry it in
    ``CSP_Code1``, others in ``SBI_Code``, and ``CSP_Code1`` sometimes holds a
    different internal number instead. Both fields are therefore checked.
  * Many records have no mobile number at all, so a search by phone cannot be
    the only route to a record.
"""

import logging
import threading
import time
from typing import Dict, List, Optional

import httpx

from app import telemetry
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

MODULE = "sbi_kiosk"

# CSPs are onboarded as Leads, and that is where the KYC pack is attached.
# The sbi_kiosk module holds a record for some of the same codes but carries
# no attachments, so both are consulted.
LEADS_MODULE = "Leads"

# Leads has no CSP-code field at all — the code appears only inside the
# attachment file names. Identity there is therefore the phone number plus a
# second agreeing fact (name or branch code), never the phone alone.
LEAD_PHONE_FIELDS = ("Phone", "Mobile", "Secondary_Phone")

# Fields that identify a CSP. Both code fields are consulted because the CRM
# uses them interchangeably.
CODE_FIELDS = ("CSP_Code1", "SBI_Code")
PHONE_FIELDS = ("Mobile_Number", "Alternate_Mobile_Number", "WhasApp_Number")

# Refreshed a minute early so a long call cannot run past expiry.
TOKEN_SAFETY_MARGIN = 60

_token: Optional[str] = None
_token_expires_at: float = 0.0
_token_lock = threading.Lock()


class ZohoError(RuntimeError):
    """Zoho could not be reached, or refused the request."""


class ZohoNotConfigured(ZohoError):
    """Credentials are missing from the environment."""


def is_configured() -> bool:
    return bool(settings.zoho_client_id
                and settings.zoho_client_secret
                and settings.zoho_refresh_token)


def access_token(force: bool = False) -> str:
    """A valid access token, reusing the cached one until it nears expiry."""
    global _token, _token_expires_at

    if not is_configured():
        raise ZohoNotConfigured(
            "Zoho is not configured — set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET "
            "and ZOHO_REFRESH_TOKEN in backend/.env."
        )

    with _token_lock:
        if not force and _token and time.time() < _token_expires_at:
            return _token

        with telemetry.external_call("zoho", "oauth_token_refresh") as span:
            response = httpx.post(
                f"{settings.zoho_accounts_url}/oauth/v2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.zoho_client_id,
                    "client_secret": settings.zoho_client_secret,
                    "refresh_token": settings.zoho_refresh_token,
                },
                timeout=30.0,
            )
            telemetry.note_http(span, "zoho", "oauth_token_refresh",
                                getattr(response, "status_code", None))
            payload = response.json()

        if "access_token" not in payload:
            error = payload.get("error", payload)
            if str(error) == "Access Denied":
                raise ZohoError(
                    "Zoho refused to refresh the token. This is usually its "
                    "rate limit on token refreshes — wait a few minutes. If it "
                    "persists, the refresh token has been revoked."
                )
            raise ZohoError(f"Could not obtain a Zoho access token: {error}")

        _token = payload["access_token"]
        _token_expires_at = (
            time.time() + int(payload.get("expires_in", 3600)) - TOKEN_SAFETY_MARGIN
        )
        logger.info("zoho_client: obtained a new access token")
        return _token


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """Call the CRM, refreshing the token once if it has gone stale."""
    url = f"{settings.zoho_api_url}{path}"
    for attempt in (1, 2):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Zoho-oauthtoken {access_token(force=attempt == 2)}"
        try:
            # Attempt 2 is the existing "retry once with a fresh token".
            with telemetry.external_call("zoho", f"{method} {path}",
                                         attempt=attempt,
                                         max_attempts=2) as span:
                response = httpx.request(method, url, headers=headers,
                                         timeout=60.0, **kwargs)
                telemetry.note_http(span, "zoho", f"{method} {path}",
                                    getattr(response, "status_code", None))
        except httpx.HTTPError as e:
            raise ZohoError(f"Could not reach Zoho ({path}): {e}") from e

        if response.status_code == 401 and attempt == 1:
            continue          # token expired early; mint a fresh one and retry
        return response

    raise ZohoError(f"Zoho kept rejecting the token for {path}")


def _search(criteria: str) -> List[Dict]:
    response = _request("GET", f"/crm/v2/{MODULE}/search",
                        params={"criteria": criteria})
    if response.status_code == 204:
        return []            # Zoho's "no matches"
    if response.status_code != 200:
        raise ZohoError(
            f"Zoho search failed (HTTP {response.status_code}): "
            f"{response.text[:300]}"
        )
    return response.json().get("data", [])


def find_by_phone(number: str) -> List[Dict]:
    """Records whose phone number matches, across every phone field."""
    digits = "".join(c for c in (number or "") if c.isdigit())[-10:]
    if len(digits) != 10:
        return []
    criteria = "or".join(f"({field}:equals:{digits})" for field in PHONE_FIELDS)
    return _search(f"({criteria})")


def find_by_csp_code(code: str) -> List[Dict]:
    """Records whose CSP code matches, in either field that can hold it."""
    code = (code or "").strip()
    if not code:
        return []
    criteria = "or".join(f"({field}:equals:{code})" for field in CODE_FIELDS)
    return _search(f"({criteria})")


def record_csp_code(record: Dict) -> Optional[str]:
    """The CSP code on a record, from whichever field carries it."""
    for field in CODE_FIELDS:
        value = (record.get(field) or "").strip() if record.get(field) else ""
        # The real code looks like 1A850466; CSP_Code1 sometimes holds a plain
        # internal number instead, which is not what documents are keyed on.
        if value and not value.isdigit():
            return value
    return None


def record_phones(record: Dict) -> set:
    """Every phone number on a record, reduced to ten digits."""
    numbers = {
        "".join(c for c in str(record.get(field) or "") if c.isdigit())[-10:]
        for field in PHONE_FIELDS
    }
    numbers.discard("")
    return numbers


def find_csp(phone: str, expected_code: str) -> Optional[Dict]:
    """Find the CSP, requiring BOTH the code and the phone number to match.

    Confirmed rule: a record is only this CSP when its code matches AND its
    phone matches. Anything less is not proof of identity, and attaching the
    wrong person's document is the failure that matters most here.

    Be aware of what this costs: the CRM and the CSP sheet currently disagree
    about phone numbers, so a CSP whose two records differ is refused and
    handed to the RM rather than guessed at.
    """
    expected = (expected_code or "").strip().upper()
    digits = "".join(c for c in (phone or "") if c.isdigit())[-10:]

    if not expected or len(digits) != 10:
        return None

    # Searched by code because most records carry one, while many have no
    # phone at all; the phone is then verified on whatever comes back.
    for record in find_by_csp_code(expected):
        if (record_csp_code(record) or "").upper() != expected:
            continue

        phones = record_phones(record)
        if digits in phones:
            return record

        logger.warning(
            "zoho_client: CSP %s matched by code but the phone differs "
            "(CRM has %d number(s), none of them the one on record here) — "
            "refusing, the RM will be asked instead",
            expected, len(phones),
        )

    return None


def lead_phones(record: Dict) -> set:
    """Every phone number on a Lead, as last-10-digit strings."""
    numbers = set()
    for field in LEAD_PHONE_FIELDS:
        raw = record.get(field)
        if raw:
            digits = "".join(c for c in str(raw) if c.isdigit())[-10:]
            if len(digits) == 10:
                numbers.add(digits)
    return numbers


def _lead_search(**params) -> List[Dict]:
    """One Leads search, with an empty result for 'nothing found'."""
    response = _request("GET", f"/crm/v2/{LEADS_MODULE}/search", params=params)
    if response.status_code == 204:
        return []
    if response.status_code != 200:
        raise ZohoError(
            f"Lead search failed (HTTP {response.status_code}): "
            f"{response.text[:300]}")
    return response.json().get("data", [])


def _lead_matches(record: Dict, digits: str, name: str, branch: str) -> bool:
    """Two independent facts must agree before a Lead is this CSP.

    Leads carries no CSP code, so identity rests on the facts it does have.
    One alone is never enough: four different Leads are called "Harimohan",
    and a branch has many CSPs. Attaching the wrong person's photograph is
    the failure that matters most here.
    """
    agreed = 0
    if digits and digits in lead_phones(record):
        agreed += 1

    record_name = " ".join(str(record.get("Full_Name")
                               or record.get("Last_Name") or "").split()).lower()
    if name and record_name and name == record_name:
        agreed += 1

    record_branch = str(record.get("Branch_Code") or "").strip().lower()
    if branch and record_branch and branch == record_branch:
        agreed += 1

    return agreed >= 2


def find_lead(phone: str, name: str = "", branch_code: str = "") -> Optional[Dict]:
    """Find this CSP's Lead, where the KYC pack is attached.

    Leads is always consulted — it is where the documents live — and it is
    searched two ways, because either identifier can disagree with the
    sheet. Nitasha's sbi_kiosk record carried a different phone from her
    sheet row, so a phone-only search is not enough on its own.

      1. by phone, then
      2. by name, for a Lead whose phone differs from the sheet.

    Whatever comes back must agree on two facts out of phone, name and
    branch code before it is accepted.
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())[-10:]
    if len(digits) != 10:
        digits = ""
    wanted_name = " ".join((name or "").split()).lower()
    wanted_branch = (branch_code or "").strip().lower()

    if not digits and not wanted_name:
        return None

    seen = set()
    candidates: List[Dict] = []

    if digits:
        candidates.extend(_lead_search(phone=digits))
    if wanted_name:
        candidates.extend(_lead_search(
            criteria=f"(Last_Name:equals:{name.strip()})"))

    rejected = 0
    for record in candidates:
        key = record.get("id")
        if key in seen:
            continue
        seen.add(key)
        if _lead_matches(record, digits, wanted_name, wanted_branch):
            return record
        rejected += 1

    if rejected:
        logger.warning(
            "zoho_client: %d Lead(s) looked like %s but agreed on fewer than "
            "two of phone, name and branch code — refusing",
            rejected, name or digits,
        )
    return None


def find_csp_records(csp) -> List[tuple]:
    """Every CRM record that is this CSP, as (module, record) pairs.

    A CSP can exist in both modules: sbi_kiosk carries the CSP code, Leads
    carries the KYC pack. Returning only the first match was a mistake —
    sbi_kiosk matches on code and phone but usually has no attachments, so
    stopping there would never reach the documents on the Lead. The caller
    tries each in turn and keeps the first that actually yields a photo.

    sbi_kiosk comes first because its code match is the stronger proof of
    identity; Leads follows because that is where the files are.
    """
    found = []

    record = find_csp(csp.mobile or "", csp.csp_id)
    if record is not None:
        found.append((MODULE, record))

    lead = find_lead(csp.mobile or "", csp.name or "",
                     getattr(csp, "branch_code", "") or "")
    if lead is not None:
        found.append((LEADS_MODULE, lead))

    return found


def find_csp_record(csp) -> Optional[tuple]:
    """The single best CRM match, kept for callers that want just one."""
    records = find_csp_records(csp)
    return records[0] if records else None


def attachments(record_id: str, module: str = MODULE) -> List[Dict]:
    """Files attached to a record, newest first."""
    response = _request("GET", f"/crm/v2/{module}/{record_id}/Attachments",
                        params={"per_page": 100})
    if response.status_code == 204:
        return []
    if response.status_code != 200:
        raise ZohoError(
            f"Could not list attachments (HTTP {response.status_code}): "
            f"{response.text[:300]}"
        )
    files = response.json().get("data", [])
    files.sort(key=lambda a: a.get("Modified_Time") or "", reverse=True)
    return files


def download_attachment(record_id: str, attachment_id: str, destination: str,
                        module: str = MODULE) -> str:
    """Download one attachment to disk and return the path."""
    import os

    response = _request(
        "GET", f"/crm/v2/{module}/{record_id}/Attachments/{attachment_id}")
    if response.status_code != 200:
        raise ZohoError(
            f"Could not download attachment {attachment_id} "
            f"(HTTP {response.status_code})"
        )

    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    with open(destination, "wb") as fh:
        fh.write(response.content)
    logger.info("zoho_client: downloaded %s (%d bytes)",
                destination, len(response.content))
    return destination
