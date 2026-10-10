"""
CSP DocMaker — the documents this system can produce

Until this existed the four documents were a Python enum and a Postgres enum,
so adding a fifth meant a code change and a migration. An admin can now add
one by uploading it.

Two things make an uploaded .docx a document this system can issue:

  * Its placeholders, and what fills each one. A template saying "Officer
    Name" means nothing until someone says which field that is. The mapping
    is held here, not in code, and a template with an unmapped placeholder is
    never issued — it would print a blank where a name belongs.

  * Where its photograph goes, if it has one: the exact paragraph text that
    the CSP's photograph replaces.

The four supplied documents are rows here too, marked built-in. Their files
stay on disk where they have always been; an uploaded one is kept in the
database, like every other document this system holds.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

# The four supplied documents, by the code already stored in document_jobs,
# stored_documents and email_documents. These codes must not change.
BUILTIN_CODES = (
    "CSP_ID_CARD",
    "CSP_CERTIFICATE",
    "TRAINING_CERTIFICATE",
    "BCP",
)


class DocumentTemplate(Base):
    __tablename__ = "document_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Which customer this belongs to. NOT NULL everywhere: a row owned by
    # nobody is a row that leaks into whoever queries without a filter.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    # What the rest of the system calls this document. Also the value stored
    # on every job and stored document, so it is the stable identity.
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="What an admin and an RM see this document called",
    )
    # A built-in's file stays on disk; an uploaded one lives here.
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Placeholder text -> the canonical field that fills it. A placeholder
    # present in the file but absent here blocks generation rather than
    # printing an empty space on an official document.
    placeholder_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    # The paragraph whose whole text the photograph replaces, or NULL when
    # this document carries no photograph.
    photo_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # A built-in cannot be deleted: documents already issued refer to it.
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
        comment="Inactive templates are not offered, but stay for history",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<DocumentTemplate {self.code} v{self.version}>"
