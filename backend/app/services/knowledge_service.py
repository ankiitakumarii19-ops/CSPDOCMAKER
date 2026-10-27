"""
CSP DocMaker — finding the knowledge-base answer to a question (No. 116)

No AI model. A question is matched to the entry whose question, phrasings
or keywords share the most meaningful words with it:

  1. Both sides are put in matching form: lower case, punctuation dropped,
     filler words dropped ("what", "is", "the", "kya", "hai", ...), plural
     "-s" taken off ("documents" = "document").
  2. Rare words count for more than common ones (a word found in one entry
     says more than one found in every entry).
  3. Each of the entry's phrasings is compared with the question; the best
     one is the entry's score (0 = nothing shared, 1 = the same words).
     A keyword of the entry found in the question adds a bonus.

The same question always picks the same entry. Below ANSWER_AT the chat
does not answer from the entry; between SUGGEST_AT and ANSWER_AT it offers
the entries as "Did you mean ...?"; below that the question is recorded as
one the chat could not answer (KnowledgeMiss), for an Admin to add.
"""

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeEntry, KnowledgeMiss

logger = logging.getLogger(__name__)

ANSWER_AT = 0.5
SUGGEST_AT = 0.25
KEYWORD_BONUS = 0.3

# Words that carry no meaning for matching, in English, Hinglish and Hindi.
STOPWORDS = set("""
a an the is are was were be been am do does did can could will would should
shall may might i me my we our you your he she it its they them their his her
this that these those there here what which who whom whose how why when where
of for to in on at by with from about as into than then so if or and but not
no yes please tell know want need get got give show let any some all just
also very much more most own same such only ok okay hi hello hey
kya hai hain ka ki ke ko se me mein main mujhe hum tum aap ap yeh ye woh wo
kaise kab kyu kyon kyun kaun kahan kitna kitne kis kisi bhi aur ya to na nahi
batao bataiye bata chahiye hota hoti hote karna karo kare kar raha rahi rahe
क्या है हैं का की के को से में मुझे हम आप यह वह कैसे कब क्यों कौन कहाँ और या
""".split())


def words(text: str) -> List[str]:
    """The meaningful words of a text, in matching form."""
    out = []
    for w in re.findall(r"\w+", (text or "").lower()):
        if w in STOPWORDS or (len(w) < 2 and not w.isdigit()):
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def normalized(text: str) -> str:
    """The question as a matching key (for counting repeats)."""
    return " ".join(words(text))[:500]


def _phrasings(entry) -> List[str]:
    lines = [entry.question] + [p for p in (entry.phrasings or "").splitlines()]
    return [p for p in (line.strip() for line in lines) if p]


def _keywords(entry) -> List[str]:
    return [k for k in (normalized(k) for k in (entry.keywords or "").split(","))
            if k]


@dataclass
class Match:
    entry: KnowledgeEntry
    score: float


def rank(question: str, entries: List[KnowledgeEntry]) -> List[Match]:
    """Entries by how well they match, best first; ties by question text so
    the order never depends on the database's."""
    asked = set(words(question))
    if not asked or not entries:
        return []
    asked_text = " " + normalized(question) + " "

    vocab = [set().union(*(set(words(p)) for p in _phrasings(e)),
                         *(set(k.split()) for k in _keywords(e)))
             for e in entries]
    total = len(entries)

    def weight(w):
        seen = sum(1 for v in vocab if w in v)
        return math.log(1 + (total + 1) / (seen + 0.5))

    asked_weight = sum(weight(w) for w in asked)
    matches = []
    for e in entries:
        best = 0.0
        for p in _phrasings(e):
            own = set(words(p))
            if not own:
                continue
            shared = sum(weight(w) for w in asked & own)
            own_weight = sum(weight(w) for w in own)
            best = max(best, 2 * shared / (asked_weight + own_weight))
        if any(f" {k} " in asked_text for k in _keywords(e)):
            best += KEYWORD_BONUS
        if best > 0:
            matches.append(Match(e, min(best, 1.0)))
    matches.sort(key=lambda m: (-m.score, m.entry.question.lower()))
    return matches


# Wordings of the replies to CSPs on WhatsApp (No. 151): kept in the
# Knowledge Base so Admins can change them, but they are written to CSPs,
# not answers for staff — the chat never answers from them.
CSP_REPLIES = "CSP replies"


async def active_entries(session: AsyncSession) -> List[KnowledgeEntry]:
    return list((await session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.active.is_(True),
                                     KnowledgeEntry.category != CSP_REPLIES)
        .order_by(KnowledgeEntry.question))).scalars().all())


async def find(session: AsyncSession, question: str) -> List[Match]:
    return rank(question, await active_entries(session))


async def record_miss(session: AsyncSession, question: str,
                      asked_by: str) -> None:
    """Count a question the chat could not answer. Never stops the chat's
    answer: a failure here is logged with its traceback and the reply goes
    out anyway."""
    key = normalized(question)
    if not key:
        return
    try:
        async with session.begin_nested():
            miss = (await session.execute(select(KnowledgeMiss).where(
                KnowledgeMiss.normalized == key))).scalars().first()
            now = datetime.now(timezone.utc)
            if miss is None:
                session.add(KnowledgeMiss(
                    normalized=key, question=question.strip()[:500],
                    times_asked=1, last_asked_by=asked_by,
                    first_asked_at=now, last_asked_at=now))
            else:
                miss.times_asked += 1
                miss.question = question.strip()[:500]
                miss.last_asked_by = asked_by
                miss.last_asked_at = now
        await session.commit()
    except Exception as e:
        logger.error("knowledge_service.record_miss: could not record an "
                     "unanswered question (%d words): %s: %s",
                     len(key.split()), type(e).__name__, e, exc_info=True)


async def forget_miss(session: AsyncSession, question: str) -> Optional[int]:
    """Once an entry answers a question, it is no longer a miss."""
    miss = (await session.execute(select(KnowledgeMiss).where(
        KnowledgeMiss.normalized == normalized(question)))).scalars().first()
    if miss is None:
        return None
    count = miss.times_asked
    await session.delete(miss)
    return count
