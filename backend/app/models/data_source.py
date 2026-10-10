"""
CSP DocMaker — where a workspace's records come from

A customer keeps their data somewhere. For the first one that is a Google
Sheet; the next may have a CSV export, an Excel file, or a database they
already run. None of that should reach the rest of the application, which
cares only about records.

So a data source is configuration: kind, how to connect, how to map its
columns onto fields, how often to read it. Adding a source is a thing a
Super Admin does, not a thing a developer does.

Credentials are deliberately NOT stored here. A connection string with a
password in a JSONB column is a password in a database backup, in a log
line, and on anyone's screen who opens the row. `secret_ref` names an
environment key instead, and the value is read at connection time.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

# What kind of thing a source is.
GOOGLE_SHEET = "google_sheet"
CSV = "csv"
EXCEL = "excel"
POSTGRES = "postgres"
MYSQL = "mysql"

SOURCE_KINDS = (GOOGLE_SHEET, CSV, EXCEL, POSTGRES, MYSQL)

# What a source is FOR. One workspace reads its records from one place and
# its org directory from another, exactly as the first customer does.
PURPOSE_RECORDS = "records"        # the CSPs themselves
PURPOSE_DIRECTORY = "directory"    # who covers which territory (INFO)
PURPOSE_AUTHORIZATION = "authorization"   # who may sign in

PURPOSES = (PURPOSE_RECORDS, PURPOSE_DIRECTORY, PURPOSE_AUTHORIZATION)

# How a sync went, so a Super Admin can see it without reading logs.
OK = "ok"
FAILED = "failed"
NEVER_RUN = "never_run"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="google_sheet | csv | excel | postgres | mysql",
    )
    purpose: Mapped[str] = mapped_column(
        String(40), nullable=False, default=PURPOSE_RECORDS,
        comment="records | directory | authorization",
    )

    # How to reach it. A spreadsheet id and tab, a file path, a host and
    # table — whatever the kind needs. Never a password.
    connection: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    # The environment key holding this source's secret, when it needs one.
    secret_ref: Mapped[str | None] = mapped_column(
        String(120), nullable=True,
        comment="Name of the env var holding the credential; never the value",
    )

    # Source column -> platform field. The one place a customer's vocabulary
    # meets ours.
    column_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )

    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15,
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )

    # What happened last time, so the screen can say so plainly.
    last_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NEVER_RUN,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        # One source per purpose per name within a workspace. Two sources
        # both claiming to be "the records" would make the sync ambiguous.
        UniqueConstraint("workspace_id", "name", name="uq_data_source_name"),
    )

    def __repr__(self) -> str:
        return f"<DataSource {self.kind}:{self.name} ({self.purpose})>"
