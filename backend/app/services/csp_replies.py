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
FEEDBACK = {"1": "CSP reply: feedback — got the documents",
            "2": "CSP reply: feedback — did not get them",
            "3": "CSP reply: feedback — something is wrong"}

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
    FEEDBACK["1"]: ("Dhanyavaad! Humein khushi hai ki aapko aapke documents "
                    "mil gaye."),
    FEEDBACK["2"]: ("Khed hai. Hum aapke documents dobara {email} par bhej "
                    "rahe hain - kripya inbox aur spam folder dekhein. Saath "
                    "hi data verification ka link bhej rahe hain - agar aapka "
                    "email galat hai to usme sahi email bharein."),
    FEEDBACK["3"]: ("Khed hai. Hum aapko data verification ka link bhej rahe "
                    "hain - usme jo galat hai use sudharein, phir aapke "
                    "documents dobara banenge."),
}
# What each feedback answer does when the reply is sent (No. 152). No. 163
# (28 Oct 2026): 2 also gets the data verification link — the email may be
# wrong, and the link is where they correct it.
FEEDBACK_ACTION = {"1": [], "2": ["resend_documents", "fresh_link"],
                   "3": ["fresh_link"]}

INTENT_LABEL = {
    "link": "Link does not open",
    "documents": "Asks about documents",
    "upload": "Upload / other papers",
    "wrong_details": "Wrong details",
    "thanks": "Thanks / ok — no reply needed",
    "knowledge": "Answered from the Knowledge Base",
    "else": "Not understood — sent to their RM",
    "feedback_1": "Feedback: got the documents, all correct",
    "feedback_2": "Feedback: did not get the documents",
    "feedback_3": "Feedback: something is wrong in them",
    "technical": "Technical issue — not answered",
}

# Technical problems that are not this project's (27 Oct 2026, No. 154:
# "for other technical issues don't reply"): devices, network / server,
# bank portal / software, transactions / money. No reply is written.
TECHNICAL_WORDS = (
    r"(?:^|\s)(machine|device|biometric|finger|fingerprint|thumb|scanner|printer|"
    r"morpho|mantra|startek|laptop|computer|cpu|internet|network|wifi|"
    r"server|site|portal|website|login|password|otp|error|crash|hang|"
    r"software|application|transaction|txn|debit|deduct|balance|"
    r"settlement|refund|withdraw|withdrawal|deposit|aeps|cash|atm|upi|"
    r"मशीन|नेटवर्क|सर्वर|ट्रांजैक्शन|पैसा)"
    r"|net nahi|app nahi|app band|paisa kat|paise kat|amount kat|money deduct")


def is_technical(text: str) -> bool:
    return _any(norm(text), TECHNICAL_WORDS)


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
               r"photo|pho|foto|pic|image|tasveer|"
               r"नाम|पता|नंबर|फोटो|तस्वीर)")
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

def compose(session, record, texts: List[str],
            feedback: Optional[str] = None) -> Tuple[List[str], str, Optional[str]]:
    """(intents, reply text, action) for these messages from this CSP.
    `feedback`: their answer to "did you get your documents?" (No. 152)
    when one of these messages was it — answered first. `action` is one or
    more of fresh_link / resend_documents, comma-separated."""
    from app.services import data_request_service as drs
    from app.services import knowledge_service

    entries = _entries(session)
    general = [e for q, e in entries.items() if not q.startswith("CSP reply:")]

    intents: List[str] = []
    knowledge: List[str] = []
    not_understood: List[str] = []
    technical = False
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
        elif is_technical(text):
            technical = True          # not answered (No. 154)
        elif norm(text):
            not_understood.append(norm(text))
    if feedback:
        intents.insert(0, f"feedback_{feedback}")
    if technical and not intents and not not_understood:
        return ["technical"], "", None
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
    actions: List[str] = []
    for intent in intents:
        if intent.startswith("feedback_"):
            answer = intent[-1]
            wording = _wording(entries, FEEDBACK[answer])
            if "{email}" in wording:
                wording = wording.replace("{email}", record.email or "aapke email")
            parts.append(wording)
            actions += [a for a in FEEDBACK_ACTION[answer] if a not in actions]
            if "fresh_link" in FEEDBACK_ACTION[answer]:
                action = "fresh_link"
        elif intent == "link":
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
    if action == "fresh_link" and "fresh_link" not in actions:
        actions.append("fresh_link")
    return intents, clean(text), ",".join(actions) or None


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
    from app.services import documents_feedback, message_log

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
        if (any(message_log.is_automatic(t, at) for t in sent_times[phone])
                and not documents_feedback.parse_answer(str(r.get("body") or ""))):
            continue      # the phone's automatic greeting, not the CSP —
            # but a quick "1" / "2" / "3" is an answer (No. 152)
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

        # An answer to "did you get your documents?" (No. 152): recorded
        # now; the reply (and what it does) waits like any other.
        first_at = message_log._parse_time(draft.messages[0]["at"])
        answered = session.execute(
            select(documents_feedback.CspFeedback).where(
                documents_feedback.CspFeedback.csp_id == record.csp_id,
                documents_feedback.CspFeedback.answered_at >= first_at)
        ).scalars().first()
        # Only an answer written in THIS conversation belongs to it.
        if answered is not None and (answered.answer_text or "") not in [
                (i["text"] or "")[:500] for i in draft.messages]:
            answered = None
        feedback = answered.answer if answered else None
        question = (None if answered
                    else documents_feedback.open_question(session, record.csp_id, now))
        for item in draft.messages:
            if feedback is None and question is not None:
                at = message_log._parse_time(item["at"])
                answer = documents_feedback.parse_answer(item["text"])
                if answer and at and at >= question.asked_at:
                    question.answer, question.answered_at = answer, at
                    question.answer_text = item["text"][:500]
                    feedback = answer
                    texts.remove(item["text"] or f"({item['type']})")
            elif feedback and documents_feedback.parse_answer(item["text"]) == feedback:
                if (item["text"] or "") in texts:
                    texts.remove(item["text"])
        draft.intents, draft.reply_text, draft.action = compose(
            session, record, texts, feedback=feedback)
        draft.status, draft.note = "draft", ""
        draft.draft_text = draft.reply_text
        if draft.intents == ["thanks"]:
            draft.status, draft.note = "skipped", "no reply needed"
        elif draft.intents == ["technical"]:
            draft.status = "skipped"
            draft.note = "technical issue — not answered (as decided)"
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
         wa=None, send_link: Optional[bool] = None) -> CspReply:
    """Send this reply (edited text if given), then do what it promised.
    send_link (No. 161): the person's choice whether the data verification
    link goes too — None keeps the agent's own plan."""
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

    from app.services import send_reason
    outcome = wa.send(reply.phone, assistant_tools.WHATSAPP_WORDING,
                      {"name": record.name or "CSP", "message": body},
                      source_name=message_log.source_name("chat", record.csp_id))
    with send_reason.because(send_reason.REPLY):
        message_log.record(session, kind=KIND_OTHER, mobile=reply.phone,
                           outcome=outcome, csp_id=record.csp_id,
                           csp_name=record.name or "")
    reply.reply_text, reply.decided_by = body, by
    # What the person did with the agent's draft (No. 154): kept as it was,
    # or changed — and by how much.
    from app.services.field_quality import levenshtein
    draft = clean(reply.draft_text or "")
    reply.edited = body != draft
    reply.edit_distance = levenshtein(draft, body) if reply.edited else 0
    if outcome["status"] == wa.PENDING:
        reply.note = ("WhatsApp is checking the wording (first time only) — "
                      "not sent yet; try again later")
        return reply
    if outcome["status"] != wa.SENT:
        reply.status = "failed"
        reply.note = f"not sent: {outcome.get('reason', '')}"[:500]
        return reply

    reply.status, reply.sent_at = "sent", datetime.now(timezone.utc)
    notes = []
    actions = [a for a in (reply.action or "").split(",") if a]
    if send_link is True and "fresh_link" not in actions:
        actions.append("fresh_link")
    elif send_link is False and "fresh_link" in actions:
        actions.remove("fresh_link")
    reply.action = ",".join(actions) or None
    if "fresh_link" in actions:
        notes.append(send_verification_link(session, record))
    if "resend_documents" in actions:
        from app.services import feedback_loops
        with send_reason.because(send_reason.NOT_RECEIVED):
            ok, why, _ = feedback_loops.resend_documents_email(session, record)
        notes.append(why if ok is not False else f"documents NOT resent: {why}")
    reply.note = "; ".join(notes)[:500]
    logger.info("csp_replies: reply sent to CSP %s by %s (%s)", record.csp_id,
                by, ", ".join(reply.intents or []))
    return reply


def send_verification_link(session, record) -> str:
    """The data verification message with a new link (No. 152); the old link
    is closed so the new one is the only one. Returns what happened, in words."""
    from app.services import data_request_service as drs
    from app.services import message_sender, send_reason
    drs.cancel(session, record.csp_id,
               "the CSP asked to change their details / the link did "
               "not work — a new one was sent")
    with send_reason.because(send_reason.CSP_ASKED):
        out = message_sender.ask_for_details(session, record, verify=True,
                                             manual=True)
    return ("new link sent" if out.get("sent")
            else f"new link NOT sent: {out.get('reason', '')}")


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
        "draft_text": reply.draft_text,
        "edited": reply.edited,
        "edit_distance": reply.edit_distance,
        "action": reply.action,
        "status": reply.status,
        "note": reply.note,
        "decided_by": reply.decided_by,
        "sent_at": reply.sent_at.isoformat() if reply.sent_at else None,
    }


# ---- what the agent learns from the week of drafts (No. 154) ------------

# The Knowledge Base wording behind a reply that answers one thing only —
# the ones a person's edit can replace.
RULE_ENTRY = {"link": LINK, "upload": UPLOAD, "wrong_details": WRONG,
              "else": ELSE, "feedback_1": FEEDBACK["1"],
              "feedback_2": FEEDBACK["2"], "feedback_3": FEEDBACK["3"]}
DATE = re.compile(r"\b\d{2} [A-Z][a-z]{2} \d{4}\b")


def as_wording(session, reply: CspReply) -> str:
    """A sent reply turned back into a wording: the CSP's own RM, email and
    dates put back as {rm}, {email}, {date}."""
    from app.models.csp_record import CSPRecord
    record = session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == reply.csp_id)).scalar_one_or_none()
    text = reply.reply_text or ""
    if record is not None:
        rm = rm_contact(session, record)
        if rm and rm in text:
            text = text.replace(rm, "{rm}")
        if record.email and record.email in text:
            text = text.replace(record.email, "{email}")
    return DATE.sub("{date}", text)


def learning(session, days: int = 30) -> dict:
    """Per kind of reply: how often the draft was sent as it was, changed,
    or skipped; the changes people made most, ready to become the wording."""
    from collections import Counter

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.execute(select(CspReply).where(
        CspReply.last_in_at >= since,
        CspReply.status.in_(("sent", "skipped")),
        CspReply.draft_text != "")).scalars().all()
    groups: Dict[str, dict] = {}
    edits: Dict[str, Counter] = {}
    for r in rows:
        key = " + ".join(r.intents or []) or "none"
        g = groups.setdefault(key, {
            "key": key, "intents": list(r.intents or []),
            "label": " + ".join(INTENT_LABEL.get(i, i) for i in (r.intents or [])),
            "sent": 0, "unchanged": 0, "edited": 0, "skipped": 0,
            "distance": 0})
        if r.status == "skipped":
            g["skipped"] += 1
            continue
        g["sent"] += 1
        if r.decided_by == "automatic" or not r.edited:
            g["unchanged"] += 1
        else:
            g["edited"] += 1
            g["distance"] += r.edit_distance or 0
            if len(r.intents or []) == 1 and r.intents[0] in RULE_ENTRY:
                edits.setdefault(key, Counter())[as_wording(session, r)] += 1
    out = []
    for key, g in sorted(groups.items(), key=lambda kv: -(kv[1]["sent"] + kv[1]["skipped"])):
        handled = g["sent"] + g["skipped"]
        g["unchanged_rate"] = round(100 * g["unchanged"] / g["sent"], 1) if g["sent"] else None
        g["avg_distance"] = round(g["distance"] / g["edited"], 1) if g["edited"] else None
        g["skipped_rate"] = round(100 * g["skipped"] / handled, 1) if handled else None
        g["suggested"] = [{"text": t, "times": n} for t, n in
                          edits.get(key, Counter()).most_common(3)]
        g["can_use"] = len(g["intents"]) == 1 and g["intents"][0] in RULE_ENTRY
        del g["distance"]
        out.append(g)
    sent = sum(g["sent"] for g in out)
    unchanged = sum(g["unchanged"] for g in out)
    return {"days": days, "sent": sent, "unchanged": unchanged,
            "edited": sum(g["edited"] for g in out),
            "skipped": sum(g["skipped"] for g in out),
            "unchanged_rate": round(100 * unchanged / sent, 1) if sent else None,
            "kinds": out}


def use_wording(session, intent: str, text: str, by: str) -> str:
    """A person's edit becomes the wording the agent drafts from now on."""
    from app.models.knowledge import KnowledgeEntry
    question = RULE_ENTRY.get(intent)
    if question is None:
        raise ValueError("This kind of reply has no single wording to change.")
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("The wording is empty.")
    entry = session.execute(select(KnowledgeEntry).where(
        KnowledgeEntry.category == CATEGORY,
        KnowledgeEntry.question == question)).scalars().first()
    if entry is None:
        entry = KnowledgeEntry(question=question, phrasings="", keywords="",
                               category=CATEGORY, answer=text, active=True)
        session.add(entry)
    entry.answer, entry.active, entry.updated_by = text, True, by
    logger.info("csp_replies: %s now drafts from a new wording (by %s)",
                question, by)
    return question
