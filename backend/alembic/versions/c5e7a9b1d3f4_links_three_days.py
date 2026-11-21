"""CSP form links last 3 days: the reply that sends a new link says so (No. 192)

20 Nov 2026. The data verification and missing details links now stay
open 3 days (DATA_REQUEST_EXPIRY_DAYS, was 7) and a new one is sent each
time one runs out unanswered. The "link does not open" reply told the CSP
"7 din ke andar"; it now says "3 din ke andar".

Only the starting wording is changed: an Admin's own edit of that reply is
left as they wrote it. Data only, no table change.

Revision ID: c5e7a9b1d3f4
Revises: b4d6f8a0c2e3
"""
import sqlalchemy as sa
from alembic import op

revision = "c5e7a9b1d3f4"
down_revision = "b4d6f8a0c2e3"
branch_labels = None
depends_on = None

QUESTION = "CSP reply: the link does not open"
OLD = ("Link ki pareshani ke liye khed hai. Hum aapko abhi ek naya link bhej "
       "rahe hain - use 7 din ke andar ek baar bharein.")
NEW = ("Link ki pareshani ke liye khed hai. Hum aapko abhi ek naya link bhej "
       "rahe hain - use 3 din ke andar ek baar bharein.")


def _swap(old: str, new: str) -> None:
    op.get_bind().execute(sa.text(
        "UPDATE knowledge_entries SET answer = :new "
        "WHERE question = :q AND answer = :old"),
        {"new": new, "q": QUESTION, "old": old})


def upgrade() -> None:
    _swap(OLD, NEW)


def downgrade() -> None:
    _swap(NEW, OLD)
