"""
CSP DocMaker — CSP Access Control

Which CSPs an RM may see and act on. Enforced in the query layer, so an RM
cannot reach another RM's CSP by putting a different CSP ID in a request.

Confirmed rule:

  * A CSP resolved to an RM  → only that RM (and Admins, read-only).
  * A CSP that is 'unresolved' → EVERY RM may access it, and every RM is
    alerted, so an unowned CSP is never stranded.

Note the consequence of the second rule: while a CSP is unresolved its data is
visible to all RMs. Filling the sheet's RM (or LHO) column moves it back to a
single owner.
"""

import logging
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from app.models.csp_record import CSPRecord
from app.models.enums import UserRole
from app.services.rm_resolution import UNRESOLVED

logger = logging.getLogger(__name__)


# The roles that monitor everything rather than owning a slice of it.
# A Workspace Owner sees what an Admin sees; what separates them is what
# they may CHANGE, which is enforced on the configuration endpoints, not
# here.
MONITOR_ROLES = (UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value)


def is_admin(token_user: dict) -> bool:
    return (token_user.get("role") or "").lower() in MONITOR_ROLES


def accessible_filter(token_user: dict) -> Optional[ColumnElement]:
    """SQL condition limiting CSP rows to what this user may access.

    Returns None when no restriction applies (Admins, who monitor everything).
    """
    if is_admin(token_user):
        return None
    email = (token_user.get("sub") or "").strip().lower()
    return or_(
        CSPRecord.rm_email == email,
        CSPRecord.rm_resolution == UNRESOLVED,
    )


def can_access(csp: CSPRecord, token_user: dict) -> bool:
    """Whether this user may act on a specific CSP record."""
    if is_admin(token_user):
        return True
    email = (token_user.get("sub") or "").strip().lower()
    return (csp.rm_email or "").lower() == email or csp.rm_resolution == UNRESOLVED
