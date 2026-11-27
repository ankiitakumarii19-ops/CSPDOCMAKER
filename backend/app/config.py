"""
CSP Document Generation & Email Automation Platform — Configuration

Loads all application settings from environment variables.
Uses pydantic-settings for validation and type safety.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # ---- Application ----
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_secret_key: str = Field(default="changeme", alias="APP_SECRET_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ---- Database ----
    database_host: str = Field(default="localhost", alias="DATABASE_HOST")
    database_port: int = Field(default=5432, alias="DATABASE_PORT")
    database_name: str = Field(default="cspdocmaker", alias="DATABASE_NAME")
    database_user: str = Field(default="cspdocmaker", alias="DATABASE_USER")
    database_password: str = Field(default="cspdocmaker_dev", alias="DATABASE_PASSWORD")
    # Echoing SQL logs bound parameter values (CSP personal data), so it is
    # opt-in and independent of APP_DEBUG.
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """Synchronous URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    # ---- Redis ----
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # ---- JWT ----
    jwt_secret_key: str = Field(default="changeme", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    # How long a sign-in lasts: someone stays signed in until they log out
    # or this many hours pass, whichever is first (No. 100). Replaces
    # JWT_ACCESS_TOKEN_EXPIRE_MINUTES (30 minutes), which signed people out
    # mid-work; a leftover value of that in an env file is ignored.
    session_hours: int = Field(default=24, alias="SESSION_HOURS")
    # A test copy of the app (No. 173): never messages anyone — every
    # WhatsApp is refused and every email but the sign-in code is held, as
    # with EMAILS_PAUSED — and every screen says TEST COPY.
    test_copy: bool = Field(default=False, alias="TEST_COPY")
    # The browser's sign-in cookie (No. 173). A test copy of the app on the
    # same address uses another name so the two sign-ins stay apart.
    session_cookie_name: str = Field(default="cspdm_session",
                                     alias="SESSION_COOKIE_NAME")

    # How often the app takes the pictures in the CSP sheet's Photo column
    # for CSPs it has no photo for (No. 102).
    sheet_photo_minutes: int = Field(default=15, alias="SHEET_PHOTO_MINUTES")

    # Every document as a file too, one folder per CSP code (No. 105). On the
    # server: the `documents` folder in the app's folder. Blank = off.
    documents_archive_dir: str = Field(default="", alias="DOCUMENTS_ARCHIVE_DIR")
    jwt_refresh_token_expire_days: int = Field(default=7, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS")

    # ---- OTP ----
    otp_length: int = Field(default=6, alias="OTP_LENGTH")
    otp_expiry_seconds: int = Field(default=300, alias="OTP_EXPIRY_SECONDS")
    otp_max_attempts: int = Field(default=3, alias="OTP_MAX_ATTEMPTS")
    otp_rate_limit_per_minute: int = Field(default=3, alias="OTP_RATE_LIMIT_PER_MINUTE")

    # ---- Log in with Google (No. 171) ----
    # The OAuth Client ID (type "Web application") from Google Cloud Console.
    # Not a secret: the sign-in page shows it to Google. Blank = no Google
    # button. Google's own check of the address replaces the emailed code.
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")

    # ---- Google Sheets ----
    google_sheets_credentials_file: str = Field(
        default="credentials/google_service_account.json",
        alias="GOOGLE_SHEETS_CREDENTIALS_FILE",
    )
    google_sheets_id: str = Field(default="", alias="GOOGLE_SHEETS_ID")
    google_sheets_rm_sheet_name: str = Field(default="RMs", alias="GOOGLE_SHEETS_RM_SHEET_NAME")
    google_sheets_admin_sheet_name: str = Field(default="Admins", alias="GOOGLE_SHEETS_ADMIN_SHEET_NAME")
    # Eko's internal WhatsApp Bulk Sender (tracker No. 78). Its hosted
    # connection carries Eko's shared key, so none is stored here.
    whatsapp_platform_url: str = Field(
        default="https://indev.eko.in/whatsapp/mcp",
        alias="WHATSAPP_PLATFORM_URL")
    # No. 268: how long to wait for the platform's answer (it may be busy
    # with another team's bulk batch) and how long to wait to reach it.
    whatsapp_platform_timeout_seconds: int = Field(
        default=300, alias="WHATSAPP_PLATFORM_TIMEOUT_SECONDS")
    whatsapp_platform_connect_timeout_seconds: int = Field(
        default=15, alias="WHATSAPP_PLATFORM_CONNECT_TIMEOUT_SECONDS")
    whatsapp_language: str = Field(default="en_US", alias="WHATSAPP_LANGUAGE")
    # The WhatsApp messages screen (tracker No. 110): how often delivered /
    # read / replied is fetched, and for how many days after a send.
    whatsapp_status_minutes: int = Field(
        default=10, alias="WHATSAPP_STATUS_MINUTES")
    whatsapp_status_days: int = Field(default=7, alias="WHATSAPP_STATUS_DAYS")

    # Decided 11 Oct 2026 (tracker No. 53): a CSP is asked for missing
    # details on WhatsApp only, and waits until WhatsApp works rather than
    # being asked by email. Switching this on allows the email fallback.
    csp_data_requests_by_email: bool = Field(
        default=False, alias="CSP_DATA_REQUESTS_BY_EMAIL")
    google_sheets_super_admin_sheet_name: str = Field(
        default="SuperAdmins", alias="GOOGLE_SHEETS_SUPER_ADMIN_SHEET_NAME")
    google_sheets_sync_interval_minutes: int = Field(default=15, alias="GOOGLE_SHEETS_SYNC_INTERVAL_MINUTES")

    # ---- Gmail API ----
    gmail_sender_email: str = Field(default="noreply@eko.co.in", alias="GMAIL_SENDER_EMAIL")
    gmail_credentials_file: str = Field(
        default="credentials/gmail_service_account.json",
        alias="GMAIL_CREDENTIALS_FILE",
    )

    # ---- SMTP Email ----
    email_method: str = Field(
        default="smtp", alias="EMAIL_METHOD",
        description="Email delivery method: 'smtp', 'gmail_api', or 'console'",
    )
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")

    # ---- WhatsApp ----
    # The Eko bulk sender. The KEY ITSELF never appears in code, in the
    # database or in a log line — a message channel stores only the NAME of
    # the variable holding it, and the value is read here at send time.
    whatsapp_api_url: str = Field(
        default="https://indev.eko.in/whatsapp/mcp", alias="WHATSAPP_API_URL")
    whatsapp_api_key: str = Field(default="", alias="WHATSAPP_API_KEY")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_from_email: str = Field(default="", alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="CSP DocMaker", alias="SMTP_FROM_NAME")
    # Asked 22 Oct 2026 (No. 133): while the sending address is being
    # changed, no email goes out — documents, chat emails, anything — except
    # the sign-in codes, so the team can still sign in. Documents that are
    # due simply wait and go out once this is turned off.
    emails_paused: bool = Field(default=False, alias="EMAILS_PAUSED")

    # ---- CSP Google Sheet (live CSP data source) ----
    google_sheets_csp_sheet_id: str = Field(
        default="", alias="GOOGLE_SHEETS_CSP_SHEET_ID",
        description="Google Sheet ID containing live CSP data",
    )
    # Tab in the same CSP spreadsheet listing who covers which LHO, State and
    # District. Used to fill in a CSP row's blank DC / ASM / RM.
    google_sheets_info_tab_name: str = Field(
        default="INFO", alias="GOOGLE_SHEETS_INFO_TAB_NAME")
    # KOs' tab. Renamed by the user from "CSPData" to "KOData" on 11 Oct 2026.
    google_sheets_csp_sheet_name: str = Field(
        default="KOData", alias="GOOGLE_SHEETS_CSP_SHEET_NAME",
        description="Tab holding the KOs (8-character CSP codes)",
    )
    # Sub-KOs' tab (9- or 10-character codes), added 11 Oct 2026. Optional:
    # if the tab does not exist the KOs are still read.
    google_sheets_subko_sheet_name: str = Field(
        default="SUBKOData", alias="GOOGLE_SHEETS_SUBKO_SHEET_NAME",
        description="Tab holding the Sub-KOs",
    )

    def csp_tab_for(self, code: str) -> str:
        """The tab a CSP's row lives in: KOData or SUBKOData, by code."""
        from app.services import ko_level
        return (self.google_sheets_subko_sheet_name
                if ko_level.level_of(code) == ko_level.SUB_KO
                else self.google_sheets_csp_sheet_name)
    csp_sync_interval_minutes: int = Field(default=1, alias="CSP_SYNC_INTERVAL_MINUTES")

    # ---- Where Eko's CSPs come from (tracker No. 121, 21 Oct 2026) ----
    # The Calling sheet lists the CSPs already working (old); "Terminal
    # Status" Inactive or empty means nothing is sent to them. The Lead raw
    # data sheet lists CSPs being onboarded; "Remarks" = LEAD_LIVE_REMARK
    # means live — anything else means still pending, nothing is sent. Rows
    # are copied into CSPDATA (KOData/SUBKOData). Empty ids = switched off.
    calling_sheet_id: str = Field(default="", alias="CALLING_SHEET_ID")
    calling_sheet_tab: str = Field(default="Calling Sheet New",
                                   alias="CALLING_SHEET_TAB")
    calling_header_row: int = Field(default=2, alias="CALLING_HEADER_ROW")
    lead_sheet_id: str = Field(default="", alias="LEAD_SHEET_ID")
    lead_sheet_tab: str = Field(default="Lead raw data",
                                alias="LEAD_SHEET_TAB")
    lead_header_row: int = Field(default=1, alias="LEAD_HEADER_ROW")
    lead_live_remark: str = Field(default="Go Live Done",
                                  alias="LEAD_LIVE_REMARK")
    source_sheets_interval_minutes: int = Field(
        default=5, alias="SOURCE_SHEETS_INTERVAL_MINUTES")

    # ---- the feedback loops (No. 150) --------------------------------
    # Loop 1: a correction to an INFO-filled value seen on this many CSPs
    # becomes a suggestion to fix INFO.
    quality_suggest_min_csps: int = Field(
        default=2, alias="QUALITY_SUGGEST_MIN_CSPS")
    # Loop 2: a WhatsApp that did not reach the phone / an email that
    # bounced — ask the CSP for the right one on the other channel, once,
    # and send again when it is corrected. Off: CONTACT_LOOP_ENABLED=false.
    contact_loop_enabled: bool = Field(default=True,
                                       alias="CONTACT_LOOP_ENABLED")
    contact_loop_minutes: int = Field(default=30, alias="CONTACT_LOOP_MINUTES")
    contact_loop_batch: int = Field(default=10, alias="CONTACT_LOOP_BATCH")
    # No. 164: a WhatsApp the platform failed to send is sent again until it
    # goes (not when the number is not on WhatsApp — the contact loop's).
    resend_failed_enabled: bool = Field(default=True,
                                        alias="RESEND_FAILED_ENABLED")
    resend_failed_minutes: int = Field(default=10, alias="RESEND_FAILED_MINUTES")
    resend_failed_batch: int = Field(default=20, alias="RESEND_FAILED_BATCH")
    # No. 173: email the Super Admins when a sheet read is stuck / failing,
    # an agent keeps failing or WhatsApps are failing — once per problem,
    # again every ALERT_REPEAT_HOURS, and once fixed. Off: ALERTS_ENABLED=false.
    alerts_enabled: bool = Field(default=True, alias="ALERTS_ENABLED")
    alert_minutes: int = Field(default=15, alias="ALERT_MINUTES")
    alert_repeat_hours: int = Field(default=4, alias="ALERT_REPEAT_HOURS")
    alert_agent_failures: int = Field(default=3, alias="ALERT_AGENT_FAILURES")
    alert_whatsapp_failures: int = Field(default=5, alias="ALERT_WHATSAPP_FAILURES")
    # No. 252: Agent health — the bars each agent is held to, whether the
    # agents may make safe improvements by themselves, and the daily
    # summary email (Settings -> Agent health).
    agent_eval_auto_improve: bool = Field(default=True,
                                          alias="AGENT_EVAL_AUTO_IMPROVE")
    agent_eval_min_success: int = Field(default=90,
                                        alias="AGENT_EVAL_MIN_SUCCESS")
    agent_eval_min_result: int = Field(default=80,
                                       alias="AGENT_EVAL_MIN_RESULT")
    agent_eval_min_chat: int = Field(default=70, alias="AGENT_EVAL_MIN_CHAT")
    agent_eval_min_acceptance: int = Field(default=50,
                                           alias="AGENT_EVAL_MIN_ACCEPTANCE")
    agent_eval_summary_on: bool = Field(default=True,
                                        alias="AGENT_EVAL_SUMMARY_ON")
    agent_eval_summary_hour: int = Field(default=9,
                                         alias="AGENT_EVAL_SUMMARY_HOUR")
    # No. 199 (Stage 0): the backup service's note "ok|failed <unix time>
    # <file or why>" (deploy/backup-loop.sh). Blank = no backups here (a
    # laptop), nothing checked. An alert when the last backup failed or the
    # last good one is older than BACKUP_ALERT_HOURS.
    backup_status_file: str = Field(default="", alias="BACKUP_STATUS_FILE")
    backup_alert_hours: int = Field(default=26, alias="BACKUP_ALERT_HOURS")
    # No. 153: the app writes AO / RBO corrections into INFO itself.
    info_auto_fix_enabled: bool = Field(default=True,
                                        alias="INFO_AUTO_FIX_ENABLED")
    info_auto_fix_minutes: int = Field(default=30, alias="INFO_AUTO_FIX_MINUTES")
    # No. 152: the day after the documents, "did you get them? 1 / 2 / 3".
    documents_feedback_enabled: bool = Field(
        default=True, alias="DOCUMENTS_FEEDBACK_ENABLED")
    # No. 159: asked this long after the documents message (was the next day).
    documents_feedback_after_minutes: int = Field(
        default=15, alias="DOCUMENTS_FEEDBACK_AFTER_MINUTES")


    # WhatsApp every old CSP to verify their details (No. 126), gently: a
    # batch every few minutes, in the day only. Only where the Calling sheet
    # is connected (the server).
    verify_old_csps_enabled: bool = Field(default=True,
                                          alias="VERIFY_OLD_CSPS_ENABLED")
    verify_batch_size: int = Field(default=25, alias="VERIFY_BATCH_SIZE")
    verify_interval_minutes: int = Field(default=15,
                                         alias="VERIFY_INTERVAL_MINUTES")
    verify_start_hour: int = Field(default=8, alias="VERIFY_START_HOUR")
    verify_end_hour: int = Field(default=20, alias="VERIFY_END_HOUR")
    verify_stop_after: int = Field(default=5, alias="VERIFY_STOP_AFTER")
    # The temporary Address tab for old CSPs (No. 129): matched by CSP code
    # into the empty Address cells of the CSPs copied in from the Calling
    # sheet. Verification waits until it has been read once.
    address_sheet_id: str = Field(default="", alias="ADDRESS_SHEET_ID")
    address_sheet_tab: str = Field(default="Address", alias="ADDRESS_SHEET_TAB")
    verify_wait_for_address: bool = Field(default=True,
                                          alias="VERIFY_WAIT_FOR_ADDRESS")

    # Email tracking (No. 127): bounce notices are read from the sending
    # Gmail inbox with the SMTP login, every EMAIL_BOUNCE_MINUTES.
    imap_host: str = Field(default="imap.gmail.com", alias="IMAP_HOST")
    email_bounce_minutes: int = Field(default=15, alias="EMAIL_BOUNCE_MINUTES")


    # ---- Documents ----
    # Relative paths resolve against the repository root (the backend process
    # runs from backend/, while templates live in <repo>/templates/documents).
    document_templates_dir: str = Field(
        default="../templates/documents", alias="DOCUMENT_TEMPLATES_DIR")
    document_output_dir: str = Field(default="generated_documents", alias="DOCUMENT_OUTPUT_DIR")
    # No. 242: the signature-and-stamp pictures. default.png is the one in
    # the templates; an LHO with its own (e.g. patna.png) gets that instead.
    signatures_dir: str = Field(default="../templates/signatures", alias="SIGNATURES_DIR")

    # TEMPORARY: while CSP photos are still being extracted from the CRM,
    # documents are generated with a placeholder photo box. Set to false and
    # the CSP photo becomes required data (missing photo blocks generation).
    # A light, studio-style touch-up of every photo placed on a document
    # (tracker No. 58): colour, contrast, brightness, a little sharpening.
    # Nothing is moved, stretched, added or removed.
    photo_touch_up: bool = Field(default=True, alias="PHOTO_TOUCH_UP")
    # White background + passport framing, made on this machine with the
    # person's real face (tracker No. 67).
    photo_white_background: bool = Field(default=True,
                                         alias="PHOTO_WHITE_BACKGROUND")
    # The finished photo's size (tracker No. 72). Printed at 35 x 45 mm on
    # the documents; DPI decides how sharp: 500 DPI = 689 x 886 pixels.
    passport_photo_width_mm: float = Field(default=35,
                                           alias="PASSPORT_PHOTO_WIDTH_MM")
    passport_photo_height_mm: float = Field(default=45,
                                            alias="PASSPORT_PHOTO_HEIGHT_MM")
    passport_photo_dpi: int = Field(default=500, alias="PASSPORT_PHOTO_DPI")

    # The ask-anything chat (tracker No. 114; deterministic since No. 116,
    # 19 Oct 2026 — no AI model). How long a drafted message waits for its
    # Send press.
    assistant_draft_minutes: int = Field(default=30,
                                         alias="ASSISTANT_DRAFT_MINUTES")
    photo_placeholder_allowed: bool = Field(
        default=True, alias="PHOTO_PLACEHOLDER_ALLOWED")

    # ---- Who owns the configuration ----
    #
    # Super Admins are listed here, NOT in the authorization Google Sheet,
    # and deliberately so. A Super Admin is the person who connects a
    # workspace's data sources in the first place — so for a new customer
    # there is no sheet yet to be listed in. Reading them from the sheet
    # would mean a workspace could never be set up from nothing.
    #
    # Everyone else (RMs and Admins) still comes from the sheet, and a Super
    # Admin is who adds them to it.
    super_admin_emails: str = Field(
        default="", alias="SUPER_ADMIN_EMAILS",
        description="NO LONGER USED (11 Oct 2026). Super Admins of Eko SBI "
                    "Kiosk CSP come from the SuperAdmins tab of the "
                    "Authorization sheet. Kept only so an old .env loads.",
    )

    # No. 240 (SaaS upgrade Stage 6): the platform's Supreme Owner(s), above
    # every workspace (the console at /platform). Comma-separated emails.
    # Server setting only — never a workspace setting, a sheet or a screen.
    # Blank = nobody (the console is closed).
    supreme_owner_emails: str = Field(default="", alias="SUPREME_OWNER_EMAILS")

    @property
    def supreme_owners(self) -> tuple[str, ...]:
        return tuple(e.strip().lower() for e in (self.supreme_owner_emails or "").split(",")
                     if e.strip())

    @property
    def super_admins(self) -> tuple[str, ...]:
        return tuple(
            e.strip().lower()
            for e in (self.super_admin_emails or "").split(",")
            if e.strip()
        )

    def is_super_admin(self, email: str) -> bool:
        return (email or "").strip().lower() in self.super_admins

    # ---- The link a CSP is sent to fill in their own details ----
    # Where that page lives, as the CSP's phone will reach it. The default is
    # only good for local testing: a localhost link opens nothing on a phone,
    # so this must be a real reachable address before any request is sent.
    public_app_url: str = Field(
        default="http://localhost:3000", alias="PUBLIC_APP_URL",
        description="Public base URL of the frontend, used to build CSP links",
    )
    # No. 192: 3 days (was 7). An unanswered link that runs out is replaced
    # by a new one, sent again, until the CSP fills it and their documents
    # go (new CSPs: new_csp_worker; old CSPs: verify_old_csps_worker).
    data_request_expiry_days: int = Field(
        default=3, alias="DATA_REQUEST_EXPIRY_DAYS",
        description="How long a CSP's fill-in link stays usable",
    )

    # ---- Zoho CRM (source of the CSP photograph) ----
    # Data centre matters: .in and .com are separate servers holding separate
    # data, and using the wrong one fails with confusing "invalid token" errors.
    zoho_data_centre: str = Field(default="in", alias="ZOHO_DATA_CENTRE")
    zoho_client_id: str = Field(default="", alias="ZOHO_CLIENT_ID")
    zoho_client_secret: str = Field(default="", alias="ZOHO_CLIENT_SECRET")
    # Obtained once by exchanging a Self Client grant code; does not expire.
    zoho_refresh_token: str = Field(default="", alias="ZOHO_REFRESH_TOKEN")

    @property
    def zoho_accounts_url(self) -> str:
        return f"https://accounts.zoho.{self.zoho_data_centre}"

    @property
    def zoho_api_url(self) -> str:
        return f"https://www.zohoapis.{self.zoho_data_centre}"

    # ---- PDF conversion ----
    # LibreOffice headless renders the DOCX templates identically on the
    # Windows development machine and the Linux deployment target. Leave the
    # path empty to auto-detect (PATH, then the standard Windows install dir).
    libreoffice_path: str = Field(default="", alias="LIBREOFFICE_PATH")
    pdf_conversion_timeout_seconds: int = Field(
        default=120, alias="PDF_CONVERSION_TIMEOUT_SECONDS")

    # ---- Email Domain ----
    # Comma-separated: staff sign in from either company domain. The name
    # stays singular so an existing ALLOWED_EMAIL_DOMAIN=eko.co.in keeps
    # working — one value is just a list of one.
    allowed_email_domain: str = Field(
        default="eko.co.in,ekosupport.in", alias="ALLOWED_EMAIL_DOMAIN")

    @property
    def allowed_email_domains(self) -> tuple[str, ...]:
        """Every domain that may sign in, lower-cased and stripped."""
        return tuple(
            part.strip().lstrip("@").lower()
            for part in self.allowed_email_domain.split(",")
            if part.strip()
        )

    def email_domain_allowed(self, email: str) -> bool:
        return (email or "").strip().lower().endswith(
            tuple(f"@{d}" for d in self.allowed_email_domains))

    @property
    def allowed_email_domains_text(self) -> str:
        """For messages: 'eko.co.in or ekosupport.in'."""
        domains = [f"@{d}" for d in self.allowed_email_domains]
        if len(domains) == 1:
            return domains[0]
        return ", ".join(domains[:-1]) + " or " + domains[-1]

    # ---- No. 204 (Stage 1): rules that were fixed in the code, now settings
    # a workspace's Super Admin may change (services/settings_catalog.py).
    # The defaults are exactly the values the code used before, so nothing
    # changes until someone changes them.
    send_time_zone: str = Field(default="+05:30", alias="SEND_TIME_ZONE")
    resend_first_wait_minutes: int = Field(default=30,
                                           alias="RESEND_FIRST_WAIT_MINUTES")
    resend_longest_wait_hours: int = Field(default=4,
                                           alias="RESEND_LONGEST_WAIT_HOURS")
    # No. 237: a failed WhatsApp is never given up on; after this many
    # failed tries to the same number the contact loop takes over
    # (alternate number, then email). Replaces RESEND_GIVE_UP_DAYS.
    resend_handover_tries: int = Field(default=5, alias="RESEND_HANDOVER_TRIES")
    contact_fix_max_tries: int = Field(default=3, alias="CONTACT_FIX_MAX_TRIES")
    whatsapp_not_received_hours: int = Field(
        default=24, alias="WHATSAPP_NOT_RECEIVED_HOURS")
    reply_lookback_hours: int = Field(default=72, alias="REPLY_LOOKBACK_HOURS")
    reply_quiet_minutes: int = Field(default=5, alias="REPLY_QUIET_MINUTES")
    reply_auto_per_day: int = Field(default=3, alias="REPLY_AUTO_PER_DAY")
    documents_link_days: int = Field(default=7, alias="DOCUMENTS_LINK_DAYS")

    # ---- No. 211 (Stage 4): each workspace's own data shape and words ----
    # Defaults = Eko's rules as they were fixed in the code.
    record_type_rule: str = Field(default="code_length", alias="RECORD_TYPE_RULE")
    record_main_lengths: str = Field(default="8", alias="RECORD_MAIN_LENGTHS")
    record_second_lengths: str = Field(default="9,10",
                                       alias="RECORD_SECOND_LENGTHS")
    word_record: str = Field(default="CSP", alias="WORD_RECORD")
    word_owner: str = Field(default="RM", alias="WORD_OWNER")
    word_main_type: str = Field(default="KO", alias="WORD_MAIN_TYPE")
    word_second_type: str = Field(default="Sub-KO", alias="WORD_SECOND_TYPE")
    asked_once_fields: str = Field(default="ao,rbo_name",
                                   alias="ASKED_ONCE_FIELDS")
    crm_fill_fields: str = Field(default="email,address,state,gender",
                                 alias="CRM_FILL_FIELDS")
    lookup_fill_enabled: bool = Field(default=True, alias="LOOKUP_FILL_ENABLED")
    auto_documents_new: bool = Field(default=True, alias="AUTO_DOCUMENTS_NEW")
    # No. 270: ASM and DC are the same person (Eko) - the ASM columns carry
    # the DC's name, email and number.
    asm_from_dc: bool = Field(default=True, alias="ASM_FROM_DC")
    # No. 272-274: a new CSP counts as New on the dashboard for this many
    # months after the app added it.
    new_csp_months: int = Field(default=3, alias="NEW_CSP_MONTHS")
    # No. 270: a later change in the Calling sheet goes into CSPDATA (not a
    # field the CSP gave on their own form).
    calling_sheet_updates: bool = Field(default=True,
                                        alias="CALLING_SHEET_UPDATES")
    # ---- No. 212 (Stage 5): documents ----
    # Documents the second record type never gets (Eko: a Sub-KO never gets
    # the BCP).
    documents_not_for_second_type: str = Field(
        default="BCP", alias="DOCUMENTS_NOT_FOR_SECOND_TYPE")
    # ---- No. 213 (Stage 6): messages ----
    send_days: str = Field(default="mon,tue,wed,thu,fri,sat,sun",
                           alias="SEND_DAYS")
    send_holidays: str = Field(default="", alias="SEND_HOLIDAYS")
    send_max_per_person_day: int = Field(default=0,
                                         alias="SEND_MAX_PER_PERSON_DAY")
    msg_documents_ready: bool = Field(default=True, alias="MSG_DOCUMENTS_READY")
    feedback_wording: str = Field(default="", alias="FEEDBACK_WORDING")
    reply_never_answer_words: str = Field(default="",
                                          alias="REPLY_NEVER_ANSWER_WORDS")
    # ---- No. 214 (Stage 7): jobs, alerts, weekly health, look ----
    # Each background job on / off per workspace, and at most how often
    # (0 = every time the server runs it, as today).
    job_sheet_read_on: bool = Field(default=True, alias="JOB_SHEET_READ_ON")
    job_sheet_read_every: int = Field(default=0, alias="JOB_SHEET_READ_EVERY")
    job_signin_read_on: bool = Field(default=True, alias="JOB_SIGNIN_READ_ON")
    job_signin_read_every: int = Field(default=0, alias="JOB_SIGNIN_READ_EVERY")
    job_records_sheets_on: bool = Field(default=True, alias="JOB_RECORDS_SHEETS_ON")
    job_records_sheets_every: int = Field(default=0, alias="JOB_RECORDS_SHEETS_EVERY")
    job_sheet_photos_on: bool = Field(default=True, alias="JOB_SHEET_PHOTOS_ON")
    job_sheet_photos_every: int = Field(default=0, alias="JOB_SHEET_PHOTOS_EVERY")
    job_delivery_status_on: bool = Field(default=True, alias="JOB_DELIVERY_STATUS_ON")
    job_delivery_status_every: int = Field(default=0, alias="JOB_DELIVERY_STATUS_EVERY")
    job_replies_on: bool = Field(default=True, alias="JOB_REPLIES_ON")
    job_replies_every: int = Field(default=0, alias="JOB_REPLIES_EVERY")
    job_verify_on: bool = Field(default=True, alias="JOB_VERIFY_ON")
    job_verify_every: int = Field(default=0, alias="JOB_VERIFY_EVERY")
    job_contact_loop_on: bool = Field(default=True, alias="JOB_CONTACT_LOOP_ON")
    job_contact_loop_every: int = Field(default=0, alias="JOB_CONTACT_LOOP_EVERY")
    job_resend_on: bool = Field(default=True, alias="JOB_RESEND_ON")
    job_resend_every: int = Field(default=0, alias="JOB_RESEND_EVERY")
    job_info_fix_on: bool = Field(default=True, alias="JOB_INFO_FIX_ON")
    job_info_fix_every: int = Field(default=0, alias="JOB_INFO_FIX_EVERY")
    job_new_records_on: bool = Field(default=True, alias="JOB_NEW_RECORDS_ON")
    job_new_records_every: int = Field(default=0, alias="JOB_NEW_RECORDS_EVERY")
    alert_to: str = Field(default="", alias="ALERT_TO")
    health_email_on: bool = Field(default=True, alias="HEALTH_EMAIL_ON")
    health_email_day: str = Field(default="mon", alias="HEALTH_EMAIL_DAY")
    health_email_hour: int = Field(default=9, alias="HEALTH_EMAIL_HOUR")
    health_email_to: str = Field(default="", alias="HEALTH_EMAIL_TO")
    # No. 237: the daily contact email — messages sent today, how many
    # times each CSP has been contacted, and who cannot be reached and why.
    contact_report_on: bool = Field(default=True, alias="CONTACT_REPORT_ON")
    contact_report_hour: int = Field(default=20, alias="CONTACT_REPORT_HOUR")
    contact_report_to: str = Field(default="", alias="CONTACT_REPORT_TO")
    brand_name: str = Field(default="CSPdocMaker", alias="BRAND_NAME")
    brand_color: str = Field(default="#00B259", alias="BRAND_COLOR")
    # No. 228: the look of the app for everyone in the workspace (Setup →
    # Display). "classic" = the app as it has always looked.
    ui_theme: str = Field(default="classic", alias="UI_THEME")
    # No. 229: the design style (shapes, shadows, surfaces) on top of the
    # look's colours. "standard" = the app as it has always looked.
    ui_style: str = Field(default="standard", alias="UI_STYLE")
    # No. 240 (SaaS upgrade Stage 3): a second brand colour ("" = none, the
    # app as it has always looked) and whether each person may pick their
    # own colours and font on Settings -> Appearance (accessibility choices
    # are always theirs).
    brand_color_2: str = Field(default="", alias="BRAND_COLOR_2")
    allow_personal_look: bool = Field(default=True, alias="ALLOW_PERSONAL_LOOK")
    # ---- No. 215 (Stage 8): going live, test mode, pause all ----
    # The server's value is Eko's (live); any other workspace starts not
    # live (workspace_settings.NOT_EKO_DEFAULTS).
    workspace_live: bool = Field(default=True, alias="WORKSPACE_LIVE")
    pause_all: bool = Field(default=False, alias="PAUSE_ALL")
    test_mode: bool = Field(default=False, alias="TEST_MODE")
    test_mode_phone: str = Field(default="", alias="TEST_MODE_PHONE")
    test_mode_email: str = Field(default="", alias="TEST_MODE_EMAIL")
    # ---- No. 216 (Stage 9): limits per workspace (0 = none, as today) ----
    max_whatsapp_per_day: int = Field(default=0, alias="MAX_WHATSAPP_PER_DAY")
    max_documents_per_day: int = Field(default=0, alias="MAX_DOCUMENTS_PER_DAY")

    # ---- Celery ----
    celery_broker_url: Optional[str] = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: Optional[str] = Field(default=None, alias="CELERY_RESULT_BACKEND")

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or f"redis://{self.redis_host}:{self.redis_port}/1"

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or f"redis://{self.redis_host}:{self.redis_port}/2"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "populate_by_name": True,
        "extra": "ignore",
    }


class WorkspaceSettingsView:
    """The server's settings, as seen by one workspace (No. 204, Stage 1).

    Inside a workspace (a request, or a job run for it), a setting listed
    in services/settings_catalog.py answers with that workspace's own value
    when its Super Admin has set one; otherwise — and for everything else —
    the server's value, which is Eko's value today. Outside any workspace
    (start-up, sign-in before a workspace is chosen) it is the server's
    value. Writing an attribute (tests do) writes the server's value.
    """

    __slots__ = ("_base",)

    def __init__(self, base: Settings):
        object.__setattr__(self, "_base", base)

    def __getattr__(self, name):
        base = object.__getattribute__(self, "_base")
        value = getattr(base, name)
        if name in _workspace_keys():
            from app.services import workspace_settings
            own = workspace_settings.own_value(name)
            if own is not workspace_settings.MISSING:
                return own
        return value

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_base"), name, value)

    def __delattr__(self, name):
        delattr(object.__getattribute__(self, "_base"), name)

    @property
    def server(self) -> Settings:
        """The server's own values, never a workspace's (Eko's value)."""
        return object.__getattribute__(self, "_base")


_KEYS = None


def _workspace_keys():
    global _KEYS
    if _KEYS is None:
        from app.services.connection_catalog import KEYS as CONNECTIONS
        from app.services.settings_catalog import KEYS
        _KEYS = KEYS | CONNECTIONS
    return _KEYS


@lru_cache()
def get_settings() -> WorkspaceSettingsView:
    """Cached settings — loaded once per process; workspace-aware (No. 204)."""
    return WorkspaceSettingsView(Settings())
