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
    jwt_refresh_token_expire_days: int = Field(default=7, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS")

    # ---- OTP ----
    otp_length: int = Field(default=6, alias="OTP_LENGTH")
    otp_expiry_seconds: int = Field(default=300, alias="OTP_EXPIRY_SECONDS")
    otp_max_attempts: int = Field(default=3, alias="OTP_MAX_ATTEMPTS")
    otp_rate_limit_per_minute: int = Field(default=3, alias="OTP_RATE_LIMIT_PER_MINUTE")

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
    whatsapp_platform_timeout_seconds: int = Field(
        default=60, alias="WHATSAPP_PLATFORM_TIMEOUT_SECONDS")
    whatsapp_language: str = Field(default="en_US", alias="WHATSAPP_LANGUAGE")

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


    # ---- AI ----
    ai_provider: str = Field(default="openai", alias="AI_PROVIDER")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="gpt-4", alias="AI_MODEL")
    ai_validation_timeout_seconds: int = Field(default=30, alias="AI_VALIDATION_TIMEOUT_SECONDS")

    # ---- Documents ----
    # Relative paths resolve against the repository root (the backend process
    # runs from backend/, while templates live in <repo>/templates/documents).
    document_templates_dir: str = Field(
        default="../templates/documents", alias="DOCUMENT_TEMPLATES_DIR")
    document_output_dir: str = Field(default="generated_documents", alias="DOCUMENT_OUTPUT_DIR")

    # TEMPORARY: while CSP photos are still being extracted from the CRM,
    # documents are generated with a placeholder photo box. Set to false and
    # the CSP photo becomes required data (missing photo blocks generation).
    # A light, studio-style touch-up of every photo placed on a document
    # (tracker No. 58): colour, contrast, brightness, a little sharpening.
    # Nothing is moved, stretched, added or removed.
    photo_touch_up: bool = Field(default=True, alias="PHOTO_TOUCH_UP")
    # White background + passport framing, made on this machine with the
    # person's real face (tracker No. 67). Used unless an AI portrait is on.
    photo_white_background: bool = Field(default=True,
                                         alias="PHOTO_WHITE_BACKGROUND")
    # The finished photo's size (tracker No. 72). Printed at 35 x 45 mm on
    # the documents; DPI decides how sharp: 500 DPI = 689 x 886 pixels.
    passport_photo_width_mm: float = Field(default=35,
                                           alias="PASSPORT_PHOTO_WIDTH_MM")
    passport_photo_height_mm: float = Field(default=45,
                                            alias="PASSPORT_PHOTO_HEIGHT_MM")
    passport_photo_dpi: int = Field(default=500, alias="PASSPORT_PHOTO_DPI")

    # AI studio portrait by Google Gemini (tracker No. 61). Only used when a
    # key is set; every portrait is face-checked against the CSP's photo.
    photo_ai_portrait: bool = Field(default=True, alias="PHOTO_AI_PORTRAIT")
    # Which service makes it. Cloudflare Workers AI chosen 11 Oct 2026 for
    # its free daily allowance; Gemini kept as the paid alternative.
    # Decided 12 Oct 2026 (tracker No. 70): while the AI portrait is on, a
    # document with a photo WAITS for the agent's portrait rather than going
    # out with a plainer photo. Shown to the RM as a Pending detail.
    photo_require_ai_portrait: bool = Field(
        default=True, alias="PHOTO_REQUIRE_AI_PORTRAIT")
    photo_ai_provider: str = Field(default="cloudflare",
                                   alias="PHOTO_AI_PROVIDER")
    cloudflare_account_id: str = Field(default="",
                                       alias="CLOUDFLARE_ACCOUNT_ID")
    cloudflare_api_token: str = Field(default="", alias="CLOUDFLARE_API_TOKEN")
    cloudflare_image_model: str = Field(
        # The bigger model, chosen 11 Oct 2026 (tracker No. 68) for its
        # studio look. ~1,500 of the 10,000 free daily units per portrait.
        default="@cf/black-forest-labs/flux-2-klein-9b",
        alias="CLOUDFLARE_IMAGE_MODEL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_image_model: str = Field(
        default="gemini-nano-banana-2.1", alias="GEMINI_IMAGE_MODEL")
    gemini_api_base: str = Field(
        default="https://generativelanguage.googleapis.com/v1",
        alias="GEMINI_API_BASE")
    gemini_timeout_seconds: int = Field(default=120,
                                        alias="GEMINI_TIMEOUT_SECONDS")
    # Measured 11 Oct 2026 on the user's samples and the agents' photos:
    # same person 0.84-0.92, different people at most 0.43. OpenCV's own
    # 0.363 would have accepted two different people. Raised from 0.60 to
    # 0.75 the same day (tracker No. 65), then set to 0.60 (No. 68) when the
    # user chose the 9B model's studio look knowing faces come out similar
    # rather than identical (its results: 0.62-0.73). 0.60 still sits well
    # above every pair of different people measured (at most 0.43).
    # The same photo gives a different portrait each time (1A852340 scored
    # 0.85 once, 0.70 the next), so a photo gets a few tries before the
    # original is settled on. Each try uses ~1,500 of Cloudflare's 10,000
    # free daily units with the 9B model.
    photo_ai_attempts: int = Field(default=3, alias="PHOTO_AI_ATTEMPTS")
    face_match_threshold: float = Field(default=0.60,
                                        alias="FACE_MATCH_THRESHOLD")
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
    data_request_expiry_days: int = Field(
        default=7, alias="DATA_REQUEST_EXPIRY_DAYS",
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


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance — loaded once per process."""
    return Settings()
