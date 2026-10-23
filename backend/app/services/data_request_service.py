"""
CSP DocMaker — issuing and redeeming a CSP's fill-in link

The link is the whole credential. A CSP has no account, so whoever holds the
link can answer the request — which fixes what the link is allowed to be
worth:

  * It is random, from `secrets`, never derived from the CSP code. A CSP code
    is printed on documents; if it could be turned into a link, every
    document would be a key.
  * Only its SHA-256 is stored, so a leaked database yields no working links.
  * It names its own fields. A submission that mentions anything else is
    refused rather than quietly ignored, because quietly ignoring it would
    tell the sender their value was saved when it was not.
  * It answers once, and expires.

A request is always for ONE CSP. Nothing here can reach a second record.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.data_request import (
    ANSWERED, CANCELLED, EXPIRED, OPEN, DataRequest,
)
from app.services import field_ownership as fo

logger = logging.getLogger(__name__)

# 32 bytes of randomness, URL-safe. Long enough that guessing is not a
# strategy, short enough to survive being pasted into WhatsApp.
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def link_for(token: str) -> str:
    """The URL a CSP is sent."""
    base = get_settings().public_app_url.rstrip("/")
    return f"{base}/csp/details/{token}"


def open_request_for(session: Session, csp_id: str) -> Optional[DataRequest]:
    """The live request for this CSP, if one is already outstanding.

    Re-asking every few minutes would send a CSP a new link on every worker
    pass, so an existing open request is reused rather than replaced.
    """
    request = session.execute(
        select(DataRequest)
        .where(DataRequest.csp_id == csp_id, DataRequest.status == OPEN)
        .order_by(DataRequest.created_at.desc())
    ).scalars().first()

    if request and _is_expired(request):
        request.status = EXPIRED
        session.flush()
        return None
    return request


def has_answered(session: Session, csp_id: str) -> bool:
    """Whether this CSP has submitted a form before (any request answered)."""
    return session.execute(
        select(DataRequest.id)
        .where(DataRequest.csp_id == csp_id, DataRequest.status == ANSWERED)
        .limit(1)
    ).first() is not None


def _is_expired(request: DataRequest) -> bool:
    expires = request.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


def create(
    session: Session,
    csp_id: str,
    fields: Sequence[str],
) -> Tuple[DataRequest, str]:
    """Issue a request for these fields. Returns (row, the plaintext token).

    The token is returned exactly once, here. It is not recoverable
    afterwards, so the caller must send it before discarding it.
    """
    unknown = [f for f in fields if f not in fo.ALL_FIELDS]
    if unknown:
        raise ValueError(
            f"Cannot ask for {unknown}: not a field anyone owns. A link must "
            f"name only fields field_ownership knows, or the page would "
            f"render a box that writes nowhere."
        )
    if not fields:
        raise ValueError("Cannot issue a request for no fields.")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    settings = get_settings()
    request = DataRequest(
        csp_id=csp_id,
        token_hash=_hash(token),
        fields=list(fields),
        status=OPEN,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.data_request_expiry_days),
    )
    session.add(request)
    session.flush()

    logger.info(
        "data_request_service.create: issued a request for CSP %s covering "
        "%d field(s), valid %d day(s)",
        csp_id, len(fields), settings.data_request_expiry_days,
    )
    return request, token


def resolve(session: Session, token: str) -> Optional[DataRequest]:
    """The open request this token stands for, or None.

    None covers every failure — unknown, already answered, cancelled, expired
    — because telling them apart would let someone probe for live tokens.
    """
    if not token:
        return None

    request = session.execute(
        select(DataRequest).where(DataRequest.token_hash == _hash(token))
    ).scalars().first()

    if request is None:
        return None
    if request.status != OPEN:
        return None
    if _is_expired(request):
        request.status = EXPIRED
        session.flush()
        logger.info(
            "data_request_service.resolve: request for CSP %s has expired",
            request.csp_id,
        )
        return None
    return request


def answer(
    session: Session,
    request: DataRequest,
    values: Dict[str, str],
) -> Dict[str, str]:
    """Record what came back. Returns the values that will be applied.

    Anything the request did not ask for is refused outright. A submission is
    not a general write: the link was issued for named fields, and honouring
    anything else would make a leaked link a way of editing a CSP record.
    """
    allowed = set(request.fields or [])
    offered = {k: (v or "").strip() for k, v in (values or {}).items()}

    unexpected = sorted(set(offered) - allowed)
    if unexpected:
        raise ValueError(
            f"This link was not issued for {unexpected}. It covers "
            f"{sorted(allowed)}."
        )

    accepted = {k: v for k, v in offered.items() if v}

    request.answered_values = accepted
    request.answered_at = datetime.now(timezone.utc)
    request.status = ANSWERED
    session.flush()

    logger.info(
        "data_request_service.answer: CSP %s returned %d of %d field(s)",
        request.csp_id, len(accepted), len(allowed),
    )
    return accepted


def cancel(session: Session, csp_id: str, reason: str = "") -> int:
    """Close any open requests for this CSP. Returns how many were closed.

    Called when the data arrives another way, so a link stops working the
    moment it is no longer needed.
    """
    requests = session.execute(
        select(DataRequest)
        .where(DataRequest.csp_id == csp_id, DataRequest.status == OPEN)
    ).scalars().all()

    for request in requests:
        request.status = CANCELLED
    if requests:
        session.flush()
        logger.info(
            "data_request_service.cancel: closed %d open request(s) for CSP "
            "%s%s", len(requests), csp_id, f" ({reason})" if reason else "",
        )
    return len(requests)


def fields_to_ask(record) -> List[str]:
    """What the CSP is asked for: their OWN details still missing.

    Changed 21 Oct 2026 (asked for): DC, ASM, RM and LHO are no longer asked
    from the CSP — a missing one is the RM's alert and the INFO sheet's to
    fill. AO and RBO Name followed on 23 Oct 2026 (No. 141, No. 142): INFO's
    AO block maps them. (11 Oct, No. 53, every organisation detail was
    asked.)
    """
    missing = fo.missing(record)
    return missing[fo.CSP] + [f for f in missing[fo.ORG]
                              if f in fo.ASKED_FROM_CSP_WHEN_BLANK]
