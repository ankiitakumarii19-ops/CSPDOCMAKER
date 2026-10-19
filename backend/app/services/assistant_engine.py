"""
CSP DocMaker — the ask-anything chat, without an AI model (tracker No. 116)

Asked for 19 Oct 2026: "I don't want an LLM, Claude or Cloudflare — make it
deterministic, with a knowledge base, so the answers are accurate." The
same question always gets the same answer, and every fact in it comes from
the app's own records or from the Knowledge Base an Admin wrote.

How a question is read, in this order:

  1. Hello / help                    -> what the chat can do.
  2. "remind / message <CSP> ..."     -> a DRAFT message (sent only on Send).
  3. A CSP named in it (code, part of a code, or a name together with a
     word like "documents" or "RBO"), or "his / iska ..." after a CSP was
     discussed                       -> that CSP's documents, a contact,
                                        photo, missing details, delivery,
                                        WhatsApp status, or all its details.
  4. "how many / list CSPs ..."       -> a count and list, with filters (no
                                        photo, no documents, details missing,
                                        KO / Sub-KO, a district/state/RM).
  5. The Knowledge Base               -> the best-matching entry's answer.
  6. A bare name                      -> the CSPs it matches.
  7. Nothing fits                     -> says so plainly, offers close
                                        entries, and records the question
                                        for an Admin (Knowledge Base screen).

Questions are understood in English, Hinglish and Hindi; answers are in
English. RMs get answers about their own CSPs only — every lookup goes
through assistant_tools, which applies csp_access.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.csp_photo import CSPPhoto
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentFormat, DocumentType, EmailStatus
from app.models.stored_document import StoredDocument
from app.services import assistant_tools, csp_access, knowledge_service
from app.services.assistant_tools import ToolError
from app.services.missing_data_service import check_missing_data, document_label

logger = logging.getLogger(__name__)

LIST_LIMIT = 10

HELP = (
    "I answer from the app's own records and the Knowledge Base — no AI, "
    "so the same question always gets the same answer. Try:\n"
    "- **Documents of 1A850466** (with Download buttons)\n"
    "- **RBO number of 1A851727** — also RM, ASM, DC, branch, mobile, "
    "email, address\n"
    "- **Is the photo of 1A851727 on file?** / **What is missing for "
    "1A851727?**\n"
    "- **Were the documents of 1A851727 mailed?** / **WhatsApp status of "
    "1A851727**\n"
    "- **How many CSPs in Bihar?** / **CSPs without photo**\n"
    "- **Remind 1A851727 to send their photo by Friday** (a draft; nothing "
    "goes until you press Send)\n"
    "- Questions about the process, e.g. **What is a BCP?**")

SUGGESTIONS = [
    "Documents of 1A850466",
    "RBO number of 1A851727",
    "How many CSPs without photo?",
    "What is a BCP?",
]


@dataclass
class Answer:
    reply: str
    cards: List[dict] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    # What kind of answer it was, for the log: help, draft, csp, list,
    # knowledge, search, unknown.
    kind: str = "unknown"


# ---- reading the question ----------------------------------------------------------

# A CSP code has letters and digits (1A850466; a Sub-KO adds 1-2). A mobile
# number is digits only, so it is never taken for a code.
CODE = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{6,12}\b")


def _norm(text: str) -> str:
    return " " + " ".join(re.findall(r"\w+", (text or "").lower())) + " "


def _has(text: str, *phrases) -> bool:
    """Whether any phrase occurs as whole words in the normalised text."""
    return any(f" {p} " in text for p in phrases)


GREETING = ("hi", "hello", "hey", "namaste", "namaskar", "help", "madad",
            "नमस्ते", "मदद", "hii", "helo", "good morning", "start")

DRAFT_WORDS = ("remind", "reminder", "message", "msg", "inform", "notify",
               "yaad", "याद", "sandesh", "संदेश", "text them", "write to",
               "send a message", "send message", "send whatsapp",
               "whatsapp karo", "whatsapp kar do", "bol do", "bolo")

DOC_WORDS = ("document", "documents", "doc", "docs", "pdf", "pdfs",
             "dastavez", "dastavej", "दस्तावेज़", "दस्तावेज", "डॉक्यूमेंट",
             "id card", "idcard", "appointment letter", "appointment",
             "training certificate", "certificate", "certificates", "bcp",
             "letter", "download")
PHOTO_WORDS = ("photo", "photos", "pic", "picture", "image", "tasveer",
               "फोटो", "तस्वीर", "selfie")
MISSING_WORDS = ("missing", "pending", "incomplete", "baki", "baaki",
                 "बाकी", "कमी", "required", "needed", "what is needed",
                 "kya chahiye", "why pending", "stuck", "atka")
DELIVERY_WORDS = ("mailed", "emailed", "delivered", "delivery", "sent",
                  "bheja", "bheje", "भेजा", "status")
WHATSAPP_WORDS = ("whatsapp", "wa", "व्हाट्सएप")
DETAIL_WORDS = ("details", "detail", "info", "information", "jankari",
                "जानकारी", "profile", "record", "about", "everything")
LEVEL_WORDS = ("ko", "sub ko", "subko", "sub", "level")
PRONOUNS = ("his", "her", "their", "its", "him", "them", "this csp",
            "that csp", "same csp", "uska", "uski", "uske", "iska", "iski",
            "iske", "unka", "unki", "unke", "इसका", "उसका", "इसकी", "उसकी")
# A question about what something IS goes to the Knowledge Base even when a
# CSP was just discussed ("What is a BCP?" is not "this CSP's BCP").
DEFINE_WORDS = ("what is", "what are", "what does", "meaning", "mean",
                "explain", "matlab", "kya hota", "kya hai", "define", "why",
                "how does", "how do", "how to", "how can", "kaise", "क्या है",
                "मतलब")
COUNT_WORDS = ("how many", "kitne", "kitni", "कितने", "कितनी", "count",
               "number of", "total", "list", "list of", "all csps",
               "show csps", "which csps", "csps with", "csps without",
               "csps in", "csps of", "csps under", "sabhi", "सभी")

CONTACT = ("number", "no", "contact", "phone", "mobile", "mob", "call",
           "नंबर", "मोबाइल", "फोन", "sampark", "संपर्क")
EMAIL = ("email", "mail", "e mail", "ईमेल", "मेल")
NAME = ("name", "naam", "नाम", "who", "kaun", "कौन")

# (role words, name field, email field, contact field, other fields)
ROLES = [
    (("rbo",), "rbo_name", None, "rbo_contact", ()),
    (("rm", "relationship manager"), "rm_name", "rm_email", None, ()),
    (("asm",), "asm_name", "asm_email", "asm_contact", ()),
    (("dc",), "dc", "dc_email", "dc_contact", ()),
    (("branch", "shakha", "शाखा", "bank branch"), "branch_name", None,
     "branch_contact", ("branch_code",)),
    (("ao",), "ao", None, None, ()),
    (("lho",), "lho", None, None, ()),
    (("circle head", "circle"), "circle_head", None, None, ()),
]
PLACE = [
    (("address", "pata", "पता", "location", "kahan", "where"),
     ("address", "district", "state")),
    (("district", "zila", "jila", "जिला", "ज़िला"), ("district",)),
    (("state", "rajya", "राज्य"), ("state",)),
    (("gender",), ("gender",)),
    (("branch code",), ("branch_code",)),
]
LABELS = dict(assistant_tools.CONTACT_FIELDS)
LABELS.update({"rm_email": "RM Email Id", "circle_head": "Circle Head",
               "gender": "Gender"})


def _codes(text: str) -> List[str]:
    return CODE.findall(text or "")


def _code_from_history(history: List[dict]) -> Optional[str]:
    """The CSP last talked about: the newest code in earlier turns."""
    for turn in reversed(history):
        found = _codes(turn.get("content") or "")
        if found:
            return found[-1]
    return None


def _requested_fields(t: str) -> List[str]:
    """Which CSP fields the question asks for, [] when none in particular."""
    for words, name, email, contact, others in ROLES:
        if _has(t, *words):
            if _has(t, *EMAIL) and email:
                return [email]
            if _has(t, *CONTACT) and contact:
                return [contact]
            if _has(t, *NAME) and not _has(t, *CONTACT, *EMAIL):
                return [name]
            return [f for f in (name, email, contact, *others) if f]
    for words, fields in PLACE:
        if _has(t, *words):
            return list(fields)
    if _has(t, *EMAIL):
        return ["email"]
    if _has(t, *CONTACT):
        return ["mobile"]
    return []


# ---- the CSP a question is about ---------------------------------------------------

async def _resolve(session, user, question: str, t: str, history: List[dict],
                   csp_words: bool):
    """(csp, None) for one CSP, (None, list card) when several match, or
    (None, None) when the question is about no CSP."""
    codes = _codes(question)
    for code in codes:
        try:
            return await assistant_tools.find_one(session, user, code), None
        except ToolError:
            data, card = await assistant_tools.find_csps(session, user, code)
            if data["total_matches"] == 1:
                return await assistant_tools.find_one(
                    session, user, card["items"][0]["csp_code"]), None
            if data["total_matches"] > 1:
                return None, card
            raise ToolError(f"No CSP with code {code} was found"
                            + ("" if csp_access.is_admin(user)
                               else " among your CSPs") + ".")
    if not csp_words:
        return None, None
    # A name together with a CSP word: "documents of Savita Kumari". Only
    # the CSP's name is searched — "circle head of Bihar" is not about the
    # CSPs who live in Bihar.
    name = _leftover_name(t)
    if name:
        named = await _by_name(session, user, name)
        if len(named) == 1:
            return named[0], None
        if len(named) > 1:
            items = [{"csp_code": c.csp_code or c.csp_id, "name": c.name,
                      "district": c.district, "state": c.state,
                      "branch_name": c.branch_name, "rm_name": c.rm_name}
                     for c in named[:LIST_LIMIT]]
            return None, {"type": "csp_list", "query": name,
                          "total": len(named), "items": items}
    # "his RBO number" after a CSP was discussed.
    earlier = _code_from_history(history)
    if earlier and (_has(t, *PRONOUNS) or not name):
        try:
            return await assistant_tools.find_one(session, user, earlier), None
        except ToolError:
            return None, None
    return None, None


async def _by_name(session, user, name: str) -> list:
    """CSPs (within access) whose name holds every word given."""
    query = select(CSPRecord)
    for word in name.split():
        query = query.where(CSPRecord.name.ilike(f"%{word}%"))
    query = assistant_tools._scoped(query, user).order_by(CSPRecord.csp_id)
    return list((await session.execute(query)).scalars().all())


_ALL_KEYWORDS = set()
for _group in (GREETING, DRAFT_WORDS, DOC_WORDS, PHOTO_WORDS, MISSING_WORDS,
               DELIVERY_WORDS, WHATSAPP_WORDS, DETAIL_WORDS, LEVEL_WORDS,
               PRONOUNS, COUNT_WORDS, CONTACT, EMAIL, NAME):
    for _p in _group:
        _ALL_KEYWORDS.update(_p.split())
for _role in ROLES:
    for _p in _role[0]:
        _ALL_KEYWORDS.update(_p.split())
for _place in PLACE:
    for _p in _place[0]:
        _ALL_KEYWORDS.update(_p.split())
_ALL_KEYWORDS.update({"csp", "csps", "agent", "agents", "kiosk", "of", "the",
                      "for", "show", "give", "send", "find", "search", "get",
                      "is", "are", "what", "please", "tell", "me", "on", "in",
                      "file", "there", "have", "has", "do", "you", "we",
                      "our", "a", "an", "and", "it", "this", "that", "with",
                      "without", "code", "id", "his", "her"})


def _leftover_name(t: str) -> str:
    """The words left after every known word is taken out — a name, if
    the question has one."""
    rest = [w for w in t.split()
            if w not in _ALL_KEYWORDS
            and w not in knowledge_service.STOPWORDS and len(w) > 1]
    return " ".join(rest)


# ---- answers about one CSP -------------------------------------------------------

def _who(csp) -> str:
    return f"{csp.name} ({csp.csp_code or csp.csp_id})"


async def _photo_on_file(session, csp) -> bool:
    stored = (await session.execute(
        select(func.count()).select_from(CSPPhoto)
        .where(CSPPhoto.csp_id == csp.csp_id))).scalar()
    return bool(stored) or bool((csp.photo_url or "").strip())


async def _delivery(session, csp) -> dict:
    """Per document type: 'mailed', 'failed' or None (never emailed)."""
    from app.models.email_document import EmailDocument
    from app.models.email_job import EmailJob
    from app.models.processing_job import ProcessingJob

    rows = (await session.execute(
        select(EmailDocument.document_type, EmailJob.status, EmailJob.sent_at)
        .join(EmailJob, EmailDocument.email_job_id == EmailJob.id)
        .join(ProcessingJob, EmailJob.processing_job_id == ProcessingJob.id)
        .where(ProcessingJob.csp_id == csp.csp_id))).all()
    out = {}
    for doc_type, status, sent_at in rows:
        key = getattr(doc_type, "value", doc_type)
        if status == EmailStatus.SENT:
            prev = out.get(key)
            if not (prev and prev[0] == "mailed" and prev[1] and sent_at
                    and prev[1] > sent_at):
                out[key] = ("mailed", sent_at)
        elif status == EmailStatus.FAILED and key not in out:
            out[key] = ("failed", None)
    return out


def _doc_types_for(csp) -> List[DocumentType]:
    from app.services import ko_level
    return ko_level.allowed_documents(csp.csp_code or csp.csp_id,
                                      list(DocumentType))


async def _about_csp(session, user, csp, question: str, t: str) -> Answer:
    who = _who(csp)

    if _has(t, *WHATSAPP_WORDS):
        return await _whatsapp_status(session, csp)

    if _has(t, *MISSING_WORDS):
        check = check_missing_data(csp, _doc_types_for(csp))
        lines = []
        for d in check.documents:
            if d.missing_fields:
                lines.append(f"- **{d.document_label}**: "
                             + ", ".join(f.field_label for f in d.missing_fields))
        photo = await _photo_on_file(session, csp)
        if not photo:
            lines.append("- **Photo**: not on file (needed for the ID Card "
                         "and Training Certificate)")
        reply = (f"Missing for {who}:\n" + "\n".join(lines) if lines else
                 f"Nothing is missing for {who}: every detail the documents "
                 "need is on record" + (", and the photo is on file." if photo
                                        else "."))
        _, card = await assistant_tools.csp_details(session, user, csp.csp_id)
        return Answer(reply, [card], kind="csp")

    if _has(t, *DELIVERY_WORDS) and (_has(t, *DOC_WORDS) or _has(
            t, "mailed", "emailed", "delivered", "delivery")):
        sent = await _delivery(session, csp)
        lines = []
        for doc_type in _doc_types_for(csp):
            state = sent.get(doc_type.value)
            label = document_label(doc_type)
            if state and state[0] == "mailed":
                when = f" on {state[1]:%d %b %Y}" if state[1] else ""
                lines.append(f"- **{label}**: emailed{when}")
            elif state:
                lines.append(f"- **{label}**: email FAILED — not delivered")
            else:
                lines.append(f"- **{label}**: not emailed yet")
        _, card = await assistant_tools.csp_documents(session, user, csp.csp_id)
        return Answer(f"Email delivery for {who}:\n" + "\n".join(lines),
                      [card], kind="csp")

    if _has(t, *DOC_WORDS):
        data, card = await assistant_tools.csp_documents(session, user,
                                                         csp.csp_id)
        docs = card["documents"]
        if not docs:
            reply = (f"No documents are stored for {who} yet. They are made "
                     "when an RM requests them, or automatically for a new "
                     "CSP once every detail and the photo are on record.")
        else:
            reply = (f"Yes — {len(docs)} document"
                     f"{'' if len(docs) == 1 else 's'} stored for {who}:\n"
                     + "\n".join(f"- {d['label']} (version {d['version']})"
                                 for d in docs)
                     + "\nUse the buttons below to download or share.")
            stored = {d["document_type"] for d in docs}
            absent = [document_label(dt) for dt in _doc_types_for(csp)
                      if dt.value not in stored
                      and dt != DocumentType.CSP_CERTIFICATE]
            if absent:
                reply += "\nNot made yet: " + ", ".join(absent) + "."
        return Answer(reply, [card], kind="csp")

    if _has(t, *PHOTO_WORDS):
        photo = await _photo_on_file(session, csp)
        reply = (f"Yes, a photo of {who} is on file; documents use its 35 × 45 "
                 "mm passport version." if photo else
                 f"No photo of {who} is on file. The ID Card and Training "
                 "Certificate cannot be made without one. An RM can upload it "
                 "on the CSP's card, or the CSP can send it through their "
                 "details form.")
        _, card = await assistant_tools.csp_details(session, user, csp.csp_id)
        return Answer(reply, [card], kind="csp")

    if _has(t, *LEVEL_WORDS) and not _requested_fields(t):
        from app.services import ko_level
        level = ko_level.label_for(csp.csp_code or csp.csp_id)
        reply = (f"{who} is a **{level}**." if level else
                 f"The code of {who} is neither 8 characters (KO) nor 9–10 "
                 "(Sub-KO), so its level cannot be told from it.")
        return Answer(reply, kind="csp")

    _, card = await assistant_tools.csp_details(session, user, csp.csp_id)
    wanted = _requested_fields(t)
    if wanted:
        lines = []
        for f in wanted:
            value = getattr(csp, f, None)
            value = str(value).strip() if value not in (None, "") else ""
            lines.append(f"- **{LABELS.get(f, f)}**: "
                         + (value or "not on record"))
        return Answer(f"For {who}:\n" + "\n".join(lines), [card], kind="csp")
    return Answer(f"Here is what is on record for {who}.", [card], kind="csp")


async def _whatsapp_status(session, csp) -> Answer:
    from app.models import whatsapp_message as wm
    rows = (await session.execute(
        select(wm.WhatsAppMessage)
        .where(wm.WhatsAppMessage.csp_id == csp.csp_id,
               wm.WhatsAppMessage.is_test.is_(False))
        .order_by(wm.WhatsAppMessage.sent_at.desc()).limit(5))).scalars().all()
    if not rows:
        return Answer(f"No WhatsApp to {_who(csp)} is on record.", kind="csp")
    kinds = {wm.KIND_DATA_REQUEST: "Data verification",
             wm.KIND_MISSING_DATA: "Data missing",
             wm.KIND_DOCUMENTS_READY: "Documents sent",
             wm.KIND_OTHER: "Message"}
    lines = []
    for m in rows:
        if m.send_status != wm.SEND_SENT:
            state = {wm.SEND_PENDING: "waiting for Meta's approval — not sent",
                     wm.SEND_REJECTED: "rejected",
                     wm.SEND_FAILED: "failed"}.get(m.send_status, m.send_status)
        else:
            state = {wm.DELIVERY_READ: "read",
                     wm.DELIVERY_DELIVERED: "delivered, not read",
                     wm.DELIVERY_FAILED: "could not reach the phone",
                     }.get(m.delivery_status or "", "sent")
        if m.responded_at:
            state += ", answered"
        lines.append(f"- **{kinds.get(m.kind, m.kind)}** "
                     f"({m.sent_at:%d %b %Y %H:%M}): {state}")
    return Answer(f"Latest WhatsApp messages to {_who(csp)}:\n"
                  + "\n".join(lines), kind="csp")


# ---- drafts ------------------------------------------------------------------------

# Fixed wordings for the common reminders (chosen 19 Oct 2026: fixed
# wordings when the request names one of these, the person's own words
# otherwise).
WORDINGS = {
    "photo": ("Please send a clear, recent photo of your face (passport "
              "style) so that your CSP documents can be made."),
    "details": ("Some details needed for your CSP documents are still "
                "missing. Please fill them in using the link we sent you on "
                "WhatsApp."),
    "documents": ("Your CSP documents are ready and have been sent to your "
                  "email. Please check your inbox."),
}
WORDING_WORDS = {
    "photo": PHOTO_WORDS,
    "details": ("details", "detail", "missing", "form", "jankari", "जानकारी",
                "information", "info"),
    "documents": DOC_WORDS,
}
_SECOND_PERSON = {"their": "your", "his": "your", "her": "your",
                  "them": "you", "him": "you", "they": "you", "he": "you",
                  "she": "you", "theirs": "yours", "themselves": "yourself"}
# Hinglish wording is kept as typed (no "Please" put in front).
_HINGLISH_VERBS = {"bhejo", "bhejiye", "bhej", "karo", "kariye", "kare",
                   "karein", "do", "dijiye", "dena", "de", "jama", "bharo",
                   "bhariye", "aaiye", "aao", "hai", "hain"}
_LEAD = re.compile(
    r"^(?:\s*(?:to|that|about|regarding|for|ki|ko|ke|ke liye|please|pls|"
    r"and|on|via|by|through|whatsapp|email|mail|[:\-–,.]))+\s*", re.I)


def _message_words(question: str, code: Optional[str]) -> str:
    """What the person wants said: the words after the CSP code (or after
    the trigger word when the CSP was named another way)."""
    text = question.strip()
    if code and code in text:
        text = text.split(code, 1)[1]
    else:
        m = re.search(r"\b(remind|message|msg|inform|notify|tell|"
                      r"whatsapp|email)\b", text, re.I)
        text = text[m.end():] if m else text
        text = re.sub(r"^\s*(?:the\s+)?csp\b", "", text, flags=re.I)
    text = _LEAD.sub("", text).strip()
    text = re.sub(r"\s+(?:on|via|by|through)\s+(?:whatsapp|e-?mail|mail)\s*$",
                  "", text, flags=re.I).strip()
    return text


def _tidy(words: str) -> str:
    out = []
    for w in words.split():
        bare = w.lower().strip(".,!?")
        if bare in _SECOND_PERSON:
            w = w.lower().replace(bare, _SECOND_PERSON[bare])
        out.append(w)
    text = " ".join(out)
    if not text:
        return text
    first = text.split()[0].lower()
    hinglish = any(w.lower().strip(".,!?") in _HINGLISH_VERBS
                   for w in text.split())
    if text.isascii() and not hinglish and first not in (
            "you", "your", "please", "kindly", "we", "the", "this", "i"):
        text = "please " + text
    return text[0].upper() + text[1:]


async def _draft(session, user, question: str, t: str,
                 history: List[dict]) -> Answer:
    csp, listed = await _resolve(session, user, question, t, history, True)
    if listed is not None:
        return Answer("Several CSPs match — which one should get the "
                      "message? Ask again with the CSP code.", [listed],
                      kind="draft")
    if csp is None:
        return Answer("Which CSP should get the message? Say it with the "
                      "CSP code, e.g. **Remind 1A851727 to send their photo "
                      "by Friday**.", kind="draft")
    code = next((c for c in _codes(question)), None)
    said = _message_words(question, code)

    channel = ("email" if _has(t, *EMAIL) else
               "whatsapp" if _has(t, *WHATSAPP_WORDS) else "auto")
    wording = None
    # A short request ("about photo", "for missing details") gets the fixed
    # wording; anything longer is the person's own words ("by Friday" kept).
    if len(said.split()) <= 3:
        for key, keys in WORDING_WORDS.items():
            if _has(_norm(said), *keys):
                wording = key
                break
    if wording == "documents":
        # The wording says they were emailed: only true once they were.
        mailed = [k for k, v in (await _delivery(session, csp)).items()
                  if v[0] == "mailed"]
        if not mailed:
            return Answer(f"The documents of {_who(csp)} have not been emailed "
                          "yet, so a 'documents sent to your email' message "
                          "would not be true. Nothing was drafted.",
                          kind="draft")
    message = WORDINGS[wording] if wording else _tidy(said)
    if not message:
        return Answer("What should the message say? For example: **Remind "
                      f"{csp.csp_code or csp.csp_id} to send their photo by "
                      "Friday**, or **Message "
                      f"{csp.csp_code or csp.csp_id}: your training is on "
                      "Monday**.", kind="draft")
    data, card = await assistant_tools.draft_message(
        session, user, csp.csp_id, message, channel)
    how = "WhatsApp" if card["channel"] == "whatsapp" else "email"
    return Answer(f"Here is the {how} draft for {_who(csp)}"
                  + (" (a fixed wording)" if wording else "")
                  + ". Check it and press **Send** — nothing has been sent.",
                  [card], kind="draft")


# ---- counts and lists --------------------------------------------------------------

async def _list(session, user, question: str, t: str) -> Optional[Answer]:
    query = assistant_tools._scoped(select(CSPRecord), user)
    csps = list((await session.execute(
        query.order_by(CSPRecord.csp_id))).scalars().all())
    what = []

    negative = _has(t, "without", "no", "missing", "bina", "बिना", "nahi",
                    "not", "none")
    if _has(t, *PHOTO_WORDS):
        photo_ids = set((await session.execute(
            select(CSPPhoto.csp_id).distinct())).scalars().all())
        csps = [c for c in csps
                if (c.csp_id in photo_ids or bool((c.photo_url or "").strip()))
                != negative]
        what.append("without a photo" if negative else "with a photo")
    elif _has(t, *DOC_WORDS) and negative:
        with_docs = set((await session.execute(
            select(StoredDocument.csp_id).distinct().where(
                StoredDocument.file_format == DocumentFormat.PDF)
        )).scalars().all())
        csps = [c for c in csps if c.csp_id not in with_docs]
        what.append("with no documents stored")
    elif _has(t, *DOC_WORDS):
        with_docs = set((await session.execute(
            select(StoredDocument.csp_id).distinct().where(
                StoredDocument.file_format == DocumentFormat.PDF)
        )).scalars().all())
        csps = [c for c in csps if c.csp_id in with_docs]
        what.append("with documents stored")
    elif _has(t, *MISSING_WORDS):
        csps = [c for c in csps
                if check_missing_data(c, _doc_types_for(c)).has_missing_data]
        what.append("with details missing")

    from app.services import ko_level
    if _has(t, "sub ko", "subko", "sub kos", "subkos"):
        csps = [c for c in csps if ko_level.level_of(c.csp_code or c.csp_id)
                == ko_level.SUB_KO]
        what.append("that are Sub-KOs")
    elif _has(t, "ko", "kos"):
        csps = [c for c in csps if ko_level.level_of(c.csp_code or c.csp_id)
                == ko_level.KO]
        what.append("that are KOs")

    place = _leftover_name(t)
    if place:
        p = place.lower()
        fits = [c for c in csps if any(
            p in (getattr(c, f, None) or "").lower()
            for f in ("district", "state", "rm_name", "branch_name", "lho"))]
        if not fits:
            return None    # the words are not a place or RM: not a list
        csps = fits
        what.append(f"matching “{place}”")

    total = len(csps)
    scope = "" if csp_access.is_admin(user) else " of yours"
    label = f"CSP{'' if total == 1 else 's'}{scope}"
    reply = f"**{total}** {label}" + (" " + " and ".join(what) if what else "")
    reply += "." if total else ". "
    if not total:
        reply += "None found."
    items = [{"csp_code": c.csp_code or c.csp_id, "name": c.name,
              "district": c.district, "state": c.state,
              "branch_name": c.branch_name, "rm_name": c.rm_name}
             for c in csps[:LIST_LIMIT]]
    cards = [{"type": "csp_list", "query": " ".join(what) or "all",
              "total": total, "items": items}] if items else []
    return Answer(reply, cards, kind="list")


# ---- setting up a workspace (No. 117) ------------------------------------------------

SETUP_WORDS = ("setup", "set up", "setup status", "what is left", "what s left",
               "whats left", "what is the issue", "what s the issue",
               "whats the issue", "what is the problem", "getting started",
               "get started", "checklist", "onboarding", "go live",
               "kya baki", "baki kya", "kya karna hai", "what should i do",
               "what do i do", "next step", "next steps")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SHEET_URL = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{20,})")
_SHEET_ID = re.compile(r"\b([A-Za-z0-9_-]{30,})\b")
_TAB = re.compile(r"\btab\s+[\"'“]?(.+?)[\"'”]?\s*[.?!]?\s*$", re.I)
ADD_WORDS = ("add", "invite", "grant", "give access", "access do", "jodo",
             "join")
DO_WORDS = ("create", "add", "make", "set up", "setup", "banao", "bana do",
            "jodo", "put")
ON_WORDS = ("turn on", "switch on", "enable", "start", "chalu", "on karo",
            "activate")


def _owner_only() -> Answer:
    return Answer("Only the Workspace Owner (Super Admin) can change the "
                  "workspace's setup. I can explain any step — ask e.g. "
                  "**how do I connect my Google Sheet?**", kind="setup")


async def _setup_overview(session, user) -> Answer:
    from app.services import workspace_setup
    steps = await workspace_setup.checklist(session, user, live=True)
    card = {"type": "setup", **workspace_setup.summary(steps),
            "steps": [s.card() for s in steps]}
    return Answer(workspace_setup.reply_for(steps), [card], kind="setup")


async def _setup(session, user, question: str, t: str) -> Optional[Answer]:
    """A setup question or command, or None when it is not one."""
    from app.services import agent_registry, workspace_setup
    from app.services import sheet_admin_service as sheets
    from app.config import get_settings

    owner = workspace_setup.is_owner(user)
    admin = csp_access.is_admin(user)
    if not (owner or admin):
        return None

    # Run the Setup agent's check now (it only reads and records).
    if _has(t, "setup check", "run setup", "check my setup", "check setup",
            "setup agent"):
        if not owner:
            return _owner_only()
        result = await workspace_setup.run_setup_check(user)
        lines = [f"Setup check: {result['summary'] or result['status']}."]
        for f in result["findings"]:
            lines.append(f"- **{f['severity'].upper()}** {f['title']}"
                         + (f" — {f['detail']}" if f.get("detail") else ""))
        return Answer("\n".join(lines), suggestions=["Setup status"],
                      kind="setup")

    # Add a member: "add rm priya@eko.co.in".
    email = _EMAIL.search(question)
    if email and _has(t, *ADD_WORDS):
        if not owner:
            return _owner_only()
        address = email.group(0).lower()
        role = ("super_admin" if _has(t, "super admin", "superadmin", "owner")
                else "admin" if _has(t, "admin") else
                "rm" if _has(t, "rm", "relationship manager") else None)
        if role is None:
            return Answer(f"As what should {address} be added — an RM or an "
                          "Admin?", suggestions=[f"add rm {address}",
                                                 f"add admin {address}"],
                          kind="setup")
        settings = get_settings()
        if not settings.email_domain_allowed(address):
            return Answer(f"{address} cannot be added: only "
                          f"{settings.allowed_email_domains_text} addresses "
                          "can be given access.", kind="setup")
        name = " ".join(p.title() for p in re.split(r"[._-]+",
                        address.split("@")[0]) if p)
        label = {"rm": "an RM", "admin": "an Admin",
                 "super_admin": "a Super Admin"}[role]
        card = await assistant_tools.propose_action(
            user, "add_member", {"email": address, "name": name, "role": role},
            f"Add {address} as {label}",
            f"{name} will be able to sign in to this workspace as {label} "
            "after signing up with this email.")
        return Answer(f"Here is what I'll do. Press **Do it** to add "
                      f"{address}, or Cancel.", [card], kind="setup")

    # Connect a sheet: "connect sheet <link> tab KOData".
    url = _SHEET_URL.search(question)
    sheet_id = url.group(1) if url else None
    if not sheet_id and _has(t, "sheet", "spreadsheet"):
        bare = _SHEET_ID.search(question)
        sheet_id = bare.group(1) if bare else None
    if sheet_id and _has(t, "connect", "add", "link", "jodo", "use", "sheet"):
        if not owner:
            return _owner_only()
        tab_match = _TAB.search(question.split(sheet_id, 1)[1]
                                if sheet_id in question else question)
        tab = tab_match.group(1).strip() if tab_match else ""
        try:
            tabs = await asyncio.to_thread(sheets.list_tabs, sheet_id)
        except Exception as e:
            return Answer(f"I could not open that sheet: {str(e)[:300]}\n\n"
                          "Usually it is not shared with the app: "
                          f"{workspace_setup._share_text()}. Then ask me "
                          "again.", kind="setup")
        titles = [x["title"] for x in tabs]
        if not tab or tab not in titles:
            first = (f"There is no tab called {tab!r}. " if tab else "")
            return Answer(first + "Which tab holds your CSPs? It has: "
                          + ", ".join(titles) + ".",
                          suggestions=[f"connect sheet {sheet_id} tab {x}"
                                       for x in titles[:6]], kind="setup")
        card = await assistant_tools.propose_action(
            user, "connect_sheet",
            {"spreadsheet_id": sheet_id, "tab": tab, "name": "CSP records"},
            f"Connect tab “{tab}” as your CSP sheet",
            "The sheet opens and has this tab. Once connected you can see and "
            "edit it on Setup → Sheets.",
            ["Note: the app does not yet load a new workspace's CSPs from its "
             "own sheet into the app (only Eko's sheet is read) — see "
             "**setup status**."])
        return Answer("The sheet opens. Press **Do it** to connect it, or "
                      "Cancel.", [card], kind="setup")

    # The standard message wordings.
    if _has(t, "wording", "wordings", "message templates", "message template",
            "default messages") and _has(t, *DO_WORDS):
        if not owner:
            return _owner_only()
        card = await assistant_tools.propose_action(
            user, "create_wordings", {},
            "Create the three standard message wordings",
            "Confirm your details, details still missing, and your documents "
            "— in English and Hindi, signed with your workspace's name. Any "
            "that already exist are left as they are.")
        return Answer("Press **Do it** to add them, or Cancel.", [card],
                      kind="setup")

    # The email channel.
    if _has(t, "email channel", "mail channel") or (
            _has(t, "channel") and _has(t, "email", "mail")
            and _has(t, *DO_WORDS)):
        if not owner:
            return _owner_only()
        from app.models.messaging import MessageChannel
        have = (await session.execute(select(MessageChannel).where(
            MessageChannel.kind == "email"))).scalars().first()
        if have is not None:
            return Answer(f"There is already an email channel "
                          f"(“{have.name}”"
                          + ("" if have.active else ", switched off") + ").",
                          kind="setup")
        card = await assistant_tools.propose_action(
            user, "add_email_channel", {}, "Add the email channel",
            "Emails to CSPs are sent through the server's email account and "
            "this becomes the default channel.")
        return Answer("Press **Do it** to add it, or Cancel.", [card],
                      kind="setup")

    # Turn an agent on.
    agent = next((k for k in agent_registry.keys() if _has(t, k)), None)
    if agent and _has(t, "agent") and _has(t, *ON_WORDS):
        if not owner:
            return _owner_only()
        from app.models.agent import AgentState
        state = (await session.execute(select(AgentState).where(
            AgentState.agent_key == agent))).scalars().first()
        if state is not None and state.enabled:
            return Answer(f"The {agent.title()} agent is already on.",
                          kind="setup")
        card = await assistant_tools.propose_action(
            user, "enable_agent", {"key": agent},
            f"Turn on the {agent.title()} agent",
            "It will run on its schedule for this workspace. You can turn it "
            "off again on Setup → Agents.")
        return Answer("Press **Do it** to turn it on, or Cancel.", [card],
                      kind="setup")

    # A question naming a CSP is about that CSP, not about setup.
    if _codes(_EMAIL.sub(" ", question)):
        return None

    # "What's left / what's the issue" — the whole checklist. (The built-in
    # how-to answers are matched later, with the Knowledge Base, so "how
    # many CSPs?" is still counted first.)
    if _has(t, *SETUP_WORDS):
        if not owner:
            return _owner_only()
        return await _setup_overview(session, user)
    return None


# ---- the whole question ------------------------------------------------------------

async def answer(question: str, history: List[dict], session: AsyncSession,
                 user: dict) -> Answer:
    """Answer one question. ToolError reasons (not found, no mobile, ...)
    become the answer; any other failure is the router's to report."""
    t = _norm(question)
    asked_by = (user.get("sub") or user.get("email") or "").lower()
    try:
        return await _answer(question, t, history, session, user, asked_by)
    except ToolError as e:
        return Answer(str(e), kind="csp")




async def _answer(question, t, history, session, user, asked_by) -> Answer:
    if t.strip() and all(w in _ALL_KEYWORDS or w in GREETING
                         for w in t.split()) and _has(t, *GREETING):
        return Answer(HELP, suggestions=SUGGESTIONS, kind="help")

    # 1b. Setting up the workspace (Owner; how-to answers for Admins too).
    #     Before CSP questions: an email or sheet id can look like a code.
    if not (_has(t, *DRAFT_WORDS) and _codes(question)):
        setup = await _setup(session, user, question, t)
        if setup is not None:
            return setup

    code_given = bool(_codes(question))
    csp_words = any(_has(t, *g) for g in (
        DOC_WORDS, PHOTO_WORDS, MISSING_WORDS, DETAIL_WORDS, WHATSAPP_WORDS,
        CONTACT, EMAIL)) or bool(_requested_fields(t))
    counting = _has(t, *COUNT_WORDS)
    pronoun = _has(t, *PRONOUNS)
    defining = _has(t, *DEFINE_WORDS)
    name = _leftover_name(t)
    # The Knowledge Base, plus the built-in setup how-to answers for Admins
    # and Owners (a new workspace's Knowledge Base starts empty).
    entries = await knowledge_service.active_entries(session)
    if csp_access.is_admin(user):
        from app.services import workspace_setup
        entries = entries + workspace_setup.guide()
    matches = knowledge_service.rank(question, entries)
    known = (matches[0] if matches
             and matches[0].score >= knowledge_service.ANSWER_AT else None)

    # 2. A message to a CSP — unless it asks about WhatsApp status, or is a
    #    Knowledge Base question that happens to say "message".
    drafting = _has(t, *DRAFT_WORDS) and not (
        _has(t, *WHATSAPP_WORDS) and _has(t, "status", "read", "delivered",
                                          "mila", "got"))
    if drafting and (code_given or pronoun or not known):
        return await _draft(session, user, question, t, history)

    # 3. A CSP named by code, or by name together with a CSP word.
    if code_given or (csp_words and name and not counting and not pronoun
                      and not defining):
        csp, listed = await _resolve(session, user, question, t, history,
                                     csp_words)
        if listed is not None:
            return Answer("Several CSPs match — which one? Tap it, or ask "
                          "again with its code.", [listed], kind="search")
        if csp is not None:
            return await _about_csp(session, user, csp, question, t)

    # 4. Counts and lists.
    if counting:
        listed = await _list(session, user, question, t)
        if listed is not None:
            return listed

    # 3b. "his RBO number" / "and the documents?" after a CSP was discussed;
    #     "What is a BCP?" still goes to the Knowledge Base.
    if csp_words and (pronoun or not (defining and known)):
        earlier = _code_from_history(history)
        if earlier and (pronoun or not name):
            csp, _ = await _resolve(session, user, question, t, history, True)
            if csp is not None:
                return await _about_csp(session, user, csp, question, t)

    # 5. The Knowledge Base (and the setup how-to answers).
    if known:
        logger.info("assistant_engine: knowledge entry %s (score %.2f)",
                    known.entry.id, known.score)
        if known.entry.id == "guide:0":
            # "How do I set up my workspace?" — the live checklist.
            from app.services import workspace_setup
            if not workspace_setup.is_owner(user):
                return _owner_only()
            return await _setup_overview(session, user)
        related = [m.entry.question for m in matches[1:3]
                   if m.score >= knowledge_service.SUGGEST_AT]
        return Answer(known.entry.answer, suggestions=related,
                      kind="setup" if str(known.entry.id).startswith("guide:")
                      else "knowledge")

    # 6. A bare name.
    if name and len(name) >= 2 and len(name.split()) <= 3:
        data, card = await assistant_tools.find_csps(session, user, name)
        if data["total_matches"]:
            return Answer(f"CSPs matching “{name}” — tap one for its "
                          "details.", [card], kind="search")

    # 7. Nothing fits: say so, and note it for an Admin.
    await knowledge_service.record_miss(session, question, asked_by)
    close = [m.entry.question for m in matches[:3]
             if m.score >= knowledge_service.SUGGEST_AT]
    if close:
        return Answer("I don't have an exact answer to that. Did you mean "
                      "one of these?", suggestions=close, kind="unknown")
    return Answer("Sorry, I don't have an answer to that yet. I've noted the "
                  "question so an Admin can add the answer to the Knowledge "
                  "Base.\n\n" + HELP, suggestions=SUGGESTIONS, kind="unknown")
