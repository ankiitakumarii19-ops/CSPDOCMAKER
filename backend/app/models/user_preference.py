"""
CSP DocMaker — a person's own preferences (No. 240, SaaS upgrade Stage 2)

One row per signed-in person, keyed by their email (lower case) — the same
key as their profile picture (user_photos), so the choices follow the person
into every workspace they belong to.

`appearance` holds only what the person chose to change (colours, font,
sizes, layout, accessibility). An empty object = the workspace's look,
exactly as before. Checked by services/my_look.py before it is saved.

Nobody else's screen reads this row: it is returned only to its owner
(GET /api/profile/appearance) and applied only on that person's own page.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    appearance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="The person's own look; only the choices they changed")
    # No. 240 (Stage 3): notifications the person switched off for
    # themselves, {kind: {channel: false}} (services/notification_prefs.py).
    notifications: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="Staff notifications this person switched off")
    # No. 240 (Stage 5): their own arrangement of each dashboard,
    # {dashboard slug: {order: [...], hidden: [...], columns: n}}.
    dashboards: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="This person's own dashboard arrangement")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<UserPreference {self.email} {sorted(self.appearance or {})}>"
