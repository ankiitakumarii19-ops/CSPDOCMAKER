"""
CSP DocMaker — how well each agent is doing, over time (No. 252)

Four tables behind Setup -> Agent health:

  agent_eval_snapshots  one row per agent per day: that day's numbers and
                        its score, so the history can be drawn and each
                        agent's own "normal" learned.
  agent_eval_issues     something wrong with an agent (failing, overdue,
                        slow, poor results ...). Opened when first seen,
                        kept up to date while it lasts, resolved when it
                        stops - never deleted, so the history stays.
  agent_improvements    what the agents learned: changes made by
                        themselves (safe ones, with undo) and changes
                        proposed for the Super Admin to apply.
  assistant_turns       one row per question asked in the chat: what kind
                        of answer it got, whether it was answered, which
                        Knowledge Base entry answered it and how fast.

The chat "agent" is keyed 'chat' alongside the six background agents.
No AI anywhere (No. 116): every number is counted, every rule is fixed.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

CHAT = "chat"

# Issue states and how serious.
OPEN = "open"
RESOLVED = "resolved"
WARNING = "warning"
CRITICAL = "critical"

# Improvement states.
APPLIED = "applied"        # in force (made by itself, or applied by a person)
PROPOSED = "proposed"      # waiting for the Super Admin
DISMISSED = "dismissed"    # the Super Admin said no
UNDONE = "undone"          # was in force, then undone
CLOSED = "closed"          # no longer needed (the problem went away)


def _workspace_column():
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)


class AgentEvalSnapshot(Base):
    __tablename__ = "agent_eval_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_column()
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_key", "day",
                         name="uq_agent_eval_snapshot_day"),
    )


class AgentEvalIssue(Base):
    __tablename__ = "agent_eval_issues"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_column()
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False)
    check_key: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default=OPEN)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    limit_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_eval_issues_open", "workspace_id", "status",
              "agent_key", "check_key"),
    )


class AgentImprovement(Base):
    __tablename__ = "agent_improvements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_column()
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    change: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    automatic: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_by: Mapped[Optional[str]] = mapped_column(String(255),
                                                      nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_agent_improvements_state", "workspace_id", "status",
              "kind"),
    )


class AssistantTurn(Base):
    __tablename__ = "assistant_turns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_column()
    asked_by: Mapped[str] = mapped_column(String(255), nullable=False,
                                          default="")
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The Knowledge Base entry that answered it (not a built-in setup guide).
    entry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # The question as a matching key (knowledge_service.normalized) and as
    # asked, kept short: what the chat learns new wordings from.
    normalized: Mapped[str] = mapped_column(String(500), nullable=False,
                                            default="")
    question: Mapped[str] = mapped_column(String(500), nullable=False,
                                          default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False,
                                             default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_assistant_turns_when", "workspace_id", "created_at"),
    )
