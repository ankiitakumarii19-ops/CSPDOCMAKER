"""
CSP DocMaker — the chat guides a Workspace Owner through setup (No. 117)

Asked for 19 Oct 2026: "whenever a new workspace owner tries to set up their
workspace, the chat should guide them — what to do, how to do it, what the
issue is — and do what it can on their behalf." No AI (No. 116): everything
here is fixed rules over the workspace's own records.

Three parts:

  * checklist()  — every setup step, each Done / To do / Problem / Blocked,
                   with what to do and how. "Blocked" is used honestly for
                   what the app itself cannot do yet (a new workspace's CSPs
                   are not read from its own sheet — only Eko's are).
  * GUIDE        — built-in how-to answers about setting up, matched the
                   same way as the Knowledge Base. Built in because a new
                   workspace's Knowledge Base starts empty.
  * ACTIONS      — work the chat can do for the Owner. The chat only ever
                   PROPOSES one (a card with "Do it" / "Cancel"); it runs
                   when the Owner presses Do it, through the same server
                   functions the screens use, so the same checks apply, and
                   it is written to the audit log.

Owner only (role super_admin in the workspace in force): setup decides who
may sign in and where data comes from.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List, Optional

from sqlalchemy import func, select

from app.config import get_settings

logger = logging.getLogger(__name__)

DONE, TODO, PROBLEM, BLOCKED, OPTIONAL = (
    "done", "todo", "problem", "blocked", "optional")
STATUS_LABEL = {DONE: "Done", TODO: "To do", PROBLEM: "Problem",
                BLOCKED: "Blocked", OPTIONAL: "Optional"}

# Steps without which the workspace cannot issue documents. The chat opens
# with the checklist for an Owner while any of these is not done.
CORE = ("sheet", "records", "templates", "wordings", "channel")

# The four document codes the app can be asked for today (tracker item N:
# a template uploaded under any other code can never be requested).
DOCUMENT_CODES = [("CSP_ID_CARD", "ID Card"),
                  ("CSP_CERTIFICATE", "Appointment Letter"),
                  ("TRAINING_CERTIFICATE", "Training Certificate"),
                  ("BCP", "BCP")]


def is_owner(user: dict) -> bool:
    return (user.get("role") or "").lower() == "super_admin"


def service_account_email() -> str:
    """The address an Owner shares their Google Sheet with, read from the
    credentials file the app signs in to Google with. '' if unreadable."""
    path = get_settings().google_sheets_credentials_file
    try:
        with open(path, encoding="utf-8") as f:
            return (json.load(f).get("client_email") or "").strip()
    except (OSError, ValueError) as e:
        logger.warning("workspace_setup: cannot read the service account "
                       "email from %s: %s: %s", path, type(e).__name__, e)
        return ""


def _share_text() -> str:
    email = service_account_email()
    return (f"share it with **{email}** as an **Editor**" if email else
            "share it with the app's Google service account as an Editor "
            "(its address is in the server's Google credentials file — the "
            "server administrator can tell you)")


@dataclass
class Step:
    key: str
    title: str
    status: str
    detail: str
    how: str = ""
    # A question that makes the chat propose doing this step, if it can.
    ask: Optional[str] = None

    def card(self) -> dict:
        return {"key": self.key, "title": self.title, "status": self.status,
                "label": STATUS_LABEL[self.status], "detail": self.detail,
                "how": self.how, "ask": self.ask}


# ---- the checklist -------------------------------------------------------------

async def _sheet_problem(spreadsheet_id: str, tab: str) -> str:
    """'' when the sheet opens and has the tab; otherwise why not."""
    from app.services import sheet_admin_service as sheets
    try:
        tabs = await asyncio.to_thread(sheets.list_tabs, spreadsheet_id)
    except Exception as e:
        logger.warning("workspace_setup: sheet %s… cannot be opened: %s: %s",
                       spreadsheet_id[:8], type(e).__name__, e)
        return str(e)[:300]
    if tab and not any(t["title"] == tab for t in tabs):
        return (f"the sheet opens, but has no tab called {tab!r} (it has: "
                + ", ".join(t["title"] for t in tabs) + ")")
    return ""


async def checklist(session, user, live: bool = True) -> List[Step]:
    """Every setup step for the workspace in force. `live` also opens each
    connected sheet to check it can be read (a few seconds)."""
    from app.models.agent import AgentState
    from app.models.csp_record import CSPRecord
    from app.models.data_source import DataSource
    from app.models.document_template import DocumentTemplate
    from app.models.knowledge import KnowledgeEntry
    from app.models.messaging import (
        PURPOSE_DATA_REQUEST, PURPOSE_DOCUMENTS_READY, PURPOSE_MISSING_DATA,
        MessageChannel, MessageTemplate)
    from app.models.workspace_member import WorkspaceMember
    from app.services import workspace_service
    from app.workspace_context import current_workspace_id

    async def count(model, *where):
        q = select(func.count()).select_from(model)
        for w in where:
            q = q.where(w)
        return (await session.execute(q)).scalar() or 0

    eko = await workspace_service.is_eko(session, current_workspace_id())
    steps: List[Step] = []

    # 1. The team.
    members = await count(WorkspaceMember, WorkspaceMember.active.is_(True))
    steps.append(Step(
        "team", "Add your team", DONE if members > 1 else TODO,
        f"{members} people can sign in to this workspace." if members > 1
        else "Only you can sign in so far.",
        "Ask me e.g. **add rm priya@eko.co.in** (or admin), or use Setup → "
        "Access. They then sign up with that email and choose this "
        "workspace.",
        ask="How do I add my team?"))

    # 2. Where the CSPs come from.
    sources = list((await session.execute(select(DataSource).where(
        DataSource.active.is_(True),
        DataSource.purpose == "records"))).scalars().all())
    if not sources:
        steps.append(Step(
            "sheet", "Connect your CSP Google Sheet", TODO,
            "No sheet is connected.",
            f"Open your Google Sheet, {_share_text()}, then ask me **connect "
            "sheet <link to the sheet> tab <tab name>** (or use Setup → "
            "Sheets → Add a sheet).",
            ask="How do I connect my Google Sheet?"))
    else:
        problems = []
        if live:
            for s in sources:
                c = s.connection or {}
                why = await _sheet_problem(c.get("spreadsheet_id", ""),
                                           c.get("tab", ""))
                if why:
                    problems.append(f"**{s.name}**: {why}")
        names = ", ".join(s.name for s in sources)
        steps.append(Step(
            "sheet", "Connect your CSP Google Sheet",
            PROBLEM if problems else DONE,
            ("The app cannot read: " + "; ".join(problems)) if problems
            else f"Connected: {names}"
            + ("" if live else " (not opened just now)") + ".",
            (f"Check the link and tab name, and {_share_text()}."
             if problems else "")))

    # 3. CSPs in the app.
    records = await count(CSPRecord)
    if records:
        steps.append(Step("records", "CSPs loaded into the app", DONE,
                          f"{records} CSPs are in the app."))
    elif eko:
        steps.append(Step(
            "records", "CSPs loaded into the app", PROBLEM,
            "No CSPs yet — the sheet is read every minute by the background "
            "workers.",
            "If this stays empty, the background workers may not be running "
            "on the server; ask the server administrator."))
    else:
        steps.append(Step(
            "records", "CSPs loaded into the app", BLOCKED,
            "The app does not yet read a new workspace's own sheet into CSP "
            "records — only Eko's sheet is read. Connecting your sheet lets "
            "you see and edit it on Setup → Sheets, but your CSPs will not "
            "appear in the app, so no documents can be made for them yet.",
            "This needs development work in the app (reading each "
            "workspace's sheet, with its own column names). It is not "
            "something you can fix from here — tell the Eko team.",
            ask="Why are there no CSPs in my workspace?"))

    # 4. Document templates.
    templates = list((await session.execute(
        select(DocumentTemplate))).scalars().all())
    inactive = [t for t in templates if not t.active]
    if not templates:
        steps.append(Step(
            "templates", "Add your document templates", TODO,
            "You have no templates of your own, so documents would be made "
            "from Eko's four built-in designs.",
            "Upload a Word (.docx) file for each document on Setup → Document "
            "Templates, using one of these codes: "
            + ", ".join(f"{c} ({n})" for c, n in DOCUMENT_CODES)
            + ". Map any placeholder it does not fill itself, then activate.",
            ask="How do I add document templates?"))
    elif inactive:
        steps.append(Step(
            "templates", "Add your document templates", TODO,
            f"{len(inactive)} of {len(templates)} template(s) are not "
            "switched on yet: " + ", ".join(t.name for t in inactive) + ".",
            "Open Setup → Document Templates, map every placeholder, then "
            "activate it. Only a template that is switched on is used."))
    else:
        steps.append(Step("templates", "Add your document templates", DONE,
                          f"{len(templates)} template(s) in use."))

    # 5. Message wordings.
    purposes = set((await session.execute(select(MessageTemplate.purpose)
                    .where(MessageTemplate.active.is_(True)))).scalars().all())
    needed = [PURPOSE_DATA_REQUEST, PURPOSE_MISSING_DATA,
              PURPOSE_DOCUMENTS_READY]
    missing = [p for p in needed if p not in purposes]
    steps.append(Step(
        "wordings", "Message wordings", TODO if missing else DONE,
        ("Missing: " + ", ".join(p.replace("_", " ") for p in missing) + ".")
        if missing else "All three wordings are in place (confirm details, "
        "details missing, documents ready).",
        "Ask me **create the message wordings** — I add the three standard "
        "ones signed with your workspace's name; edit them later on Setup → "
        "Messaging." if missing else "",
        ask="create the message wordings" if missing else None))

    # 6. A way to reach CSPs.
    channels = list((await session.execute(select(MessageChannel).where(
        MessageChannel.active.is_(True)))).scalars().all())
    steps.append(Step(
        "channel", "A way to message CSPs", DONE if channels else TODO,
        ("Channels: " + ", ".join(f"{c.name} ({c.kind})" for c in channels)
         + ".") if channels else "No messaging channel, so no CSP can be "
        "emailed or asked for details.",
        "" if channels else "Ask me **add the email channel** — it sends "
        "through the server's email account. WhatsApp goes through Eko's "
        "WhatsApp platform and is added by the Eko team.",
        ask=None if channels else "add the email channel"))

    # 7. The Communication agent sends the asks on a schedule.
    comm = (await session.execute(select(AgentState).where(
        AgentState.agent_key == "communication"))).scalars().first()
    on = bool(comm and comm.enabled)
    steps.append(Step(
        "agent", "Turn on the Communication agent", DONE if on else OPTIONAL,
        "It is on." if on else "It is off (the default): CSPs with missing "
        "details are not chased on a schedule.",
        "" if on else "Ask me **turn on the communication agent** once a "
        "channel and the wordings are in place.",
        ask=None if on else "turn on the communication agent"))

    # 8. The Knowledge Base the chat answers from.
    entries = await count(KnowledgeEntry)
    steps.append(Step(
        "knowledge", "Write your Knowledge Base", DONE if entries else OPTIONAL,
        f"{entries} answer(s) written." if entries else
        "Empty — the chat cannot answer questions about your process yet.",
        "" if entries else "Add questions and answers on Setup → Knowledge "
        "Base."))

    # 9. Server settings that are not the Owner's to change.
    url = (get_settings().public_app_url or "").lower()
    if "localhost" in url or "127.0.0.1" in url:
        steps.append(Step(
            "server", "Public web address", BLOCKED,
            "The server's PUBLIC_APP_URL is a localhost address, so links "
            "sent to CSPs would open nothing on their phones.",
            "The server administrator sets PUBLIC_APP_URL."))
    return steps


def summary(steps: List[Step]) -> dict:
    core = [s for s in steps if s.key in CORE]
    return {"done": sum(1 for s in core if s.status == DONE),
            "total": len(core),
            "complete": all(s.status == DONE for s in core)}


def reply_for(steps: List[Step]) -> str:
    """The checklist as the chat's answer: progress, then what to do next."""
    s = summary(steps)
    lines = [f"**Workspace setup: {s['done']} of {s['total']} essential steps "
             "done.**"]
    blocked = [x for x in steps if x.status == BLOCKED]
    problems = [x for x in steps if x.status == PROBLEM]
    todo = [x for x in steps if x.status == TODO]
    if problems:
        lines.append("Fix first: " + "; ".join(
            f"**{x.title}** — {x.detail}" for x in problems))
    if todo:
        lines.append(f"Next: **{todo[0].title}** — {todo[0].how or todo[0].detail}")
    if blocked:
        lines.append("Blocked (not fixable from here): " + "; ".join(
            f"**{x.title}**" for x in blocked) + " — see below.")
    if s["complete"] and not blocked:
        lines.append("Everything essential is in place.")
    lines.append("Each step is below; tap a button and I'll do it or explain "
                 "it — nothing changes until you press **Do it**.")
    return "\n".join(lines)


# ---- built-in how-to answers -------------------------------------------------------

def guide() -> list:
    """Setup questions, matched like Knowledge Base entries."""
    share = _share_text()
    codes = "\n".join(f"- **{c}** — {n}" for c, n in DOCUMENT_CODES)
    entries = [
        ("How do I set up my workspace?",
         "setup\nset up workspace\nwhat should i do first\ngetting started\n"
         "workspace setup kaise kare\nonboarding",
         "setup, getting started, onboarding",
         "Ask me **setup status** — I'll check every step and tell you what "
         "is done, what is next and what is blocked, and I can do several "
         "steps for you."),
        ("How do I connect my Google Sheet?",
         "connect sheet\nadd google sheet\nsheet kaise jode\nlink my sheet",
         "connect sheet, google sheet",
         f"1. Open your Google Sheet and {share}.\n"
         "2. Copy the sheet's link from the browser.\n"
         "3. Ask me **connect sheet <link> tab <tab name>** — I check that it "
         "opens and show you a confirmation before adding it. (Or Setup → "
         "Sheets → Add a sheet.)"),
        ("Why can't the app open my sheet?",
         "sheet not opening\ncould not open spreadsheet\npermission denied "
         "sheet\nsheet error\n403",
         "could not open, permission, not shared",
         f"Almost always the sheet is not shared with the app: {share}. "
         "Also check the link is the full Google Sheets address and the tab "
         "name is spelt exactly as on the tab (capitals and spaces count)."),
        ("Which email do I share my sheet with?",
         "service account email\nshare sheet with whom\nkis email ko share",
         "service account, share",
         f"To let the app read and edit your sheet, {share}."),
        ("How do I add my team?",
         "add members\nadd rm\nadd admin\ninvite people\nteam kaise add kare",
         "add member, invite, team",
         "Ask me **add rm name@eko.co.in** or **add admin name@eko.co.in** "
         "(I confirm before adding), or use Setup → Access. The person then "
         "signs up with that email, picks the same role, and chooses your "
         "workspace at login. Only "
         f"{get_settings().allowed_email_domains_text} addresses can be "
         "added."),
        ("How do I add document templates?",
         "upload template\nadd template\ntemplate kaise upload kare\n"
         "word template",
         "template, docx, upload",
         "On Setup → Document Templates, upload a Word (.docx) file for each "
         "document. Use one of these codes — the app can only be asked for "
         f"these four today:\n{codes}\nIt maps the placeholders it "
         "recognises; map the rest, then switch the template on."),
        ("How do I set up messaging?",
         "messaging setup\nemail channel\nwhatsapp setup\nmessage kaise "
         "bheje",
         "channel, messaging",
         "Two things are needed: a **channel** (ask me **add the email "
         "channel**; WhatsApp is added by the Eko team) and the **wordings** "
         "(ask me **create the message wordings**). Then turn on the "
         "Communication agent to chase missing details on a schedule."),
        ("Why are there no CSPs in my workspace?",
         "no csps\ncsp not showing\nmy csps are missing\ncsp kyun nahi dikh "
         "rahe",
         "no csp, records",
         "The app does not yet read a new workspace's own sheet into CSP "
         "records — only Eko's sheet is read. You can connect and edit your "
         "sheet on Setup → Sheets, but your CSPs will not appear in the app "
         "until that is built. Tell the Eko team; it is not something you "
         "can fix from here."),
        ("What do the agents do?",
         "agents meaning\nwhich agents to turn on\ncommunication agent",
         "agent",
         "Agents are scheduled jobs, not AI: Data reads your sources, "
         "Verification checks details, Document makes documents, "
         "Communication chases CSPs for missing details (off until you turn "
         "it on), Monitoring watches for failures, Setup checks your "
         "configuration. Ask me **run the setup check** or **turn on the "
         "communication agent**."),
    ]
    return [SimpleNamespace(category="Setup", question=q, phrasings=p,
                            keywords=k, answer=a, id=f"guide:{i}")
            for i, (q, p, k, a) in enumerate(entries)]


# ---- what the chat can do for the Owner ----------------------------------------------

@dataclass
class Proposal:
    kind: str
    params: dict
    title: str
    detail: str
    extra: List[str] = field(default_factory=list)


ACTION_KINDS = ("add_member", "connect_sheet", "create_wordings",
                "add_email_channel", "enable_agent")


async def run(kind: str, params: dict, session, user) -> dict:
    """Do one confirmed action through the screens' own server functions.
    Returns {"ok": bool, "message": str}; a refusal from those functions
    (a wrong domain, an unshared sheet) is the message, not a crash."""
    from fastapi import HTTPException

    try:
        if kind == "add_member":
            from app.routers.access_router import GrantRequest, grant_access
            out = await grant_access(request=GrantRequest(
                email=params["email"], name=params["name"],
                role=params["role"]), session=session, user=user)
            role = {"rm": "RM", "admin": "Admin",
                    "super_admin": "Super Admin"}[params["role"]]
            return {"ok": True, "message": (
                f"{params['email']} {out['action']} as {role}. They sign up "
                "with that email, choose the same role, and pick this "
                "workspace at login.")}
        if kind == "connect_sheet":
            from app.routers.sheet_router import SourceIn, register_sheet
            await register_sheet(body=SourceIn(
                name=params["name"], spreadsheet_id=params["spreadsheet_id"],
                tab=params["tab"]), session=session, user=user)
            return {"ok": True, "message": (
                f"Connected tab {params['tab']!r} as {params['name']!r}. You "
                "can see and edit it on Setup → Sheets.")}
        if kind == "create_wordings":
            from app.models.workspace import Workspace
            from app.services.document_template_service import (
                sync_builtin_messages)
            from app.workspace_context import current_workspace_id
            ws = (await session.execute(select(Workspace).where(
                Workspace.id == current_workspace_id()))).scalars().first()
            added = await sync_builtin_messages(
                session, signature=f"Team {ws.name}" if ws else None)
            return {"ok": True, "message": (
                f"Added {added} message wording(s). Edit them any time on "
                "Setup → Messaging." if added else
                "The standard wordings were already there; nothing added.")}
        if kind == "add_email_channel":
            from app.routers.messaging_router import ChannelIn, add_channel
            await add_channel(body=ChannelIn(
                name="Email", kind="email", provider="smtp",
                secret_ref="SMTP_PASSWORD", is_default=True),
                session=session, user=user)
            return {"ok": True, "message": (
                "Email channel added. It sends through the server's email "
                "account.")}
        if kind == "enable_agent":
            from app.routers.agent_router import AgentToggle, toggle_agent
            await toggle_agent(key=params["key"],
                               body=AgentToggle(enabled=True),
                               session=session, user=user)
            return {"ok": True, "message": (
                f"The {params['key'].title()} agent is on.")}
    except HTTPException as e:
        await session.rollback()
        return {"ok": False, "message": str(e.detail)}
    raise ValueError(f"Unknown setup action {kind!r}")


async def run_setup_check(user) -> dict:
    """The Setup agent, run now (read-only: it records what it finds)."""
    from app.routers.agent_router import run_agent
    return await run_agent(key="setup", user=user)
