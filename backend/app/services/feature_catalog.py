"""
CSP DocMaker — the features a Super Admin gives to roles and people
(PROJECT-REGISTER No. 199 / 206, Stage 2: Feature access and roles,
TK-015 - TK-019)

Each feature is a screen or an action, with the server routes that do it.
`default` is who has it TODAY (besides the Super Admin) — taken from the
routes' own role checks, and a test (test_feature_access) proves every
route's check equals its feature's `default`, so with nothing changed the
app behaves exactly as before.

The Super Admin always has every feature; that cannot be switched off.

  can_give_to   which kinds of people the feature may be GIVEN to beyond
                `default` (an RM, an Admin, or roles built on them). Empty =
                it can only be taken away, not given.
  locked        cannot be changed at all, for safety: who may add people,
                hand out features or connect sheets — someone who could do
                these could give themselves everything.
  all_csps      the screen lists or acts on every CSP, not only the person's
                own; shown as a warning when it is given to an RM.

Routes not listed here are basics everyone signed in keeps (sign-in, own
profile photo, the sheet freshness chips, what-may-I-do).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

RM, ADMIN = "rm", "admin"


@dataclass(frozen=True)
class Feature:
    key: str
    group: str
    title: str
    about: str
    default: Tuple[str, ...]                 # rm / admin, today
    routes: Tuple[Tuple[str, str], ...]      # (methods "GET,POST" or "*", path)
    can_give_to: Tuple[str, ...] = (RM, ADMIN)
    locked: bool = False
    all_csps: bool = False
    words: Tuple[str, ...] = ()              # chat words (ZU-02)
    # False only where the Super Admin does not have it today either
    # (making documents is the RM's screen).
    owner: bool = True


GROUPS: List[Tuple[str, str]] = [
    ("csps", "Working on CSPs"),
    ("watch", "Watching what happened"),
    ("setup", "Setting up the workspace"),
    ("owner", "Super Admin only"),
]

FEATURES: List[Feature] = [
    # ---- working on CSPs ----------------------------------------------
    Feature("csp_search", "csps", "Find and open CSPs",
            "Search CSPs, open one, its photo, chat and form links; the "
            "header search.",
            (RM, ADMIN),
            (("GET", "/api/csps/search"), ("GET", "/api/csps/{csp_id}"),
             ("GET", "/api/csps/{csp_id}/photo"),
             ("GET", "/api/csps/{csp_id}/conversation"),
             ("GET", "/api/csps/{csp_id}/verification-links"),
             ("GET", "/api/search")),
            words=("find csps", "search", "open csps", "find and open")),
    Feature("csp_message", "csps", "Message a CSP by hand",
            "Send one CSP a WhatsApp or email from their page.",
            (RM, ADMIN), (("POST", "/api/csps/{csp_id}/message"),),
            words=("message by hand", "send by hand", "message a csp",
                   "message csps", "manual message")),
    Feature("documents", "csps", "Make and send documents",
            "Choose a CSP's documents, check missing details, upload a "
            "photo, confirm and send.",
            (RM,),
            (("PATCH", "/api/csps/{csp_id}"),
             ("POST", "/api/csps/{csp_id}/auto-issue"),
             ("*", "/api/documents/"), ("*", "/api/workflows/")),
            can_give_to=(RM,), owner=False,
            words=("make documents", "send documents", "documents",
                   "issue documents")),
    Feature("action_required", "csps", "Action Required",
            "The bell: CSPs with details missing, and what was done.",
            (RM, ADMIN), (("GET", "/api/alerts"),),
            words=("action required", "bell", "alerts list")),
    Feature("database", "csps", "Database",
            "Every CSP's full record, photos and documents (another RM's "
            "CSP opens view only).",
            (RM, ADMIN),
            (("GET", "/api/admin/database"),),
            words=("database",)),
    Feature("csp_edit", "csps", "Edit a CSP",
            "Change a CSP's details from the Database (saved to the sheet).",
            (RM, ADMIN),
            (("GET", "/api/admin/database/{csp_id}/edit"),
             ("PUT", "/api/admin/database/{csp_id}")),
            words=("edit a csp", "edit csps", "edit csp", "edit")),
    Feature("sheets", "csps", "Sheets: see and edit rows",
            "The connected sheets' rows: read, change, add, remove.",
            (RM, ADMIN),
            (("GET", "/api/admin/sheets"),
             ("PATCH,POST,DELETE", "/api/admin/sheets/{source_id}/tabs/{tab}/")),
            words=("sheets", "sheet rows", "edit sheets")),
    Feature("chat", "csps", "Chat assistant",
            "Ask the chat about CSPs; drafts it offers to send.",
            (RM, ADMIN),
            (("*", "/api/assistant/chat"), ("*", "/api/assistant/drafts/"),
             ("GET", "/api/assistant/documents/"),
             ("GET", "/api/assistant/setup"), ("GET", "/api/assistant/status")),
            words=("chat", "assistant")),
    # ---- watching -------------------------------------------------------
    Feature("dashboard", "watch", "Dashboard overview",
            "Counts, filters, CSP list and its CSV download, audit log.",
            (ADMIN,),
            (("GET", "/api/admin/dashboard"), ("GET", "/api/admin/jobs"),
             ("GET", "/api/admin/audit-logs"), ("GET", "/api/admin/csp-"),
             ("GET", "/api/admin/csp/")),
            all_csps=True, words=("dashboard overview", "dashboard",
                                  "overview")),
    Feature("dashboards", "watch", "Build dashboards",
            "Make, change and see the extra dashboards.",
            (ADMIN,), (("*", "/api/admin/dashboards"),), all_csps=True,
            words=("build dashboards", "dashboards", "build a dashboard")),
    Feature("whatsapp", "watch", "WhatsApp messages",
            "Every WhatsApp sent: delivered, read, replied, failed.",
            (ADMIN,), (("*", "/api/admin/whatsapp-messages"),),
            all_csps=True, words=("whatsapp messages", "whatsapp")),
    Feature("emails", "watch", "Emails",
            "Every email sent: opened, bounced.",
            (ADMIN,), (("*", "/api/admin/email-messages"),), all_csps=True,
            words=("emails", "email screen")),
    Feature("replies", "watch", "Replies to CSPs",
            "What CSPs wrote back; send, change or skip the drafts.",
            (ADMIN,),
            (("GET", "/api/admin/csp-replies"),
             ("POST", "/api/admin/csp-replies/")),
            all_csps=True, words=("replies", "reply drafts")),
    Feature("data_quality", "watch", "Data quality",
            "Filled-in values, corrections, guardrails, loops, feedback.",
            (ADMIN,), (("*", "/api/admin/quality/"),), all_csps=True,
            words=("data quality", "quality")),
    # ---- setting up -----------------------------------------------------
    Feature("templates", "setup", "Document templates",
            "Upload and change the Word templates.",
            (ADMIN,), (("*", "/api/admin/templates"),),
            words=("templates", "document templates")),
    Feature("messaging", "setup", "Messaging",
            "Message wordings and channels; ask many CSPs at once.",
            (ADMIN,), (("*", "/api/admin/messaging"),), all_csps=True,
            words=("messaging", "wordings", "ask csps", "bulk message")),
    Feature("knowledge", "setup", "Knowledge Base",
            "The answers the chat and the reply agent use.",
            (ADMIN,), (("*", "/api/admin/knowledge"),),
            words=("knowledge base", "knowledge")),
    Feature("settings", "setup", "Settings",
            "See the settings; change the groups handed to Admins.",
            (ADMIN,),
            (("GET", "/api/admin/settings"), ("PUT,DELETE", "/api/admin/settings/{key}"),
             ("POST", "/api/admin/settings/history/"),
             ("POST", "/api/admin/settings/sheet")),
            can_give_to=(ADMIN,), words=("settings",)),
    Feature("rules_view", "setup", "See the workspace rules",
            "Read Workspace Rules (who may join, sign-in length).",
            (ADMIN,), (("GET", "/api/admin/workspace-rules"),),
            can_give_to=(ADMIN,), words=("workspace rules", "rules")),
    Feature("reply_mode", "setup", "Reply mode",
            "Switch the reply agent between Drafts, Automatic and Off.",
            (), (("PUT", "/api/admin/csp-replies/mode"),),
            can_give_to=(ADMIN,), words=("reply mode",)),
    Feature("agents", "setup", "Agents",
            "See the background jobs; run, switch on / off, decide findings.",
            (), (("*", "/api/admin/agents"),), can_give_to=(ADMIN,),
            words=("agents", "agent page")),
    # ---- the Super Admin's alone ---------------------------------------
    Feature("access", "owner", "Access: add and remove people",
            "Admins may do it only if Workspace Rules says so.",
            (ADMIN,), (("*", "/api/admin/access"),), can_give_to=(),
            locked=True),
    Feature("access_history", "owner", "Sign-in history and sheet sync",
            "Who signed in when; read the access sheet now.",
            (), (("GET", "/api/admin/access/logins"),
                 ("POST", "/api/admin/access/sync")), can_give_to=(),
            locked=True),
    Feature("feature_access", "owner", "Feature access",
            "This page: who has which feature.",
            (), (("*", "/api/admin/feature-access"),), can_give_to=(),
            locked=True),
    Feature("rules_change", "owner", "Change the workspace rules",
            "", (), (("PUT", "/api/admin/workspace-rules"),), can_give_to=(),
            locked=True),
    Feature("settings_handover", "owner", "Hand settings groups to Admins",
            "", (), (("PUT", "/api/admin/settings/admin-groups"),),
            can_give_to=(), locked=True),
    Feature("sheet_connections", "owner", "Connect or remove sheets",
            "", (),
            (("POST,PATCH,DELETE", "/api/admin/sheets"),
             ("POST,PATCH,DELETE", "/api/admin/sheets/{source_id}"),
             ("POST", "/api/admin/sheets/{source_id}/tabs")),
            can_give_to=(), locked=True),
    Feature("connections", "owner", "Connections",
            "The workspace's own sheets, email, WhatsApp and CRM; their "
            "passwords and keys.", (),
            (("*", "/api/admin/connections"),), can_give_to=(), locked=True),
    Feature("columns", "owner", "Columns",
            "Which sheet column is which field (guessed from the sheet).",
            (), (("*", "/api/admin/columns"),), can_give_to=(), locked=True),
    Feature("setup_guide", "owner", "Setup guide",
            "Every setup step, test mode, going live, the dry run.", (),
            (("*", "/api/admin/setup-guide"),), can_give_to=(), locked=True),
    Feature("workspace_admin", "owner", "Export or close the workspace",
            "Download all its data; switch the workspace off.", (),
            (("*", "/api/admin/workspace/"),), can_give_to=(), locked=True),
    Feature("setup_actions", "owner", "Setup done by the chat (Do it)",
            "", (), (("*", "/api/assistant/actions/"),), can_give_to=(),
            locked=True),
]

BY_KEY: Dict[str, Feature] = {f.key: f for f in FEATURES}
assert len(BY_KEY) == len(FEATURES)

# Paths every signed-in person keeps.
BASICS = ("/api/profile/", "/api/quality/freshness", "/api/me/", "/api/auth/")


def _matches(rule: Tuple[str, str], method: str, path: str) -> int:
    """How well a rule matches: 0 = not; else the length of the matched path
    (exact matches beat prefixes, longer beats shorter)."""
    methods, pattern = rule
    if methods != "*" and method not in methods.split(","):
        return 0
    if path == pattern:
        return 10_000 + len(pattern)
    if pattern.endswith(("/", "-")) and path.startswith(pattern):
        return len(pattern)
    if path.startswith(pattern + "/"):
        return len(pattern)
    return 0


def feature_for(method: str, path: str) -> Optional[Feature]:
    """The feature a route belongs to (by its path template, e.g.
    /api/csps/{csp_id}), or None for the basics."""
    if path.startswith(BASICS):
        return None
    best, found = 0, None
    for f in FEATURES:
        for rule in f.routes:
            score = _matches(rule, method.upper(), path)
            if score > best:
                best, found = score, f
    return found


def find(text: str) -> List[Feature]:
    """Features named in a chat message, by fixed words (longest wins)."""
    t = " " + " ".join(text.lower().replace("-", " ").split()) + " "
    hits = []
    for f in FEATURES:
        if f.locked:
            continue
        best = 0
        for w in f.words + (f.title.lower(),):
            if f" {w} " in t:
                best = max(best, len(w))
        if best:
            hits.append((best, f))
    if not hits:
        return []
    top = max(b for b, _ in hits)
    return [f for b, f in hits if b == top]
