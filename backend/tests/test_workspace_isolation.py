# -*- coding: utf-8 -*-
"""One customer must never see another's data.

This is the test the whole multi-tenant design exists to satisfy. Everything
else — configurable templates, configurable sources, self-service signup —
is only safe if this holds.

It is deliberately written against the real database with two real
workspaces, not against mocks. Isolation that works in a unit test and not
in Postgres is not isolation.
"""

import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.document_template import DocumentTemplate
from app.models.workspace import Workspace
from app.workspace_context import (
    WorkspaceNotSet, all_workspaces, current_workspace_id,
    require_workspace_id, scoped_entities, workspace,
)
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")

OTHER_ID = uuid.UUID("00000000-0000-4000-8000-0000000000ff")


@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    yield engine
    engine.dispose()


@pytest.fixture
def two_workspaces(_engine):
    """The seeded workspace, plus a second customer with their own data."""
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE data_requests, rm_alerts, stored_documents, "
            "csp_records RESTART IDENTITY CASCADE"))
        session.execute(text(
            "DELETE FROM document_templates WHERE workspace_id = :w"
        ).bindparams(w=OTHER_ID))
        session.execute(text("DELETE FROM workspaces WHERE id = :w")
                        .bindparams(w=OTHER_ID))
        session.add(Workspace(
            id=OTHER_ID, slug="acme-insurance", name="ACME Insurance",
            owner_email="owner@acme.example", document_storage="postgres",
        ))
        session.commit()

        # One CSP in each, deliberately sharing a code.
        for ws, name in ((DEFAULT_WORKSPACE_ID, "Ours"),
                         (OTHER_ID, "Theirs")):
            with workspace(ws):
                session.add(CSPRecord(csp_id="SHARED-001", name=name,
                                      origin="new"))
                session.commit()
        yield session

        session.execute(text("DELETE FROM workspaces WHERE id = :w")
                        .bindparams(w=OTHER_ID))
        session.commit()


# ---- the property that matters ------------------------------------------

async def test_a_workspace_sees_only_its_own_records(two_workspaces):
    session = two_workspaces
    with workspace(DEFAULT_WORKSPACE_ID):
        rows = session.execute(select(CSPRecord)).scalars().all()
        assert [r.name for r in rows] == ["Ours"]

    with workspace(OTHER_ID):
        rows = session.execute(select(CSPRecord)).scalars().all()
        assert [r.name for r in rows] == ["Theirs"]


async def test_the_same_code_can_exist_in_two_workspaces(two_workspaces):
    """Two customers may both have a record numbered SHARED-001."""
    session = two_workspaces
    with all_workspaces():
        rows = session.execute(
            select(CSPRecord).where(CSPRecord.csp_id == "SHARED-001")
        ).scalars().all()
    assert len(rows) == 2


async def test_asking_for_another_workspaces_record_by_id_finds_nothing(
    two_workspaces,
):
    """The filter is applied to the query, so a guessed id does not help."""
    session = two_workspaces
    with workspace(OTHER_ID):
        theirs = session.execute(select(CSPRecord)).scalars().one()
        their_pk = theirs.id

    with workspace(DEFAULT_WORKSPACE_ID):
        found = session.execute(
            select(CSPRecord).where(CSPRecord.id == their_pk)
        ).scalars().first()
    assert found is None, "a record was reached across workspaces by its id"


async def test_a_new_row_lands_in_the_workspace_in_force(two_workspaces):
    session = two_workspaces
    with workspace(OTHER_ID):
        session.add(CSPRecord(csp_id="ACME-1", name="New", origin="new"))
        session.commit()
        assert session.execute(select(CSPRecord)).scalars().all().__len__() == 2

    with workspace(DEFAULT_WORKSPACE_ID):
        names = [r.name for r in session.execute(select(CSPRecord)).scalars()]
        assert "New" not in names


async def test_templates_are_isolated_too(two_workspaces):
    """A customer's documents are theirs; nobody else edits or sees them."""
    session = two_workspaces
    with workspace(OTHER_ID):
        session.add(DocumentTemplate(
            code="EMPLOYEE_ID", name="Employee ID", placeholder_map={}))
        session.commit()
        codes = {t.code for t in
                 session.execute(select(DocumentTemplate)).scalars()}
        assert codes == {"EMPLOYEE_ID"}

    with workspace(DEFAULT_WORKSPACE_ID):
        codes = {t.code for t in
                 session.execute(select(DocumentTemplate)).scalars()}
        assert "EMPLOYEE_ID" not in codes
        assert "CSP_ID_CARD" in codes


# ---- the escape hatch is deliberate and narrow --------------------------

async def test_seeing_across_workspaces_takes_an_explicit_request(
    two_workspaces,
):
    session = two_workspaces
    with workspace(DEFAULT_WORKSPACE_ID):
        assert len(session.execute(select(CSPRecord)).scalars().all()) == 1
        with all_workspaces():
            assert len(session.execute(select(CSPRecord)).scalars().all()) == 2


# ---- the context itself --------------------------------------------------

async def test_the_workspace_is_restored_after_the_block():
    with workspace(DEFAULT_WORKSPACE_ID):
        with workspace(OTHER_ID):
            assert current_workspace_id() == OTHER_ID
        assert current_workspace_id() == DEFAULT_WORKSPACE_ID


async def test_acting_without_a_workspace_raises_rather_than_guessing():
    """Guessing would write one customer's row into another's workspace."""
    from app import workspace_context

    token = workspace_context._current.set(None)
    try:
        with pytest.raises(WorkspaceNotSet):
            require_workspace_id()
    finally:
        workspace_context._current.reset(token)


async def test_a_string_id_is_accepted():
    with workspace(str(OTHER_ID)):
        assert current_workspace_id() == OTHER_ID


# ---- nothing tenant-bearing escapes the net -----------------------------

async def test_every_table_holding_customer_data_is_scoped():
    """A new model carrying customer data must carry a workspace too.

    If this fails, something was added without a workspace_id — and it will
    be visible to every customer until somebody notices.
    """
    expected = {
        "AgentFinding", "AgentRun", "AgentState", "AuditLog",
        "AuthorizationRecord", "CSPPhoto", "CSPRecord", "Dashboard", "DataRequest",
        "DataSource", "DocumentTemplate", "EmailJob", "MessageCampaign",
        "MessageChannel", "MessageTemplate", "ProcessingJob", "RMAlert",
        "StoredDocument", "SyncRun", "User", "WhatsAppMessage", "WorkspaceMember",
    }
    # DashboardWidget is deliberately absent: it is reached only through the
    # dashboard that owns it, which is scoped. Denormalising the workspace
    # onto it would give two places for one answer.
    assert set(scoped_entities()) == expected, (
        "the set of workspace-scoped models changed — if a model was added, "
        "give it a workspace_id; if one was removed, update this list"
    )
