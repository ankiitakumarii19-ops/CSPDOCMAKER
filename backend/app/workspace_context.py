"""
CSP DocMaker — which workspace the current work belongs to

Isolation that depends on every query remembering a filter is isolation that
fails the first time somebody is in a hurry. There are sixty queries in this
application and there will be more.

So the workspace is ambient. A request, or a worker task, says once which
workspace it is acting for, and from then on:

  * every row inserted gets that workspace_id without the caller passing it;
  * every SELECT against a scoped table is filtered to it automatically.

Both are enforced here rather than at each call site. A query that forgets
is not a leak, because there is nothing to forget.

Reading across workspaces is possible, but only by asking for it explicitly
through `all_workspaces()` — which is deliberately ugly to write and easy to
find in a review.
"""

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# The workspace every query in this task or request belongs to.
_current: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "current_workspace_id", default=None,
)
# Set while a caller has deliberately asked to see across workspaces.
_unscoped: ContextVar[bool] = ContextVar("workspace_unscoped", default=False)


class WorkspaceNotSet(RuntimeError):
    """Something tried to act without saying which workspace it was for."""


def current_workspace_id() -> Optional[uuid.UUID]:
    """The workspace in force, or None."""
    return _current.get()


def require_workspace_id() -> uuid.UUID:
    """The workspace in force. Raises rather than guessing.

    Guessing would mean writing one customer's row into another's workspace,
    which is worse than failing loudly.
    """
    workspace_id = _current.get()
    if workspace_id is None:
        raise WorkspaceNotSet(
            "No workspace is set for this operation. Wrap it in "
            "`with workspace(id):` — a row cannot be written without knowing "
            "whose it is."
        )
    return workspace_id


def is_unscoped() -> bool:
    return _unscoped.get()


@contextmanager
def workspace(workspace_id):
    """Act as this workspace for the duration of the block."""
    if isinstance(workspace_id, str):
        workspace_id = uuid.UUID(workspace_id)
    token = _current.set(workspace_id)
    try:
        yield workspace_id
    finally:
        _current.reset(token)


@contextmanager
def all_workspaces():
    """See across every workspace.

    For the few things that genuinely span customers: the scheduler deciding
    which workspaces to sync, and platform-level reporting. Never for
    anything reached from a request.
    """
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)


def default_workspace_id() -> Optional[uuid.UUID]:
    """The workspace a new row belongs to, for SQLAlchemy column defaults.

    Returns None when nothing is set, which lets the NOT NULL constraint do
    the complaining — a clearer error than a silent misfile.
    """
    return _current.get()


# ---- making it automatic -------------------------------------------------

def install() -> None:
    """Filter every SELECT on a scoped table to the workspace in force.

    This is the half that stops leaks. Without it, isolation would depend on
    sixty queries each remembering a WHERE clause, and on every query written
    after today remembering it too.

    Uses SQLAlchemy's orm_execute hook with with_loader_criteria, so the
    filter is applied to the entity wherever it appears — including inside
    joins and eager loads, which a hand-written WHERE on the outer query
    would miss.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session, with_loader_criteria

    # Listened for on Session itself rather than one factory: an
    # AsyncSession wraps a sync Session, and the Celery workers build their
    # own sessions entirely. Scoping has to cover all of them, not just the
    # ones the API happens to create.
    @event.listens_for(Session, "do_orm_execute")
    def _scope(state):
        # Imported inside the handler: at install time this module is being
        # loaded BY app.database, so Base does not exist yet.
        from app.database import Base

        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        if is_unscoped():
            return
        workspace_id = current_workspace_id()
        if workspace_id is None:
            # Nothing set: leave the query alone rather than silently
            # returning an empty result, which would look like missing data
            # rather than a missing workspace.
            return

        for mapper in Base.registry.mappers:
            entity = mapper.class_
            if not hasattr(entity, "workspace_id"):
                continue
            state.statement = state.statement.options(
                with_loader_criteria(
                    entity,
                    lambda cls: cls.workspace_id == workspace_id,
                    include_aliases=True,
                )
            )

    logger.info("workspace_context: query scoping installed on Session")


def scoped_entities() -> list:
    """Every model that carries a workspace. Used by the isolation test."""
    from app.database import Base

    return sorted(
        (m.class_.__name__ for m in Base.registry.mappers
         if hasattr(m.class_, "workspace_id")),
    )


# ---- resolving the workspace for one request -----------------------------

async def resolve_for_email(session, email: str):
    """Which workspace this person acts in.

    Two ways, in order:

      1. Their user row says so. This is everyone who has signed up.
      2. They own a workspace. A Super Admin is configured before they
         register, so on their first visit there is no user row yet — but
         there is a workspace with their address on it.

    Returns None when neither applies, which leaves the request unscoped
    and therefore unable to write. That is the right failure: better a
    clear refusal than a row filed under the wrong customer.
    """
    from sqlalchemy import select

    from app.models.user import User
    from app.models.workspace import Workspace

    address = (email or "").strip().lower()
    if not address:
        return None

    with all_workspaces():
        user = (await session.execute(
            select(User).where(func_lower(User.email) == address)
        )).scalars().first()
        if user is not None and user.workspace_id:
            return user.workspace_id

        owned = (await session.execute(
            select(Workspace)
            .where(func_lower(Workspace.owner_email) == address,
                   Workspace.active.is_(True))
            .order_by(Workspace.created_at)
        )).scalars().first()
        if owned is not None:
            return owned.id

    return None


def func_lower(column):
    from sqlalchemy import func

    return func.lower(column)
