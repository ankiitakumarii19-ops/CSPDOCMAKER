"""
CSP DocMaker — the chat's knowledge base (tracker No. 116)

Asked for 19 Oct 2026: no AI model in the chat — Claude and Cloudflare cost
money and can be wrong. Questions about a CSP are answered from its record;
questions about the process ("what is a BCP?", "why is a request pending?")
are answered from the entries below, written by people. Super Admins and
Admins keep them on Admin -> Knowledge Base.

  * KnowledgeEntry — one question with its answer. `phrasings` holds other
    ways people ask it (one per line); matching uses the question, the
    phrasings and the keywords, never the answer.
  * KnowledgeMiss  — a question the chat could not answer, counted, so an
    Admin can see what to add next. The same question asked again adds to
    its count instead of a new row.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    # Other ways of asking, one per line.
    phrasings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Extra words that point to this entry, comma-separated (e.g. "bcp,
    # business correspondent"). Optional.
    keywords: Mapped[str] = mapped_column(String(500), nullable=False,
                                          default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False,
                                          default="General")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                         default=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255),
                                                      nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)


class KnowledgeMiss(Base):
    __tablename__ = "knowledge_misses"
    __table_args__ = (UniqueConstraint("workspace_id", "normalized",
                                       name="uq_knowledge_miss_question"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    # The question in matching form (lower case, words only): the key that
    # makes a repeat count up instead of adding a row.
    normalized: Mapped[str] = mapped_column(String(500), nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    times_asked: Mapped[int] = mapped_column(Integer, nullable=False,
                                             default=1)
    last_asked_by: Mapped[Optional[str]] = mapped_column(String(255),
                                                         nullable=True)
    first_asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
