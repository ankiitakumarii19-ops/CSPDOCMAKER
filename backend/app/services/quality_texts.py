"""
CSP DocMaker — the words on Data quality, editable (No. 171)

Admin → Setup → Data quality shows three lists in words:

  * Context    — what the app reads (one row per sheet)
  * Harness    — how the app checks itself (one row per check)
  * Guardrails — the rules the app never breaks

Admins and Super Admins can now change the words. The live columns (when a
sheet was last read, where a check stands now) are still worked out by the
code, and the app's behaviour does not change: there is no AI to read
written rules (D1). What changes is what people read on the screen and what
the staff chat answers — each save rewrites the matching Knowledge Base
entry (category "Data quality").

Stored per workspace in Workspace.settings["quality_texts"]:
  {"context": {key: {"label", "used_for"}},
   "harness": {key: {"name", "watches", "how"}},
   "guardrails": [{"title", "detail"}]}
A key with no saved words shows the code's own.
"""

from typing import Dict, List, Optional

SETTINGS_KEY = "quality_texts"
CATEGORY = "Data quality"

# The Context rows' words (sync_runs.source → used for). Moved here from the
# screen so they can be overridden.
CONTEXT_USED_FOR = {
    "csp": "Every CSP's details; INFO fills the blanks (AO, RBO, DC, ASM, "
           "LHO, State, RM)",
    "authorization": "Who may sign in, and as which role",
    "source_sheets": "Old CSPs (Calling sheet) and new ones going live "
                     "(Lead raw data); holds",
    "address": "Addresses of old CSPs (temporary tab)",
}
CONTEXT_LABELS = {
    "csp": "CSP sheet",
    "authorization": "Sign-in list",
    "source_sheets": "Calling & Lead sheets",
    "address": "Address tab",
}

# The rules the app never breaks — AGENT.md "Never" and SKILL.md §10, in
# the owner's words.
DEFAULT_GUARDRAILS = [
    {"title": "No AI anywhere",
     "detail": "No LLM, Claude, Gemini, Cloudflare model or OCR. Every "
               "decision is a fixed rule; the same input gives the same "
               "result."},
    {"title": "Existing CSPs are left alone",
     "detail": "CSPs already in CSPDATA before the Calling / Lead import are "
               "never mailed documents or sent the verification WhatsApp."},
    {"title": "Photo is always 35 × 45 mm",
     "detail": "Every document photo is a white-background passport photo, "
               "cropped to 35 × 45 mm — never just scaled."},
    {"title": "The CSP fills only their own details",
     "detail": "Never DC, ASM, RM or LHO. AO and RBO Name are asked once, "
               "only when INFO cannot map them."},
    {"title": "Messages only 8 am – 8 pm, never to a CSP on hold",
     "detail": "Nothing is sent from a laptop: only the public server "
               "sends."},
    {"title": "Errors are never hidden",
     "detail": "Every failure is logged with its reason and shown on the "
               "screens."},
    {"title": "Secrets stay secret",
     "detail": "Passwords, keys and tokens never go into code, logs, "
               "screenshots or chat."},
    {"title": "Back up before a database change",
     "detail": "And ask before deleting anything."},
    {"title": "Two Ganesh Kumar accounts are two people",
     "detail": "@eko.co.in and @ekosupport.in are different people."},
    {"title": "No payment or billing", "detail": "Out of scope."},
    {"title": "Every request is recorded",
     "detail": "In PROJECT-REGISTER.md, with a number."},
]

# Limits, so a pasted book cannot fill the settings column.
MAX_TEXT = 1000
MAX_GUARDRAILS = 60

# Questions of the Knowledge Base entries a save rewrites. The first two
# were seeded by migration b3e5f7a9c1d2 (No. 149).
Q_CONTEXT = "What does the app read? (context)"
Q_HARNESS = "How does the app check itself? (harness)"
Q_GUARDRAILS = "What rules does the app never break? (guardrails)"


class TextError(ValueError):
    """A save refused, with a message fit to show."""


def _clean(value, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def stored(ws) -> dict:
    data = ((ws.settings or {}) if ws is not None else {}).get(SETTINGS_KEY)
    return data if isinstance(data, dict) else {}


def context_rows(ws) -> List[dict]:
    """Every Context row's words: saved, else the code's own."""
    saved = stored(ws).get("context") or {}
    rows = []
    for key, used_for in CONTEXT_USED_FOR.items():
        mine = saved.get(key) or {}
        rows.append({
            "key": key,
            "label": mine.get("label") or CONTEXT_LABELS[key],
            "used_for": mine.get("used_for") or used_for,
            "edited": bool(mine),
        })
    return rows


def apply_harness(ws, rows: List[dict]) -> List[dict]:
    """The harness rows with saved words in place of the code's."""
    saved = stored(ws).get("harness") or {}
    out = []
    for row in rows:
        mine = saved.get(row["key"]) or {}
        out.append({**row,
                    "name": mine.get("name") or row["name"],
                    "watches": mine.get("watches") or row["watches"],
                    "how": mine.get("how") or row["how"],
                    "edited": bool(mine)})
    return out


def guardrails(ws) -> List[dict]:
    saved = stored(ws).get("guardrails")
    if isinstance(saved, list):
        return saved
    return [dict(g) for g in DEFAULT_GUARDRAILS]


def validated(section: str, body, harness_keys: List[str]):
    """The words to store for one section, or TextError."""
    if section == "context":
        out = {}
        for item in body or []:
            key = item.get("key")
            if key not in CONTEXT_USED_FOR:
                raise TextError(f"Unknown sheet: {key!r}.")
            label, used_for = _clean(item.get("label"), 80), _clean(item.get("used_for"))
            if not label or not used_for:
                raise TextError("Every sheet needs a name and what it is used for.")
            if label != CONTEXT_LABELS[key] or used_for != CONTEXT_USED_FOR[key]:
                out[key] = {"label": label, "used_for": used_for}
        return out
    if section == "harness":
        out = {}
        for item in body or []:
            key = item.get("key")
            if key not in harness_keys:
                raise TextError(f"Unknown check: {key!r}.")
            words = {"name": _clean(item.get("name"), 80),
                     "watches": _clean(item.get("watches")),
                     "how": _clean(item.get("how"))}
            if not all(words.values()):
                raise TextError("Every check needs a name, what it watches "
                                "and how.")
            out[key] = words
        return out
    if section == "guardrails":
        items = [{"title": _clean(g.get("title"), 200),
                  "detail": _clean(g.get("detail"))} for g in body or []]
        items = [g for g in items if g["title"]]
        if len(items) > MAX_GUARDRAILS:
            raise TextError(f"At most {MAX_GUARDRAILS} guardrails.")
        return items
    raise TextError(f"Unknown section: {section!r}.")


def saved_settings(ws, section: str, value) -> dict:
    """Workspace.settings with this section replaced."""
    texts = dict(stored(ws))
    texts[section] = value
    return {**(ws.settings or {}), SETTINGS_KEY: texts}


def reset_harness_to_code(harness_rows: List[dict], saved: Dict[str, dict]
                          ) -> Dict[str, dict]:
    """Drop saved words equal to the code's own (nothing was changed)."""
    by_key = {r["key"]: r for r in harness_rows}
    return {k: v for k, v in saved.items()
            if any(v[f] != by_key[k][f] for f in ("name", "watches", "how"))}


# ---- the chat's answers ---------------------------------------------------

def context_answer(rows: List[dict]) -> str:
    lines = ["Everything the app decides is made from these:"]
    lines += [f"- **{r['label']}** — {r['used_for']}" for r in rows]
    lines.append("- **INFO tab** (in the CSP sheet) — fills blank AO, RBO, "
                 "DC, ASM, LHO, State and RM.")
    lines.append("- **Zoho Lead** — fills a blank email, address, state or "
                 "gender before a CSP is asked.")
    lines.append("When each was last read, and whether that is on time: "
                 "**Admin → Setup → Data quality → Context**, and the "
                 "coloured chips at the top of every screen.")
    return "\n".join(lines)


def harness_answer(rows: List[dict]) -> str:
    lines = [f"- **{r['name']}** — {r['watches']}" for r in rows]
    lines.append("Where each stands now: **Admin → Setup → Data quality → "
                 "Harness**.")
    return "\n".join(lines)


def guardrails_answer(items: List[dict]) -> str:
    if not items:
        return "No guardrails are written down. Admin → Setup → Data quality."
    lines = ["The app never breaks these rules:"]
    lines += [f"{i}. **{g['title']}**" + (f" — {g['detail']}" if g["detail"] else "")
              for i, g in enumerate(items, 1)]
    lines.append("The list is on **Admin → Setup → Data quality → "
                 "Guardrails**.")
    return "\n".join(lines)


GUARDRAILS_PHRASINGS = ("what are the guardrails\nrules never broken\n"
                        "what will the app never do\napp kya kabhi nahi "
                        "karega\nguardrails kya hai\nnever rules")
GUARDRAILS_KEYWORDS = "guardrails, rules, never, never break"


async def write_answer(session, question: str, answer: str, who: str,
                       phrasings: str = "", keywords: str = "") -> None:
    """Rewrite (or add) the Knowledge Base entry with this question."""
    from sqlalchemy import select

    from app.models.knowledge import KnowledgeEntry

    entry = (await session.execute(select(KnowledgeEntry).where(
        KnowledgeEntry.question == question))).scalars().first()
    if entry is None:
        session.add(KnowledgeEntry(
            question=question, phrasings=phrasings, keywords=keywords,
            answer=answer[:4000], category=CATEGORY, active=True,
            updated_by=who))
    else:
        entry.answer = answer[:4000]
        entry.updated_by = who


def find_row(name: str, rows: List[dict], field: str) -> Optional[dict]:
    """The row whose name best matches `name` (words in common), or None."""
    words = set(_words(name))
    best, score = None, 0.0
    for row in rows:
        theirs = set(_words(row[field])) | set(_words(row["key"].replace("_", " ")))
        if not words or not theirs:
            continue
        s = 2 * len(words & theirs) / (len(words) + len(theirs))
        if s > score:
            best, score = row, s
    return best if score >= 0.5 else None


def _words(text: str) -> List[str]:
    import re
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in ("the", "a", "an", "of", "and", "tab", "sheet", "sheets")]
