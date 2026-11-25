"""
CSP DocMaker — CSPs still waiting for their documents (PROJECT-REGISTER No. 234)

The RM dashboard: every CSP that has not yet been sent all of its documents,
how many times it has been contacted, and filters by RM, DC, state and
district. Every RM sees every CSP here (No. 234: any RM may act on any CSP).

Definitions — the same as the Admin dashboard, so the two never disagree:

  * a document is SENT when an email carrying it reached "sent"
    (email_jobs + email_documents, as admin_router._delivery_sets);
  * the documents a CSP should get are every document type, less the ones
    its KO level never gets (ko_level.allowed_documents: a Sub-KO no BCP);
  * a CSP is LEFT when at least one of those is not sent yet;
  * CONTACTED = WhatsApps and emails that actually went out to this CSP
    (whatsapp_messages / email_messages with send_status "sent"). Every
    details-form link, reminder and message by hand is one of these.

Not listed: CSPs that were in CSPDATA before the Calling / Lead import —
they are never mailed documents (owner's rule, D14), so they are not
"left". Their number is returned so the screen can say so.
"""

import logging
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

FILTERS = ("rm", "dc", "state", "district")
CONTACT_BANDS = ("never", "1-2", "3+")
HOLD_VIEWS = ("", "hide", "only")
SORTS = ("contacts", "-contacts", "last_contacted", "name")
GROUPS = ("rm", "dc", "state", "district")


def band_of(total: int) -> str:
    if total <= 0:
        return "never"
    return "1-2" if total <= 2 else "3+"


def _text(value) -> str:
    return " ".join(str(value or "").split())


def build_rows(records: Iterable, mailed: Dict[str, Set[str]],
               contacts: Dict[str, dict], imported: Set[str]) -> dict:
    """Every CSP still owed a document, as plain rows (no database here, so
    the rules are tested on their own).

    records   CSP records (csp_id, csp_code, name, origin, send_hold, ...)
    mailed    csp_id -> document type values already emailed
    contacts  csp_id -> {"whatsapp": n, "email": n, "last": datetime|None}
    imported  CSP codes copied in by the Calling / Lead import
    """
    from app.models.enums import DocumentType
    from app.services import ko_level
    from app.services.missing_data_service import document_label

    rows: List[dict] = []
    old = 0
    for r in records:
        code = r.csp_code or r.csp_id
        if (r.origin or "") == "baseline" and code not in imported:
            old += 1
            continue
        due = ko_level.allowed_documents(code, list(DocumentType))
        sent = mailed.get(r.csp_id, set())
        left = [d for d in due if d.value not in sent]
        if not left:
            continue
        c = contacts.get(r.csp_id) or {}
        wa, em = int(c.get("whatsapp") or 0), int(c.get("email") or 0)
        last = c.get("last")
        rows.append({
            "csp_id": r.csp_id,
            "csp_code": r.csp_code,
            "name": r.name,
            "mobile": r.mobile,
            "rm": _text(r.rm_name),
            "dc": _text(r.dc),
            "state": _text(r.state),
            "district": _text(r.district),
            "origin": r.origin,
            "on_hold": r.send_hold or "",
            "documents_left": [document_label(d) for d in left],
            "documents_sent": len(due) - len(left),
            "documents_due": len(due),
            "whatsapp": wa,
            "email": em,
            "contacts": wa + em,
            "last_contacted": last.isoformat() if last else None,
        })
    return {"rows": rows, "old_not_listed": old}


def apply(rows: List[dict], filters: dict, contacted: str = "",
          hold: str = "", q: str = "") -> List[dict]:
    """The rows the filters keep. Text compares ignore case and spaces."""
    want = {k: _text(filters.get(k)).lower() for k in FILTERS
            if _text(filters.get(k))}
    q = _text(q).lower()
    out = []
    for row in rows:
        if any(row[k].lower() != v for k, v in want.items()):
            continue
        if contacted and band_of(row["contacts"]) != contacted:
            continue
        if hold == "hide" and row["on_hold"]:
            continue
        if hold == "only" and not row["on_hold"]:
            continue
        if q and q not in " ".join(str(row.get(k) or "") for k in (
                "csp_id", "csp_code", "name", "mobile")).lower():
            continue
        out.append(row)
    return out


def options(rows: List[dict], filters: dict) -> Dict[str, List[str]]:
    """The values each filter can take — from the CSPs the OTHER filters
    leave, so a choice never comes back empty (pick a state: only its
    districts)."""
    out = {}
    for name in FILTERS:
        others = {k: v for k, v in filters.items() if k != name}
        values: Dict[str, str] = {}
        for r in apply(rows, others):
            if r[name]:
                values.setdefault(r[name].lower(), r[name])
        out[name] = sorted(values.values(), key=str.lower)
    return out


def summary(rows: List[dict]) -> dict:
    bands = defaultdict(int)
    for r in rows:
        bands[band_of(r["contacts"])] += 1
    return {
        "left": len(rows),
        "never": bands["never"],
        "once_or_twice": bands["1-2"],
        "three_plus": bands["3+"],
        "on_hold": sum(1 for r in rows if r["on_hold"]),
        "contacts": sum(r["contacts"] for r in rows),
    }


def grouped(rows: List[dict], by: str) -> List[dict]:
    """Left / never contacted / contacts, per RM (or DC, state, district)."""
    groups: Dict[str, dict] = {}
    for r in rows:
        name = r[by] or "(not set)"
        g = groups.setdefault(name.lower(), {"name": name, "left": 0,
                                             "never": 0, "contacts": 0})
        g["left"] += 1
        g["never"] += r["contacts"] == 0
        g["contacts"] += r["contacts"]
    out = sorted(groups.values(), key=lambda g: (-g["left"], g["name"].lower()))
    for g in out:
        g["average"] = round(g["contacts"] / g["left"], 1) if g["left"] else 0
    return out


def sort_rows(rows: List[dict], sort: str) -> List[dict]:
    if sort == "-contacts":
        return sorted(rows, key=lambda r: (-r["contacts"], r["name"].lower()))
    if sort == "last_contacted":
        # Longest since the last contact first; never contacted before all.
        return sorted(rows, key=lambda r: (r["last_contacted"] is not None,
                                           r["last_contacted"] or "",
                                           r["name"].lower()))
    if sort == "name":
        return sorted(rows, key=lambda r: r["name"].lower())
    return sorted(rows, key=lambda r: (r["contacts"], r["name"].lower()))


# ---- reading the database --------------------------------------------------

def load(session) -> dict:
    """build_rows() over this workspace's CSPs (a sync session)."""
    from app.models.csp_record import CSPRecord
    from app.models.email_document import EmailDocument
    from app.models.email_job import EmailJob
    from app.models.email_message import EmailMessage, SENT as EMAIL_SENT
    from app.models.enums import EmailStatus
    from app.models.processing_job import ProcessingJob
    from app.models.source_sheet import SourceSheetState
    from app.models.whatsapp_message import SEND_SENT, WhatsAppMessage

    records = session.execute(select(CSPRecord)).scalars().all()

    mailed: Dict[str, Set[str]] = defaultdict(set)
    for csp_id, doc_type in session.execute(
            select(ProcessingJob.csp_id, EmailDocument.document_type)
            .join(EmailJob, EmailJob.processing_job_id == ProcessingJob.id)
            .join(EmailDocument, EmailDocument.email_job_id == EmailJob.id)
            .where(EmailJob.status == EmailStatus.SENT)).all():
        mailed[csp_id].add(getattr(doc_type, "value", doc_type))

    contacts: Dict[str, dict] = defaultdict(
        lambda: {"whatsapp": 0, "email": 0, "last": None})
    for model, status, key in ((WhatsAppMessage, SEND_SENT, "whatsapp"),
                               (EmailMessage, EMAIL_SENT, "email")):
        for csp_id, n, last in session.execute(
                select(model.csp_id, func.count(), func.max(model.sent_at))
                .where(model.csp_id.isnot(None), model.send_status == status)
                .group_by(model.csp_id)).all():
            c = contacts[csp_id]
            c[key] = n
            if last and (c["last"] is None or last > c["last"]):
                c["last"] = last

    imported = set(session.execute(
        select(SourceSheetState.csp_code)
        .where(SourceSheetState.imported_as.isnot(None))).scalars())

    out = build_rows(records, mailed, contacts, imported)
    logger.info("pending_documents.load: %d CSP(s) read, %d left, %d old "
                "not listed", len(records), len(out["rows"]),
                out["old_not_listed"])
    return out


def check(name: str, value: Optional[str], allowed) -> str:
    """'' or one of `allowed`; ValueError (plain words) otherwise."""
    value = (value or "").strip()
    if value and value not in allowed:
        raise ValueError(f"Unknown {name} '{value}'. Choose one of: "
                         + ", ".join(a for a in allowed if a) + ".")
    return value
