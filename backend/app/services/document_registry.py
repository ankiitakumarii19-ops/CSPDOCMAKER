"""
CSP DocMaker — what documents exist, read from configuration

Until now the four documents were a Python enum and five dictionaries keyed
by it: the template filename, the placeholder map, the photo marker, the
display label, the output filename. Adding a fifth document meant editing
all five and shipping code.

Those dictionaries are now rows in `document_templates`, and this is where
the rest of the application asks about them. A document an admin uploaded
this morning answers exactly like one that shipped with the system.

Two things worth knowing:

  * It is read through a short cache. Generation asks about a document
    several times per run, and a round trip per question would be silly.
    An admin's change takes effect within CACHE_SECONDS, or immediately via
    invalidate().

  * It is workspace-aware. Two customers may both have a document coded
    CSP_CERTIFICATE and they are not the same document.

The four supplied documents still exist as `DocumentType` members, because
their codes are stored on every job and document ever produced. The enum is
now a convenience for referring to them, not the list of what exists.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.models.enums import DocumentType
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30


@dataclass
class DocumentSpec:
    """Everything the pipeline needs to know about one document."""

    code: str
    name: str
    active: bool = True
    is_builtin: bool = False
    version: int = 1
    filename: Optional[str] = None
    file_data: Optional[bytes] = None
    photo_marker: Optional[str] = None
    placeholder_map: Dict[str, str] = field(default_factory=dict)

    @property
    def fields(self) -> set:
        """The canonical fields this document prints."""
        return set(self.placeholder_map.values())

    @property
    def has_photo(self) -> bool:
        return bool(self.photo_marker)

    @property
    def output_prefix(self) -> str:
        """What its generated file is called, before the CSP code.

        Derived from the code rather than configured: CSP_ID_CARD becomes
        CSP_Id_Card. One less thing for an admin to have to fill in.
        """
        return "_".join(part.capitalize() if not part.isupper() or len(part) > 3
                        else part
                        for part in self.code.split("_"))


# workspace id -> (loaded_at, {code: spec})
_cache: Dict[Optional[uuid.UUID], tuple] = {}


def invalidate(workspace_id=None) -> None:
    """Forget what was loaded, so the next question re-reads the database."""
    if workspace_id is None:
        _cache.clear()
    else:
        _cache.pop(workspace_id, None)


def code_of(doc_type) -> str:
    """The stored code for a document, however it was referred to.

    Accepts a DocumentType member, its name, or a plain string — callers
    have all three, and a document that arrived by upload only has the
    third.
    """
    if isinstance(doc_type, DocumentType):
        return doc_type.name
    text = str(doc_type or "").strip()
    # 'csp_id_card' and 'CSP_ID_CARD' are the same document.
    for member in DocumentType:
        if text.lower() in (member.name.lower(), member.value.lower()):
            return member.name
    return text.upper()


def _load() -> Dict[str, DocumentSpec]:
    """Read this workspace's documents, through the cache."""
    workspace_id = current_workspace_id()
    cached = _cache.get(workspace_id)
    if cached and (time.monotonic() - cached[0]) < CACHE_SECONDS:
        return cached[1]

    specs = _read_from_database()
    if specs is None:
        # The database is unreachable, or we are running somewhere that has
        # none. Fall back to the supplied four rather than claiming this
        # system can produce no documents at all.
        specs = _builtin_specs()
    _cache[workspace_id] = (time.monotonic(), specs)
    return specs


def _read_from_database() -> Optional[Dict[str, DocumentSpec]]:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.document_template import DocumentTemplate

    try:
        engine = create_engine(
            get_settings().database_url.replace(
                "postgresql+asyncpg://", "postgresql+psycopg2://"),
            pool_pre_ping=True,
        )
        with Session(engine) as session:
            rows = session.execute(select(DocumentTemplate)).scalars().all()
            builtins = _builtin_specs()
            specs = {}
            for row in rows:
                # A supplied document's row is seeded with its name and file
                # only — a migration cannot read a .docx to learn its
                # placeholders. Where the row has not been filled in yet,
                # the code's own description of it stands in, so generation
                # never depends on a reconcile having run first.
                fallback = builtins.get(row.code)
                specs[row.code] = DocumentSpec(
                    code=row.code,
                    name=row.name,
                    active=row.active,
                    is_builtin=row.is_builtin,
                    version=row.version or 1,
                    filename=row.filename or (
                        fallback.filename if fallback else None),
                    file_data=bytes(row.file_data) if row.file_data else None,
                    photo_marker=row.photo_marker or (
                        fallback.photo_marker if fallback else None),
                    placeholder_map=dict(row.placeholder_map or {}) or (
                        dict(fallback.placeholder_map) if fallback else {}),
                )
        engine.dispose()
        return specs or None
    except Exception as e:
        logger.warning(
            "document_registry: could not read document_templates (%s: %s) — "
            "falling back to the supplied four", type(e).__name__, e,
        )
        return None


def _builtin_specs() -> Dict[str, DocumentSpec]:
    """The four supplied documents, as the code has always described them."""
    from app.services import template_service as ts

    return {
        member.name: DocumentSpec(
            code=member.name,
            name=ts.BUILTIN_LABELS.get(member, member.name),
            is_builtin=True,
            filename=ts.TEMPLATE_FILES.get(member),
            photo_marker=ts.PHOTO_MARKERS.get(member),
            placeholder_map=dict(ts.PLACEHOLDER_FIELDS.get(member, {})),
        )
        for member in DocumentType
    }


# ---- what the rest of the application asks -------------------------------

def get(doc_type) -> DocumentSpec:
    """One document's configuration. Raises if nobody has configured it."""
    code = code_of(doc_type)
    spec = _load().get(code)
    if spec is None:
        known = ", ".join(sorted(_load())) or "none"
        raise KeyError(
            f"No document is configured with the code {code!r}. "
            f"Configured: {known}."
        )
    return spec


def exists(doc_type) -> bool:
    return code_of(doc_type) in _load()


def all_specs(active_only: bool = False) -> List[DocumentSpec]:
    specs = sorted(_load().values(), key=lambda s: s.name)
    return [s for s in specs if s.active] if active_only else specs


def codes(active_only: bool = False) -> List[str]:
    """Every document this workspace can issue.

    Replaces `list(DocumentType)`, which could only ever name four.
    """
    return [s.code for s in all_specs(active_only=active_only)]


def label(doc_type) -> str:
    try:
        return get(doc_type).name
    except KeyError:
        return code_of(doc_type)


def placeholder_map(doc_type) -> Dict[str, str]:
    return dict(get(doc_type).placeholder_map)


def photo_marker(doc_type) -> Optional[str]:
    return get(doc_type).photo_marker


def has_photo(doc_type) -> bool:
    try:
        return get(doc_type).has_photo
    except KeyError:
        return False
