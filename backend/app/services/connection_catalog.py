"""
CSP DocMaker — each workspace's own connections (PROJECT-REGISTER No. 210,
Stage 3: TK-021 - TK-028, ZU-03)

Which Google Sheets a workspace reads, the email account it sends from, its
WhatsApp channel and its CRM. Read through get_settings() like every
setting (services/workspace_settings.py), so the code that uses them did not
change.

Two rules keep one workspace's data from another's:

  * eko_only — the server's value (from deploy/.env.production) belongs to
    Eko's workspace alone. Any other workspace starts NOT connected (blank)
    until its Super Admin connects its own. Without this, a new workspace
    would read Eko's sheet and send from Eko's address.
  * secret  — passwords and keys are kept encrypted (services/secret_store.py),
    entered once, never shown back, never written to a log, the history or
    the chat.

The Google service account (the robot that reads sheets) stays the
server's: a workspace shares its sheet with that robot's address, as the
setup guide says. The Zoho data centre stays the server's (India).
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

TEXT, INT, BOOL, SECRET, CHOICE = "text", "int", "bool", "secret", "choice"


@dataclass(frozen=True)
class Connection:
    key: str            # the attribute on app.config.Settings
    group: str
    label: str
    help: str
    kind: str = TEXT
    eko_only: bool = False   # other workspaces start blank
    choices: Tuple[str, ...] = ()
    min: int = 0
    max: int = 300
    words: Tuple[str, ...] = ()


GROUPS: List[Tuple[str, str, str]] = [
    ("sheets", "Google Sheets",
     "Share each sheet with the app's robot address (shown below) as an "
     "editor, then paste the sheet's link or id here."),
    ("email", "Email",
     "The account documents and messages are emailed from (SMTP, e.g. "
     "Gmail with an app password)."),
    ("whatsapp", "WhatsApp",
     "The WhatsApp sending platform this workspace uses."),
    ("crm", "CRM (Zoho, optional)",
     "Used to fill a CSP's blank email, address, state, gender and photo."),
]

CONNECTIONS: List[Connection] = [
    # ---- sheets --------------------------------------------------------
    Connection("google_sheets_csp_sheet_id", "sheets", "Main CSP sheet",
               "The sheet with your CSPs (Eko: CSPDATA). Link or id.",
               eko_only=True, words=("csp sheet", "main sheet", "cspdata")),
    Connection("google_sheets_csp_sheet_name", "sheets", "Tab: main records",
               "The tab with one row per record (Eko: KOData).",
               words=("main tab", "ko tab", "records tab")),
    Connection("google_sheets_subko_sheet_name", "sheets",
               "Tab: second record type",
               "Eko: SUBKOData. Leave as it is if you have one tab.",
               words=("subko tab", "second tab")),
    Connection("google_sheets_info_tab_name", "sheets", "Tab: lookup table",
               "Fills office fields by branch / district (Eko: INFO).",
               words=("info tab", "lookup tab")),
    Connection("google_sheets_id", "sheets", "Sign-in list sheet",
               "The sheet with the RMs / Admins / SuperAdmins tabs. Link or id.",
               eko_only=True, words=("sign in sheet", "access sheet",
                                     "authorization sheet")),
    Connection("google_sheets_rm_sheet_name", "sheets", "Sign-in list: RMs tab",
               "Eko: RMs.", words=("rms tab",)),
    Connection("google_sheets_admin_sheet_name", "sheets",
               "Sign-in list: Admins tab", "Eko: Admins.",
               words=("admins tab",)),
    Connection("google_sheets_super_admin_sheet_name", "sheets",
               "Sign-in list: Super Admins tab", "Eko: SuperAdmins.",
               words=("super admins tab",)),
    Connection("calling_sheet_id", "sheets", "Old records sheet (optional)",
               "Eko: the Calling sheet — records already working, checked "
               "by WhatsApp. Link or id.",
               eko_only=True, words=("calling sheet", "old records sheet")),
    Connection("calling_sheet_tab", "sheets", "Tab in the old records sheet",
               "Eko: Calling Sheet New.", words=("calling tab",)),
    Connection("calling_header_row", "sheets",
               "Old records sheet: heading row", "Eko: 2.", kind=INT, min=1,
               max=50, words=("calling header row",)),
    Connection("lead_sheet_id", "sheets", "New records sheet (optional)",
               "Eko: Lead raw data — new CSPs being onboarded. Link or id.",
               eko_only=True, words=("lead sheet", "new records sheet")),
    Connection("lead_sheet_tab", "sheets", "Tab in the new records sheet",
               "Eko: Lead raw data.", words=("lead tab",)),
    Connection("lead_header_row", "sheets", "New records sheet: heading row",
               "Eko: 1.", kind=INT, min=1, max=50,
               words=("lead header row",)),
    Connection("address_sheet_id", "sheets", "Address sheet (optional)",
               "Addresses matched by code into blank address cells. Link or "
               "id.", eko_only=True, words=("address sheet",)),
    Connection("address_sheet_tab", "sheets", "Tab in the address sheet",
               "Eko: Address.", words=("address tab",)),
    # ---- email ---------------------------------------------------------
    Connection("smtp_host", "email", "Mail server",
               "e.g. smtp.gmail.com", eko_only=True,
               words=("mail server", "smtp host", "smtp server")),
    Connection("smtp_port", "email", "Port", "587 for most servers.",
               kind=INT, min=1, max=65535, words=("smtp port",)),
    Connection("smtp_username", "email", "Sign-in address",
               "The email address that signs in to the mail server.",
               eko_only=True, words=("smtp user", "email user",
                                     "email username", "mail user")),
    Connection("smtp_password", "email", "Password",
               "For Gmail: an app password. Kept locked; never shown again.",
               kind=SECRET, eko_only=True),
    Connection("smtp_from_email", "email", "Send from",
               "The address people see (blank = the sign-in address).",
               eko_only=True, words=("from address", "send from",
                                     "sender address")),
    Connection("imap_host", "email", "Inbox server (bounces)",
               "Where bounce notices are read, e.g. imap.gmail.com.",
               words=("imap host", "inbox server")),
    # ---- whatsapp ------------------------------------------------------
    Connection("whatsapp_platform_url", "whatsapp", "WhatsApp platform address",
               "The platform's connection address (Eko: Eko's WhatsApp "
               "Bulk Sender).", eko_only=True,
               words=("whatsapp platform", "whatsapp address",
                      "whatsapp url")),
    Connection("whatsapp_language", "whatsapp", "Template language",
               "The language code the approved templates are in.",
               kind=CHOICE, choices=("en_US", "en", "hi", "en_GB"),
               words=("template language", "whatsapp language")),
    # ---- crm -----------------------------------------------------------
    Connection("zoho_client_id", "crm", "Zoho client id",
               "From the Zoho API console.", eko_only=True,
               words=("zoho client id",)),
    Connection("zoho_client_secret", "crm", "Zoho client secret",
               "Kept locked; never shown again.", kind=SECRET, eko_only=True),
    Connection("zoho_refresh_token", "crm", "Zoho refresh token",
               "Kept locked; never shown again.", kind=SECRET, eko_only=True),
]

BY_KEY: Dict[str, Connection] = {c.key: c for c in CONNECTIONS}
KEYS = frozenset(BY_KEY)
SECRET_KEYS = frozenset(c.key for c in CONNECTIONS if c.kind == SECRET)
GROUP_KEYS = tuple(g[0] for g in GROUPS)
assert len(BY_KEY) == len(CONNECTIONS)
SHEET_ID_KEYS = ("google_sheets_csp_sheet_id", "google_sheets_id",
                 "calling_sheet_id", "lead_sheet_id", "address_sheet_id")


class ConnectionError_(ValueError):
    """A value that cannot be saved; the text says why."""


def blank(c: Connection):
    return 0 if c.kind == INT else (False if c.kind == BOOL else "")


def parse(c: Connection, raw):
    """As typed -> stored value (a sheet link becomes its id)."""
    import re
    if c.kind == INT:
        try:
            v = int(str(raw).strip())
        except ValueError:
            raise ConnectionError_(f"{c.label}: give a number.")
        if not c.min <= v <= c.max:
            raise ConnectionError_(f"{c.label} must be from {c.min} to {c.max}.")
        return v
    if c.kind == BOOL:
        return str(raw).strip().lower() in ("1", "true", "on", "yes")
    t = str(raw if raw is not None else "").strip()
    if c.kind == CHOICE:
        if t not in c.choices:
            raise ConnectionError_(f"{c.label}: choose one of "
                                   + ", ".join(c.choices) + ".")
        return t
    if c.key in SHEET_ID_KEYS:
        m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", t)
        if m:
            t = m.group(1)
        if t and not re.fullmatch(r"[A-Za-z0-9_-]{20,}", t):
            raise ConnectionError_(f"{c.label}: paste the sheet's link or "
                                   "its id.")
    if c.key == "whatsapp_platform_url" and t and not re.match(
            r"^https://", t):
        raise ConnectionError_("The WhatsApp platform address must start "
                               "with https://")
    if len(t) > c.max:
        raise ConnectionError_(f"{c.label} is too long.")
    return t
