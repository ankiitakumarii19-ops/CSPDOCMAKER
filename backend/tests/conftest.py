"""Shared fixtures.

DB-backed tests run against a dedicated database (TEST_DATABASE_NAME,
default cspdocmaker_test) that is migrated with Alembic to head — never the
development database.
"""

import os
import uuid
import subprocess
import sys
import tempfile

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_NAME", "cspdocmaker_test")
# Must be set before any app module creates its engine/settings.
os.environ["DATABASE_NAME"] = TEST_DB
os.environ["APP_ENV"] = "development"
os.environ["EMAIL_METHOD"] = "console"
os.environ["SMS_PROVIDER"] = "stub"
# Pinned so the suite does not change behaviour with the developer's .env.
# Tests that care about photos being required turn this off themselves.
os.environ["PHOTO_PLACEHOLDER_ALLOWED"] = "true"
# Never reach the real Zoho account from the suite (No. 124 asks Zoho before
# messaging a CSP). Tests that need Zoho put a stand-in in its place.
os.environ["ZOHO_CLIENT_ID"] = ""
os.environ["ZOHO_CLIENT_SECRET"] = ""
os.environ["ZOHO_REFRESH_TOKEN"] = ""
# The developer's .env may pause emails (No. 133); the suite tests sending
# with it off, and the pause tests turn it on themselves.
os.environ["EMAILS_PAUSED"] = "false"
# Test runs write their logs and traces to a throwaway folder.
import tempfile as _tempfile
os.environ["LOG_DIR"] = _tempfile.mkdtemp(prefix="cspdocmaker-test-logs-")
# Generated documents go to a throwaway directory, never the dev output dir.
os.environ.setdefault(
    "DOCUMENT_OUTPUT_DIR",
    os.path.join(tempfile.gettempdir(), "cspdocmaker_test_documents"),
)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _recreate_test_db() -> bool:
    import psycopg2
    from app.config import get_settings
    s = get_settings()
    try:
        conn = psycopg2.connect(
            host=s.database_host, port=s.database_port, user=s.database_user,
            password=s.database_password, dbname="postgres", connect_timeout=3,
        )
    except psycopg2.OperationalError:
        return False
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn.close()
    return True


@pytest.fixture(scope="session")
def migrated_db():
    if not _recreate_test_db():
        pytest.skip("PostgreSQL not reachable — start it with `docker compose up -d`")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR, check=True, capture_output=True,
    )
    yield


# Every test runs inside the workspace the migration seeds. Production
# sets this per request or per worker task; the tests set it once, because
# a row cannot be written without knowing whose it is.
DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def _in_default_workspace(migrated_db):
    from app.workspace_context import workspace
    with workspace(DEFAULT_WORKSPACE_ID):
        yield


@pytest.fixture(autouse=True)
def _no_photos_from_the_real_sheet(monkeypatch):
    """Getting a photo tries the live CSP sheet first (No. 99). Tests never
    download it: the sheet holds no photos unless a test says otherwise."""
    from app.services import sheet_photo_reader
    empty = sheet_photo_reader.SheetPhotos(pictures={}, ambiguous={},
                                           codes=set())
    monkeypatch.setattr(sheet_photo_reader, "sheet_photos",
                        lambda refresh=False: empty)


@pytest.fixture
async def db(migrated_db):
    from sqlalchemy import text
    from app.database import async_session_factory
    async with async_session_factory() as session:
        await session.execute(text(
            "TRUNCATE audit_logs, validation_results, sms_jobs, email_jobs, "
            "stored_documents, document_jobs, processing_jobs, csp_records, "
            "users, authorization_records, workspace_members "
            "RESTART IDENTITY CASCADE"
        ))
        await session.commit()
        yield session


# A byte string that is a real, if minimal, PDF: enough for the strictness
# checks in pdf_service and document_storage_service to accept it.
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


@pytest.fixture
def stub_pdf_conversion(monkeypatch):
    """Replace LibreOffice with a stub that writes a minimal PDF.

    Workflow tests are about the workflow — generate, validate, store, send —
    and must give the same result on a machine with LibreOffice and one
    without. Real conversion is covered in test_pdf_service.py, which skips
    when LibreOffice is absent.
    """
    from pathlib import Path
    from app.services import pdf_service

    def fake_convert_all(docx_paths, output_dir=None):
        pairs = []
        for docx_path in docx_paths:
            pdf_path = Path(docx_path).with_suffix(".pdf")
            if output_dir:
                pdf_path = Path(output_dir) / pdf_path.name
            pdf_path.write_bytes(MINIMAL_PDF)
            pairs.append((docx_path, str(pdf_path)))
        return pairs

    monkeypatch.setattr(pdf_service, "convert_all", fake_convert_all)
    return fake_convert_all


@pytest.fixture
async def client(migrated_db):
    import httpx
    from app.main import app
    transport = httpx.ASGITransport(app=_AutoMember(app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---- signed-in test users are members of the test workspace -------------
#
# Every request is now checked against `workspace_members`. Most tests mint
# a token for a made-up user and care about something else entirely, so the
# `client` fixture makes that user a member of the default workspace, with
# the role on their token — exactly what signing up would have done.
# Tests about membership itself use `strict_client`, which does none of this.

class _AutoMember:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope.get("headers") or []).get(b"authorization", b"")
            if auth.lower().startswith(b"bearer "):
                await _ensure_member(auth.split(b" ", 1)[1].decode().strip())
        await self.app(scope, receive, send)


async def _ensure_member(token: str) -> None:
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.enums import UserRole
    from app.models.workspace_member import WorkspaceMember
    from app.services import jwt_service
    from app.workspace_context import all_workspaces

    claims = jwt_service.decode_token(token) or {}
    email, role = (claims.get("sub") or "").lower(), claims.get("role")
    if not email or role not in {r.value for r in UserRole} or claims.get("ws"):
        return
    async with async_session_factory() as session:
        with all_workspaces():
            row = (await session.execute(select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == DEFAULT_WORKSPACE_ID,
                WorkspaceMember.email == email))).scalars().first()
            if row is None:
                session.add(WorkspaceMember(
                    workspace_id=DEFAULT_WORKSPACE_ID, email=email,
                    role=UserRole(role), active=True))
            elif row.role.value != role or not row.active:
                row.role, row.active = UserRole(role), True
            else:
                return
            await session.commit()


@pytest.fixture
async def strict_client(migrated_db):
    import httpx
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
