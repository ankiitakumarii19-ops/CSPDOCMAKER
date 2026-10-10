"""
CSP DocMaker — a workspace

One customer's world. Everything belongs to exactly one: their records,
their documents, their templates, their data sources, their people.

The hierarchy:

    Workspace  "SBI Kiosk CSP"
      owner    a Super Admin — the person who set it up
      people   the Admins and RMs that owner added
      sources  where their records come from (sheet, CSV, Excel, database)
      storage  where their generated documents go
      records  their CSPs, documents, jobs, alerts

Nothing in one workspace is reachable from another. That is not a policy
applied at each query — it is a column on every table and a filter applied
in one place, because isolation that depends on somebody remembering is
isolation that fails the first time somebody is in a hurry.

Two configurable things live here rather than in the environment, because
they differ per customer rather than per deployment:

  * where a workspace's records are read FROM — its data sources;
  * where its generated documents are written TO — Postgres today, and
    anywhere else a customer insists on.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The workspace every existing row belongs to. The system ran for one
# customer before workspaces existed, and all of that data is theirs.
DEFAULT_SLUG = "sbi-kiosk-csp"
DEFAULT_NAME = "Eko SBI Kiosk CSP"

# Where a workspace's generated documents are kept.
STORAGE_POSTGRES = "postgres"
STORAGE_GOOGLE_DRIVE = "google_drive"
STORAGE_S3 = "s3"
STORAGE_LOCAL = "local"

STORAGE_CHOICES = (
    STORAGE_POSTGRES,
    STORAGE_GOOGLE_DRIVE,
    STORAGE_S3,
    STORAGE_LOCAL,
)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True,
        comment="Stable, URL-safe identifier; never reused",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # The Super Admin who created it. Their Admins and RMs hang off the
    # workspace, not off them, so a workspace survives its owner leaving.
    owner_email: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
    )

    # Where this workspace's generated documents are written. Postgres is
    # the default because it is what the system already does and what is
    # already proven; a customer who insists on their own Drive or bucket
    # changes this rather than changing code.
    document_storage: Mapped[str] = mapped_column(
        String(40), nullable=False, default=STORAGE_POSTGRES,
        comment="postgres | google_drive | s3 | local",
    )
    # Whatever that destination needs — a folder id, a bucket, a path.
    # Credentials are NOT kept here; they stay in the environment.
    storage_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )

    # Everything else a workspace can be configured with that does not yet
    # deserve a column of its own.
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Workspace {self.slug}>"
