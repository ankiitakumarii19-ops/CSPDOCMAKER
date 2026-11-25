"""
CSP DocMaker — the daily contact email (PROJECT-REGISTER No. 237)

Asked 25 Nov 2026: "email me daily how many messages you sent today and how
many times each CSP has been contacted, and if someone you cannot contact,
then why not — what's the reason."

Once a day, at the workspace's hour (Settings → Look and weekly email →
"Daily contact email", 8 pm India time for Eko), to CONTACT_REPORT_TO
(blank = every Super Admin):

  1. TODAY — WhatsApps sent / not sent, emails sent / not sent, and the
     total that went out;
  2. CONTACTED TODAY — each CSP messaged today: how many went today, how
     many failed today, and how many times they have been contacted in all;
  3. CANNOT CONTACT — every CSP the app cannot reach, with why:
       * every way was tried (main number, each alternate, email) — the
         contact loop's "Can't reach" (feedback_loops.unreachable_list);
       * still trying — their newest WhatsApp has not gone yet: the error,
         how many tries, and what happens next;
       * nothing to send to — no usable mobile number and no email;
  4. the full list as a CSV attachment: every CSP, how many WhatsApps and
     emails reached them, failed tries, last contact, and their status.

"Contacted" = a WhatsApp or an email that went out (send_status 'sent'),
the same count the RM dashboard shows (No. 234). Test messages never count.
Fixed rules over the workspace's own records; no AI. Sent at most once a
day (the audit log remembers), only from the server (never a laptop or the
test copy), and never while emails are paused.
"""

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select

logger = logging.getLogger(__name__)
ACTION = "daily_contact_email"

# Plain words for the kinds of message (whatsapp_messages.kind / email kind).
KIND_WORDS = {
    "data_request": "details check", "missing_data": "details needed",
    "documents_ready": "documents ready", "feedback": "feedback question",
    "other": "reply", "documents": "documents", "details_request":
    "details check", "guide_video": "guide video",
}


def _local_midnight(now: datetime) -> datetime:
    from app.workers.verify_old_csps_worker import send_zone
    return now.astimezone(send_zone()).replace(hour=0, minute=0, second=0,
                                               microsecond=0)


def gather(session, now: datetime) -> dict:
    """Everything the email says, as plain data (tested on its own)."""
    from app.models.csp_record import CSPRecord
    from app.models.email_message import EmailMessage, SENT as EMAIL_SENT
    from app.models.whatsapp_message import (SEND_PENDING, SEND_SENT,
                                             WhatsAppMessage)
    from app.services import feedback_loops as fl
    from app.services import message_log, resend_failed
    from app.services import whatsapp_platform as wa

    since = _local_midnight(now)
    records = {r.csp_id: r for r in session.execute(select(CSPRecord)).scalars()}

    def name_of(csp_id):
        r = records.get(csp_id)
        return (r.name if r else "") or ""

    # ---- today ----------------------------------------------------------
    today = {"whatsapp_sent": 0, "whatsapp_failed": 0, "whatsapp_waiting": 0,
             "emails_sent": 0, "emails_failed": 0}
    per_csp: Dict[str, dict] = defaultdict(
        lambda: {"sent": 0, "failed": 0, "kinds": []})
    for m in session.execute(select(WhatsAppMessage).where(
            WhatsAppMessage.sent_at >= since,
            WhatsAppMessage.is_test.is_(False))).scalars():
        if m.send_status == SEND_SENT:
            today["whatsapp_sent"] += 1
        elif m.send_status == SEND_PENDING:
            today["whatsapp_waiting"] += 1
        else:
            today["whatsapp_failed"] += 1
        if m.csp_id:
            c = per_csp[m.csp_id]
            c["sent" if m.send_status == SEND_SENT else "failed"] += 1
            word = "WhatsApp " + KIND_WORDS.get(m.kind, m.kind or "message")
            if word not in c["kinds"]:
                c["kinds"].append(word)
    for e in session.execute(select(EmailMessage).where(
            EmailMessage.sent_at >= since)).scalars():
        ok = e.send_status == EMAIL_SENT
        today["emails_sent" if ok else "emails_failed"] += 1
        if e.csp_id:
            c = per_csp[e.csp_id]
            c["sent" if ok else "failed"] += 1
            word = "email " + KIND_WORDS.get(e.kind, e.kind or "message")
            if word not in c["kinds"]:
                c["kinds"].append(word)
    today["total_sent"] = today["whatsapp_sent"] + today["emails_sent"]

    # ---- all time: how many times each CSP has been contacted ----------
    totals: Dict[str, dict] = defaultdict(
        lambda: {"whatsapp": 0, "email": 0, "failed": 0, "last": None})
    for model, ok_status, key in ((WhatsAppMessage, SEND_SENT, "whatsapp"),
                                  (EmailMessage, EMAIL_SENT, "email")):
        where = [model.csp_id.isnot(None)]
        if model is WhatsAppMessage:
            where.append(WhatsAppMessage.is_test.is_(False))
        for csp_id, status, n, last in session.execute(
                select(model.csp_id, model.send_status, func.count(),
                       func.max(model.sent_at))
                .where(*where).group_by(model.csp_id, model.send_status)).all():
            t = totals[csp_id]
            if status == ok_status:
                t[key] += n
                if last and (t["last"] is None or last > t["last"]):
                    t["last"] = last
            else:
                t["failed"] += n

    contacted_today = sorted((
        {"csp_id": csp_id, "name": name_of(csp_id), "today_sent": c["sent"],
         "today_failed": c["failed"], "what": ", ".join(c["kinds"]),
         "in_all": totals[csp_id]["whatsapp"] + totals[csp_id]["email"]}
        for csp_id, c in per_csp.items()), key=lambda r: r["csp_id"])

    # ---- cannot contact, and why ----------------------------------------
    cannot: Dict[str, dict] = {}

    def add(csp_id, status, why):
        item = cannot.setdefault(csp_id, {"csp_id": csp_id,
                                          "name": name_of(csp_id),
                                          "status": status, "why": []})
        for w in why:
            if w and w not in item["why"]:
                item["why"].append(w)

    for item in fl.unreachable_list(session):
        add(item["csp_id"], "can't reach — every way tried", item["reasons"])

    # Still trying: the newest WhatsApp of a CSP has not gone yet.
    newest: Dict[str, list] = defaultdict(list)
    for m in session.execute(select(WhatsAppMessage).where(
            WhatsAppMessage.csp_id.isnot(None),
            WhatsAppMessage.is_test.is_(False))
            .order_by(WhatsAppMessage.sent_at)).scalars():
        newest[m.csp_id].append(m)
    for csp_id, messages in newest.items():
        if csp_id in cannot:
            continue
        last = messages[-1]
        if message_log.stage(last, now) != message_log.NOT_SENT:
            continue
        if last.retry_status == "not_needed":
            continue
        tries = 0
        for m in reversed(messages):
            if message_log.stage(m, now) != message_log.NOT_SENT:
                break
            tries += 1
        error = message_log.why(last, now)
        if last.retry_status == resend_failed.HANDED_OVER:
            nxt = "the main number is given up on — trying the alternate number, then email"
        elif resend_failed.not_on_whatsapp(last.send_error):
            nxt = "the number is not on WhatsApp — trying the alternate number, then email"
        elif last.send_status == "rejected":
            nxt = "Meta refused the wording — a person must change it"
        else:
            nxt = "will be sent again"
        add(csp_id, "still trying",
            [f"{error} ({tries} tr{'y' if tries == 1 else 'ies'}, last on "
             f"{_short(last.sent_at)})", nxt])

    # Nothing to send to at all.
    for csp_id, r in records.items():
        if csp_id in cannot or r.send_hold:
            continue
        if not wa.phone_for_whatsapp(r.mobile or "") and not fl._email(r.email):
            add(csp_id, "nothing to send to",
                ["no usable mobile number and no email address in CSPDATA"])

    cannot_list = sorted(cannot.values(), key=lambda r: (r["status"], r["csp_id"]))

    # ---- the full list (CSV) --------------------------------------------
    full = []
    for csp_id, r in sorted(records.items()):
        t = totals.get(csp_id) or {"whatsapp": 0, "email": 0, "failed": 0,
                                    "last": None}
        c = cannot.get(csp_id)
        full.append({
            "CSP code": r.csp_code or csp_id, "Name": r.name or "",
            "RM": r.rm_name or "", "WhatsApps that went": t["whatsapp"],
            "Emails that went": t["email"],
            "Times contacted": t["whatsapp"] + t["email"],
            "Failed tries": t["failed"],
            "Last contacted": _short(t["last"]) if t["last"] else "never",
            "Status": (c["status"] if c else
                       ("on hold: " + r.send_hold) if r.send_hold else "ok"),
            "Why": "; ".join(c["why"]) if c else "",
        })

    return {"since": since, "today": today, "contacted_today": contacted_today,
            "cannot": cannot_list, "full": full}


def _short(at: Optional[datetime]) -> str:
    if not at:
        return ""
    from app.workers.verify_old_csps_worker import send_zone
    return at.astimezone(send_zone()).strftime("%d %b %H:%M")


def body(data: dict, name: str) -> str:
    t = data["today"]
    day = data["since"].strftime("%d %b %Y")
    lines = [f"{name}: contacts on {day}", "",
             f"Messages that went out today: {t['total_sent']}",
             f"  WhatsApp: {t['whatsapp_sent']} went, {t['whatsapp_failed']} "
             f"did not go (they are tried again), {t['whatsapp_waiting']} "
             f"waiting for Meta's approval",
             f"  Email: {t['emails_sent']} went, {t['emails_failed']} did not go",
             ""]
    rows = data["contacted_today"]
    lines.append(f"CSPs contacted today: {len(rows)}")
    for r in rows:
        failed = f", {r['today_failed']} failed" if r["today_failed"] else ""
        lines.append(f"  {r['csp_id']} {r['name']} — {r['today_sent']} today"
                     f"{failed} ({r['what']}); contacted {r['in_all']} "
                     f"time{'' if r['in_all'] == 1 else 's'} in all")
    if not rows:
        lines.append("  none")
    lines.append("")
    cannot = data["cannot"]
    lines.append(f"CSPs we cannot contact: {len(cannot)}")
    for r in cannot:
        lines.append(f"  {r['csp_id']} {r['name']} — {r['status']}")
        lines += [f"      - {w}" for w in r["why"]]
    if not cannot:
        lines.append("  none — every CSP can be reached")
    lines += ["", "Attached: every CSP with how many times they have been "
              "contacted (WhatsApp + email), failed tries, last contact and "
              "status.", "",
              "Change or stop this email: Settings → Look and weekly email → "
              "Daily contact email."]
    return "\n".join(lines)


def csv_bytes(full: List[dict]) -> bytes:
    out = io.StringIO()
    if full:
        w = csv.DictWriter(out, fieldnames=list(full[0].keys()))
        w.writeheader()
        w.writerows(full)
    # A byte-order mark so Excel opens the Hindi / special letters right.
    return ("﻿" + out.getvalue()).encode("utf-8")


def recipients(session) -> List[str]:
    from app.config import get_settings
    own = sorted({e.strip().lower() for e in str(
        get_settings().contact_report_to or "").split(",") if e.strip()})
    if own:
        return own
    from app.models.enums import UserRole
    from app.models.workspace_member import WorkspaceMember
    return sorted(set(session.execute(select(WorkspaceMember.email).where(
        WorkspaceMember.role == UserRole.SUPER_ADMIN,
        WorkspaceMember.active.is_(True))).scalars()))


def due(session, now: datetime) -> Optional[str]:
    """None when the email should go now, else why not."""
    from app.config import get_settings
    from app.models.audit_log import AuditLog
    from app.workers.verify_old_csps_worker import send_zone
    s = get_settings()
    if not s.contact_report_on:
        return "off (Settings → Look and weekly email → Daily contact email)"
    local = now.astimezone(send_zone())
    if local.hour < int(s.contact_report_hour):
        return "not the hour yet"
    last = session.execute(select(func.max(AuditLog.created_at)).where(
        AuditLog.action == ACTION, AuditLog.result == "success")).scalar()
    if last and last >= _local_midnight(now):
        return "already sent today"
    return None


def _send(to: str, subject: str, text: str, attachment: bytes,
          filename: str) -> tuple:
    """Plain text + the CSV, through the app's SMTP account."""
    from app.services import email_service
    if email_service.paused():
        return False, email_service.paused_reason()
    try:
        ok = email_service.send_with_attachment(
            to, subject, text, attachment, filename, "text/csv")
    except Exception as e:                 # returned and logged by the caller
        return False, f"{type(e).__name__}: {e}"
    return ok, "" if ok else "SMTP reported failure — see the server log"


def run(session, now: Optional[datetime] = None, send=None) -> dict:
    from app.config import get_settings
    from app.models.audit_log import AuditLog
    from app.services import message_sender
    from app.workspace_context import current_workspace_id
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    if s.test_copy or not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "not the server (a laptop or the test copy sends "
                           "no daily contact email)"}
    why = due(session, now)
    if why:
        return {"skipped": why}
    data = gather(session, now)
    to = recipients(session)
    if not to:
        logger.error("contact_report: no one to send the daily contact email "
                     "to — set Settings → Daily contact email: to, or add a "
                     "Super Admin")
        return {"skipped": "no recipient"}
    send = send or _send
    text = body(data, s.brand_name)
    day = data["since"].strftime("%d %b %Y")
    subject = (f"{s.brand_name}: {data['today']['total_sent']} messages today, "
               f"{len(data['cannot'])} CSPs cannot be contacted — {day}")
    attachment = csv_bytes(data["full"])
    filename = f"csp-contacts-{data['since'].strftime('%Y-%m-%d')}.csv"
    sent, failed = [], {}
    for addr in to:
        ok, reason = send(addr, subject, text, attachment, filename)
        if ok:
            sent.append(addr)
        else:
            failed[addr] = reason
            logger.error("contact_report: daily contact email not sent to %s: "
                         "%s", addr, reason)
    session.add(AuditLog(workspace_id=current_workspace_id(), action=ACTION,
                         resource_type="workspace",
                         resource_id=str(current_workspace_id()),
                         result="success" if sent else "failure",
                         metadata_json={"to": sent, "failed": failed,
                                        "today": data["today"],
                                        "contacted_today": len(data["contacted_today"]),
                                        "cannot_contact": len(data["cannot"])}))
    session.commit()
    return {"sent_to": sent, "failed": failed, "today": data["today"],
            "cannot": len(data["cannot"])}
