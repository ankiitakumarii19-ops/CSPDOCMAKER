"""
CSP DocMaker — the reply agent for CSPs' WhatsApp messages (No. 151)

Asked 27 Oct 2026: "an agent which reads their response and responds to
whatever they ask; if it is not related, reply: contact your RM" — with the
RM's name and number. Decided: rules + Knowledge Base, no AI (No. 116);
drafts first, a person sends them; one switch makes it automatic.

How a reply is made, every run (workers.answer_csp_replies):

  1. The CSPs' new WhatsApp messages are read from the platform's inbox —
     only numbers this app has messaged, only the last REPLY_LOOKBACK_HOURS,
     never the phone's automatic greeting. Messages from one CSP that arrive
     before their reply is sent are answered together, once.
  2. Each message is matched by fixed rules (English / Hinglish / Hindi):
     the link does not open, documents, uploads / other papers, wrong
     details, thanks-only. A message no rule knows is looked up in the
     Knowledge Base's "CSP replies" answers; still unknown -> "contact your
     RM <name> (<number>)".
  3. The reply is written from the Knowledge Base's "CSP replies" wordings
     (Admins can change them), filled from the CSP's own record: the date
     their details came in, where their documents were emailed, their RM.
  4. "draft" mode: it waits on the WhatsApp messages screen for Send (after
     an edit, if wanted) or Skip. "auto" mode: sent once the CSP has been
     quiet for 5 minutes, 8 am - 8 pm, at most 3 a day per CSP. "off":
     nothing is read or written.

Sending uses the chat's Meta-approved wording ("Namaste {name}, here is a
message from Eko Bharat Ventures: {message} Thank you."). A reply that
promises a new link sends it right after (message_sender.ask_for_details).
Nothing goes to a CSP on hold. Deterministic: the same messages give the
same reply.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select

from app.models.csp_reply import CspReply

logger = logging.getLogger(__name__)

CATEGORY = "CSP replies"
MODES = ("off", "draft", "auto")
DEFAULT_MODE = "draft"
LOOKBACK = timedelta(hours=72)
QUIET = timedelta(minutes=5)
AUTO_PER_DAY = 3
MAX_CHARS = 900

LINK = "CSP reply: the link does not open"
RECEIVED = "CSP reply: details already received"
DOCS_SENT = "CSP reply: documents were emailed"
DOCS_NOT_YET = "CSP reply: documents not made yet"
UPLOAD = "CSP reply: uploads and other papers"
WRONG = "CSP reply: wrong details"
ELSE = "CSP reply: anything else"

# Used when an Admin has deleted or switched off the entry, so a reply can
# always be written. Same wording as the migration's starting set.
DEFAULTS = {
    LINK: ("Link ki pareshani ke liye khed hai. Hum aapko abhi ek naya link "
           "bhej rahe hain - use 7 din ke andar ek baar bharein."),
    RECEIVED: ("Aapki details {date} ko humein mil chuki hain, dhanyavaad. Ab "
               "kuch aur bharne ki zaroorat nahi hai."),
    DOCS_SENT: ("Aapke documents {date} ko {email} par email kiye gaye the. "
                "Kripya inbox aur spam folder dekhein."),
    DOCS_NOT_YET: ("Aapke documents aapki details poori hone ke baad aapke "
                   "email par bheje jayenge."),
    UPLOAD: ("Police verification, agreement aur doosre papers ke liye "
             "kripya apne RM{rm} se sampark karein."),
    WRONG: ("Details sudharne ke liye hum aapko naya link bhej rahe hain - "
            "usme sahi details bharein."),
    ELSE: "Is baare mein kripya apne RM{rm} se sampark karein.",
}

INTENT_LABEL = {
    "link": "Link does not open",
    "documents": "Asks about documents",
    "upload": "Upload / other papers",
    "wrong_details": "Wrong details",
    "thanks": "Thanks / ok — no reply needed",
    "knowledge": "Answered from the Knowledge Base",
    "else": "Not understood — sent to their RM",
}


# ---- understanding a message --------------------------------------------

def norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\wऀ-ॿ\s]", " ", text)
    return " ".join(text.split())


def _any(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


W = r"(?:^|\s)"            # a word starts here (Hindi words have no \b)
LINK_WORDS = rf"{W}(link|lnk|lino|linc|लिंक)"
PROBLEM_WORDS = (r"(open|khul|khol|nahi|nahin|nhi|nai|not|expire|error|"
                 r"kaam|work|chal|band|problem|issue|नहीं|खुल)")
UPLOAD_WORDS = (rf"{W}(upload|uplod|अपलोड)|police verification|"
                r"aggr?e?ment|agrement|agreement|पुलिस|एग्रीमेंट")
DOCUMENT_WORDS = (r"(document|documents|docs|dastavez|dastavej|दस्तावेज|"
                  r"certificate|certificat|प्रमाण|id card|idcard|"
                  r"appointment|letter|bcp)")
WRONG_WORDS = r"(galat|wrong|change|badal|sudhar|correct|update|गलत|बदल)"
FIELD_WORDS = (r"(naam|name|address|pata|mobile|number|email|mail|branch|"
               r"नाम|पता|नंबर)")
THANKS_ONLY = re.compile(
    r"(ok|okay|okk+|thanks?|thank you|thanku|thx|ty|dhanyavad|dhanyawad|"
    r"shukriya|done|ho gaya|hogaya|ji|haan|ha|yes|theek hai|thik hai|"
    r"धन्यवाद|ठीक है|जी|\s)+")


def classify(text: str) -> List[str]:
    """The rules a message matches, most actionable first."""
    t = norm(text)
    if not t:
        return []
    if THANKS_ONLY.fullmatch(t):
        return ["thanks"]
    found = []
    if _any(t, LINK_WORDS) and _any(t, PROBLEM_WORDS):
        found.append("link")
    if _any(t, UPLOAD_WORDS):
        found.append("upload")
    elif _any(t, DOCUMENT_WORDS):
        found.append("documents")
    if _any(t, WRONG_WORDS) and _any(t, FIELD_WORDS):
        found.append("wrong_details")
    return found


# ---- what the CSP's record says -----------------------------------------

def _entries(session) -> Dict[str, object]:
    from app.models.knowledge import KnowledgeEntry
    return {e.question: e for e in session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.category == CATEGORY,
                                     KnowledgeEntry.active.is_(True))
    ).scalars()}


def _wording(entries: dict, rule: str) -> str:
    entry = entries.get(rule)
    return (entry.answer if entry is not None and (entry.answer or "").strip()
            else DEFAULTS[rule])


def _day(when: Optional[datetime]) -> str:
    return when.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime(
        "%d %b %Y") if when else ""


def rm_contact(session, record) -> str:
    """' <name> (<number>)', ' <name>', or '' when the RM is not known."""
    from app.models.authorization_record import AuthorizationRecord
    from app.services.alert_composer import normalize_mobile

    person = None
    if record.rm_email:
        person = session.execute(select(AuthorizationRecord).where(
            func.lower(AuthorizationRecord.email) == record.rm_email.lower(),
            AuthorizationRecord.active.is_(True))).scalars().first()
    name = (record.rm_name or (person.name if person else "") or "").strip()
    number = normalize_mobile(person.mobile) if person else ""
    number = number[2:] if number.startswith("91") and len(number) == 12 else number
    if name and number:
        return f" {name} ({number})"
    return f" {name}" if name else ""


def _answered(session, csp_id: str):
    from app.models.data_request import ANSWERED, DataRequest
    return session.execute(
        select(DataRequest).where(DataRequest.csp_id == csp_id,
                                  DataRequest.status == ANSWERED)
        .order_by(DataRequest.answered_at.desc())).scalars().first()


def _documents_emailed(session, csp_id: str) -> Optional[Tuple[datetime, str]]:
    """When and where this CSP's documents were last emailed, if they were."""
    from app.models.email_job import EmailJob
    from app.models.email_message import KIND_DOCUMENTS, SENT, EmailMessage
    from app.models.enums import EmailStatus
    from app.models.processing_job import ProcessingJob

    m = session.execute(
        select(EmailMessage).where(EmailMessage.csp_id == csp_id,
                                   EmailMessage.kind == KIND_DOCUMENTS,
                                   EmailMessage.send_status == SENT,
                                   EmailMessage.bounced_at.is_(None))
        .order_by(EmailMessage.sent_at.desc())).scalars().first()
    if m is not None:
        return m.sent_at, m.to_email
    job = session.execute(
        select(EmailJob).join(ProcessingJob,
                              ProcessingJob.id == EmailJob.processing_job_id)
        .where(ProcessingJob.csp_id == csp_id,
               EmailJob.status == EmailStatus.SENT)
        .order_by(EmailJob.sent_at.desc())).scalars().first()
    return (job.sent_at, job.recipient) if job is not None else None


# ---- writing the reply --------------------------------------------------

def compose(session, record, texts: List[str]) -> Tuple[List[str], str, Optional[str]]:
    """(intents, reply text, action) for these messages from this CSP."""
    from app.services import data_request_service as drs
    from app.services import knowledge_service

    entries = _entries(session)
    general = [e for q, e in entries.items() if not q.startswith("CSP reply:")]

    intents: List[str] = []
    knowledge: List[str] = []
    not_understood: List[str] = []
    for text in texts:
        found = classify(text)
        if found:
            intents += [f for f in found if f not in intents]
            continue
        ranked = knowledge_service.rank(text, general) if general else []
        if ranked and ranked[0].score >= knowledge_service.ANSWER_AT:
            if ranked[0].entry.answer not in knowledge:
                knowledge.append(ranked[0].entry.answer)
            if "knowledge" not in intents:
                intents.append("knowledge")
        elif norm(text):
            not_understood.append(norm(text))
    if intents and all(i == "thanks" for i in intents) and not not_understood:
        return ["thanks"], "", None
    intents = [i for i in intents if i != "thanks"]
    # Something real was not understood: a message of 3+ words, or nothing
    # at all was. A lone "plz" or "hi" beside a question is not a question.
    unknown = (any(len(t.split()) >= 3 for t in not_understood)
               or (not_understood and not intents))
    if unknown and "upload" not in intents:
        intents.append("else")

    rm = rm_contact(session, record)
    parts: List[str] = []
    action = None
    for intent in intents:
        if intent == "link":
            answered = _answered(session, record.csp_id)
            if answered is not None and drs.open_request_for(
                    session, record.csp_id) is None:
                parts.append(_wording(entries, RECEIVED).replace(
                    "{date}", _day(answered.answered_at)))
            else:
                parts.append(_wording(entries, LINK))
                action = "fresh_link"
        elif intent == "documents":
            emailed = _documents_emailed(session, record.csp_id)
            if emailed:
                parts.append(_wording(entries, DOCS_SENT)
                             .replace("{date}", _day(emailed[0]))
                             .replace("{email}", emailed[1] or "your email"))
            else:
                parts.append(_wording(entries, DOCS_NOT_YET))
        elif intent == "upload":
            parts.append(_wording(entries, UPLOAD))
        elif intent == "wrong_details" and action != "fresh_link":
            parts.append(_wording(entries, WRONG))
            action = "fresh_link"
        elif intent == "knowledge":
            parts += knowledge
        elif intent == "else":
            parts.append(_wording(entries, ELSE))
    text = " ".join(p.replace("{rm}", rm) for p in parts)
    return intents, clean(text), action


def clean(text: str) -> str:
    """One line (WhatsApp wording parameters cannot hold line breaks)."""
    return " ".join((text or "").split())[:MAX_CHARS]


# ---- the switch ---------------------------------------------------------

def get_mode(session) -> str:
    from app.models.workspace import Workspace
    from app.workspace_context import current_workspace_id
    ws = session.get(Workspace, current_workspace_id())
    mode = ((ws.settings or {}) if ws else {}).get("csp_replies_mode")
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(session, mode: str) -> str:
    from app.models.workspace import Workspace
    from app.workspace_context import current_workspace_id
    if mode not in MODES:
        raise ValueError(f"mode is one of {', '.join(MODES)}")
    ws = session.get(Workspace, current_workspace_id())
    ws.settings = {**(ws.settings or {}), "csp_replies_mode": mode}
    return mode


# ---- reading the inbox --------------------------------------------------

def collect(session, wa, now: Optional[datetime] = None) -> Dict[str, int]:
    """New messages from CSPs, into drafts (one waiting draft per CSP)."""
    from app.models.csp_record import CSPRecord
    from app.models.whatsapp_message import SEND_SENT, WhatsAppMessage
    from app.services import message_log

    now = now or datetime.now(timezone.utc)
    ours = session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.csp_id.isnot(None),
                                      WhatsAppMessage.send_status == SEND_SENT,
                                      WhatsAppMessage.phone != "")
        .order_by(WhatsAppMessage.sent_at)).scalars().all()
    csp_of: Dict[str, str] = {}
    sent_times: Dict[str, List[datetime]] = {}
    for m in ours:
        csp_of[m.phone] = m.csp_id
        sent_times.setdefault(m.phone, []).append(m.sent_at)
    if not csp_of:
        return {"new": 0, "updated": 0}

    seen = dict(session.execute(
        select(CspReply.phone, func.max(CspReply.last_in_at))
        .group_by(CspReply.phone)).all())
    inbox = message_log._listed(wa.call_tool("get_incoming_messages", {}),
                                "messages", "rows")
    fresh: Dict[str, List[dict]] = {}
    for r in inbox:
        phone = re.sub(r"\D", "", str(r.get("from_phone") or ""))
        at = message_log._parse_time(r.get("sent_at"))
        if phone not in csp_of or at is None or at < now - LOOKBACK:
            continue
        if seen.get(phone) and at <= seen[phone]:
            continue
        if any(message_log.is_automatic(t, at) for t in sent_times[phone]):
            continue      # the phone's automatic greeting, not the CSP
        fresh.setdefault(phone, []).append({
            "at": at.isoformat(),
            "text": str(r.get("body") or "")[:1000],
            "type": str(r.get("msg_type") or "text")})

    counts = {"new": 0, "updated": 0}
    for phone, items in fresh.items():
        items.sort(key=lambda i: i["at"])
        record = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id == csp_of[phone])).scalar_one_or_none()
        if record is None:
            continue
        draft = session.execute(select(CspReply).where(
            CspReply.phone == phone, CspReply.status == "draft")
        ).scalars().first()
        if draft is None:
            draft = CspReply(csp_id=record.csp_id, phone=phone, messages=[])
            session.add(draft)
            counts["new"] += 1
        else:
            counts["updated"] += 1
        draft.messages = list(draft.messages or []) + items
        draft.last_in_at = message_log._parse_time(items[-1]["at"])
        texts = [i["text"] or f"({i['type']})" for i in draft.messages]
        draft.intents, draft.reply_text, draft.action = compose(
            session, record, texts)
        draft.status, draft.note = "draft", ""
        if draft.intents == ["thanks"]:
            draft.status, draft.note = "skipped", "no reply needed"
        elif record.send_hold:
            draft.status, draft.note = "skipped", f"on hold: {record.send_hold}"
    # Drafts nobody sent in time are out of date.
    for old in session.execute(select(CspReply).where(
            CspReply.status == "draft",
            CspReply.last_in_at < now - LOOKBACK)).scalars():
        old.status, old.note = "expired", "not sent within 3 days"
    session.flush()
    return counts


# ---- sending ------------------------------------------------------------

def send(session, reply: CspReply, by: str, text: Optional[str] = None,
         wa=None) -> CspReply:
    """Send this reply (edited text if given), then do what it promised."""
    from app.models.csp_record import CSPRecord
    from app.models.whatsapp_message import KIND_OTHER
    from app.services import assistant_tools, message_log, message_sender
    from app.services import data_request_service as drs
    from app.services import whatsapp_platform

    wa = wa or whatsapp_platform
    record = session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == reply.csp_id)).scalar_one_or_none()
    if record is None:
        raise ValueError("This CSP is no longer in the records.")
    if record.send_hold:
        raise ValueError(f"Nothing is sent to this CSP: {record.send_hold}")
    body = clean(text if text is not None else reply.reply_text)
    if not body:
        raise ValueError("The reply is empty.")

    outcome = wa.send(reply.phone, assistant_tools.WHATSAPP_WORDING,
                      {"name": record.name or "CSP", "message": body},
                      source_name=message_log.source_name("chat", record.csp_id))
    message_log.record(session, kind=KIND_OTHER, mobile=reply.phone,
                       outcome=outcome, csp_id=record.csp_id,
                       csp_name=record.name or "")
    reply.reply_text, reply.decided_by = body, by
    if outcome["status"] == wa.PENDING:
        reply.note = ("WhatsApp is checking the wording (first time only) — "
                      "not sent yet; try again later")
        return reply
    if outcome["status"] != wa.SENT:
        reply.status = "failed"
        reply.note = f"not sent: {outcome.get('reason', '')}"[:500]
        return reply

    reply.status, reply.sent_at = "sent", datetime.now(timezone.utc)
    reply.note = ""
    if reply.action == "fresh_link":
        # The old link is closed so the new one is the only one.
        drs.cancel(session, record.csp_id,
                   "the CSP said the link does not work — a new one was sent")
        out = message_sender.ask_for_details(
            session, record, verify=(record.origin == "baseline"), manual=True)
        reply.note = ("new link sent" if out.get("sent")
                      else f"new link NOT sent: {out.get('reason', '')}")[:500]
    logger.info("csp_replies: reply sent to CSP %s by %s (%s)", record.csp_id,
                by, ", ".join(reply.intents or []))
    return reply


def run(session, now: Optional[datetime] = None, wa=None,
        sending_hours: bool = True) -> Dict[str, int]:
    """One pass: read the inbox; in auto mode, send what is ready."""
    from app.services import whatsapp_platform

    wa = wa or whatsapp_platform
    now = now or datetime.now(timezone.utc)
    mode = get_mode(session)
    if mode == "off":
        return {"mode": mode}
    counts = {"mode": mode, **collect(session, wa, now), "sent": 0}
    session.commit()
    if mode != "auto" or not sending_hours:
        return counts
    ready = session.execute(select(CspReply).where(
        CspReply.status == "draft", CspReply.last_in_at <= now - QUIET)
        .order_by(CspReply.last_in_at)).scalars().all()
    for reply in ready:
        today = session.execute(select(func.count()).select_from(CspReply).where(
            CspReply.csp_id == reply.csp_id, CspReply.status == "sent",
            CspReply.decided_by == "automatic",
            CspReply.sent_at >= now - timedelta(days=1))).scalar() or 0
        if today >= AUTO_PER_DAY:
            reply.note = f"waiting: {AUTO_PER_DAY} automatic replies already today"
            continue
        try:
            send(session, reply, "automatic", wa=wa)
            counts["sent"] += reply.status == "sent"
        except ValueError as e:
            reply.status, reply.note = "skipped", str(e)
        session.commit()
    return counts


def as_row(reply: CspReply, name: str = "") -> dict:
    return {
        "id": str(reply.id),
        "csp_id": reply.csp_id,
        "csp_name": name,
        "messages": reply.messages or [],
        "last_in_at": reply.last_in_at.isoformat() if reply.last_in_at else None,
        "intents": [{"key": i, "label": INTENT_LABEL.get(i, i)}
                    for i in (reply.intents or [])],
        "reply_text": reply.reply_text,
        "action": reply.action,
        "status": reply.status,
        "note": reply.note,
        "decided_by": reply.decided_by,
        "sent_at": reply.sent_at.isoformat() if reply.sent_at else None,
    }
