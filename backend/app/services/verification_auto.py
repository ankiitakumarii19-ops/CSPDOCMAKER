"""
CSP DocMaker — the verification agent decides by itself (No. 171)

The verification agent compares what each CSP sent on their form with what
the record holds now. It used to raise a card for every difference and wait
for a Super Admin's Accept / Decline; nothing happened either way, and the
same card came back every 30 minutes (78 waiting on 1 Nov 2026). The
owner's rule now: **the newest value wins**, decided here, logged, never
asked.

  1. Same value, only written differently — capitals, spaces, leading
     zeros ("8474" / "008474"), the RBO's place name ("RBO 6 Samastipur" /
     "RBO 6"), +91 on a mobile — is not a difference. Nothing happens.
  2. The CSP's answer reached the sheet when they sent it (data_requests.
     sheet_saved) and the sheet now says something else: the sheet was
     changed afterwards, so the sheet's value is newer. It stays.
  3. The answer never reached the sheet (the write failed) and the sheet
     still holds what it held before the answer (previous_values): the
     CSP's answer is the newest, so it is written to the sheet now — the
     same write the form does — and to the record.
     If the sheet has moved on since, the sheet's value is newer: it stays.

Only the newest answer for a CSP and field counts. Every decision of kind 2
and 3 is written once to the audit log (action "verification_auto": CSP,
field, the CSP's answer, the old and new value, why, when) and shown on the
Agents page. Writing to the sheet happens only on the server (public
PUBLIC_APP_URL), as every other automatic sheet write.
"""

import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from sqlalchemy import select

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

ACTION = "verification_auto"
KEPT_SHEET = "kept_sheet"
WROTE_ANSWER = "wrote_answer"

_RBO = re.compile(r"^rbo\s*[-:]?\s*0*([a-z0-9]+)")


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def same(field: str, a, b) -> bool:
    """Equal once spelling differences that change nothing are removed."""
    x, y = _norm(a), _norm(b)
    if x == y:
        return True
    if x.isdigit() and y.isdigit():
        return x.lstrip("0") == y.lstrip("0")
    if field == "rbo_name":
        mx, my = _RBO.match(x), _RBO.match(y)
        if mx and my:
            return mx.group(1) == my.group(1)
    if "mobile" in field or "phone" in field:
        dx, dy = re.sub(r"\D", "", x), re.sub(r"\D", "", y)
        return len(dx) >= 10 and dx[-10:] == dy[-10:]
    return False


@dataclass
class Decision:
    request_id: str
    csp_id: str
    field: str
    answered: str          # what the CSP sent
    before: str            # what the record / sheet held
    after: str             # what it holds once decided
    kind: str              # KEPT_SHEET | WROTE_ANSWER
    why: str

    @property
    def key(self) -> str:
        return f"{self.request_id}:{self.field}"


def decide(request, field: str, answered, current) -> Optional[Decision]:
    """What to do about one difference, or None when there is none."""
    if current is None or same(field, answered, current):
        return None
    reached = request.sheet_saved is None or field in (request.sheet_saved or [])
    before = (request.previous_values or {}).get(field)
    common = dict(request_id=str(request.id), csp_id=request.csp_id,
                  field=field, answered=str(answered), before=str(current))
    if not reached and before is not None and same(field, before, current):
        return Decision(**common, after=str(answered), kind=WROTE_ANSWER,
                        why="The CSP's answer never reached the sheet and "
                            "nobody changed the sheet since — their answer "
                            "is the newest.")
    if reached:
        why = ("The sheet was changed after the CSP answered — the sheet's "
               "value is newer.")
    else:
        why = ("The CSP's answer never reached the sheet, and the sheet was "
               "changed since — the sheet's value is newer.")
    return Decision(**common, after=str(current), kind=KEPT_SHEET, why=why)


def newest_answers(requests: Iterable) -> List[tuple]:
    """[(request, field, value)] — only the latest answer per CSP + field."""
    latest = {}
    for r in sorted(requests, key=lambda r: (r.answered_at is None,
                                             r.answered_at)):
        for field, value in (r.answered_values or {}).items():
            latest[(r.csp_id, field)] = (r, field, value)
    return list(latest.values())


def already_logged(session, keys: List[str]) -> set:
    if not keys:
        return set()
    return set(session.execute(select(AuditLog.resource_id).where(
        AuditLog.action == ACTION, AuditLog.resource_id.in_(keys))
    ).scalars())


def log(session, d: Decision, result: str = "success",
        error: Optional[str] = None) -> None:
    from app.services import field_ownership as fo

    meta = {"by": "verification agent", "field": d.field,
            "label": fo.label_of(d.field), "decision": d.kind,
            "csp_answered": d.answered, "old_value": d.before,
            "new_value": d.after, "why": d.why}
    if error:
        meta["error"] = error[:500]
    session.add(AuditLog(action=ACTION, resource_type="data_request",
                         resource_id=d.key, csp_id=d.csp_id, result=result,
                         metadata_json=meta))


def write_answer(session, d: Decision, record) -> None:
    """Put the CSP's answer on the sheet and the record, as the form does."""
    from app.services import field_quality
    from app.services import sheet_writeback_service as wb

    written, _skipped = wb.write_values(d.csp_id, {d.field: d.after})
    if d.field not in written:
        raise wb.SheetWriteError(f"the sheet has no column for {d.field}")
    setattr(record, d.field, d.after)
    try:
        with session.begin_nested():
            # It is the CSP's own form answer, arriving late.
            field_quality.record_check(session, d.csp_id, written,
                                       "csp_form", "CSP")
    except Exception as e:
        # The value is on the sheet; only the quality note is missing.
        logger.error("verification_auto: %s %s written, but its quality "
                     "note was not: %s: %s", d.csp_id, d.field,
                     type(e).__name__, e, exc_info=True)


def history(session, limit: int = 100) -> List[dict]:
    """What the agent decided by itself, newest first, for the screen."""
    rows = session.execute(
        select(AuditLog).where(AuditLog.action == ACTION)
        .order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    out = []
    for r in rows:
        m = r.metadata_json or {}
        out.append({"at": r.created_at.isoformat() if r.created_at else None,
                    "csp_id": r.csp_id, "field": m.get("field"),
                    "label": m.get("label"), "decision": m.get("decision"),
                    "csp_answered": m.get("csp_answered"),
                    "old_value": m.get("old_value"),
                    "new_value": m.get("new_value"), "why": m.get("why"),
                    "result": r.result, "error": m.get("error")})
    return out
