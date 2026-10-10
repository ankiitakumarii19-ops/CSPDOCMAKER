"""
CSP DocMaker — the agents

An agent here is a named, accountable worker with one responsibility, a
record of everything it did, and an explicit limit on what it may change
without being asked. It is not a wrapper around a language model.

That is deliberate, and it follows the brief: do not replace working
deterministic code with AI merely to call the product agentic. So:

    "Does this required field exist?"              -> code
    "Does the document contain every placeholder?" -> code
    "Is the photo 35x45mm?"                        -> code
    "Has the document passed validation?"          -> code
    "Do these two columns mean the same field?"    -> reasoning, proposed
    "Which of these looks wrong?"                  -> reasoning, proposed

Everything in the first group stays exactly where it is. What the agents
add is the second group, plus something the system genuinely lacked: a
place where each piece of recurring work is named, watched, and able to
say what it found.

The hard rule is the proposal. An agent never silently makes a high-impact
configuration change. It records a FINDING, and a Super Admin accepts or
rejects it. An agent that could quietly remap a field could quietly print
the wrong name on every certificate.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.workspace_context import default_workspace_id

# How a run ended.
OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

# What a finding is waiting for.
PROPOSED = "proposed"     # an agent suggests this; nobody has decided
ACCEPTED = "accepted"
REJECTED = "rejected"
INFORMATIONAL = "informational"   # worth knowing; nothing to decide

# How much a finding matters.
INFO = "info"
WARNING = "warning"
CRITICAL = "critical"


class AgentState(Base):
    """Whether an agent is on, and how its last run went."""

    __tablename__ = "agent_states"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id,
    )
    # Matches a key in agent_registry. Not a foreign key: the catalogue of
    # agents lives in code, because each one is code.
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False,
                                           index=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<AgentState {self.agent_key} enabled={self.enabled}>"


class AgentRun(Base):
    """One execution, kept so an agent can be held to account."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id,
    )
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False,
                                           index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # In the agent's own words, for a human reading the screen.
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Whether a person asked for this run, and who.
    triggered_by: Mapped[str | None] = mapped_column(String(255),
                                                     nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    findings: Mapped[list["AgentFinding"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_key} {self.status}>"


class AgentFinding(Base):
    """Something an agent noticed, or wants permission to do.

    A finding with status 'proposed' is the only way an agent changes
    configuration: it says what it would do, and waits.
    """

    __tablename__ = "agent_findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False)

    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=INFO,
        comment="info | warning | critical")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=INFORMATIONAL, index=True,
        comment="proposed | accepted | rejected | informational")

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What the agent would change, if accepted. Never applied on its own.
    proposal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # What it is about, so a screen can link to it.
    subject_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    run: Mapped["AgentRun"] = relationship(back_populates="findings")

    def __repr__(self) -> str:
        return f"<AgentFinding {self.agent_key} {self.severity} {self.status}>"
