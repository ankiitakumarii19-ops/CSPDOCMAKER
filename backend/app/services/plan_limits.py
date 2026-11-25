"""
CSP DocMaker — a workspace's plan limits and usage (No. 240, SaaS upgrade Stage 6)

Billing readiness, not billing: nothing is charged and no payment gateway is
called. A limit only applies when the Supreme Owner has put the workspace on
a plan that has one. No subscription row, status "unlimited", or a limit of
0 / NULL = no limit — every workspace today, and Eko always (its row is
"unlimited", set by the migration).

  check_documents(asked)        before documents are made (document_service):
                                over the month's limit -> RuntimeError
                                "waiting: ..." so the job is tried again
                                later, exactly like the daily ceiling (No. 216).
  check_users(session)          before someone is added to the workspace
                                (access_router): over the limit -> LimitError.
  usage(session, workspace_id)  documents this month, storage, people — for
                                the Supreme Owner's console and the workspace.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class LimitError(RuntimeError):
    """A plan limit was reached; the message says which and what to do."""


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _limits_sync(workspace_id) -> Optional[dict]:
    """The workspace's plan limits, or None (no plan / unlimited / unreadable)."""
    import psycopg2
    from app.config import get_settings
    s = get_settings().server
    try:
        conn = psycopg2.connect(
            host=s.database_host, port=s.database_port, user=s.database_user,
            password=s.database_password, dbname=s.database_name, connect_timeout=3)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ws.status, p.name, p.max_documents_month, p.max_users "
                    "FROM workspace_subscriptions ws JOIN plans p ON p.key = ws.plan_key "
                    "WHERE ws.workspace_id = %s", (str(workspace_id),))
                row = cur.fetchone()
                if row is None or row[0] == "unlimited":
                    return None
                limits = {"status": row[0], "plan": row[1],
                          "max_documents_month": row[2] or 0, "max_users": row[3] or 0}
                if limits["max_documents_month"]:
                    cur.execute("SELECT count(*) FROM stored_documents WHERE "
                                "workspace_id = %s AND created_at >= %s",
                                (str(workspace_id), _month_start()))
                    limits["documents_this_month"] = int(cur.fetchone()[0] or 0)
                return limits
        finally:
            conn.close()
    except Exception as e:
        # A plan that cannot be read never stops documents: logged, no limit.
        logger.error("plan_limits: could not read the plan of workspace %s "
                     "(%s: %s) — no limit applied", workspace_id, type(e).__name__, e)
        return None


def check_documents(asked: int) -> None:
    from app.workspace_context import current_workspace_id
    ws = current_workspace_id()
    if ws is None:
        return
    limits = _limits_sync(ws)
    if not limits or not limits["max_documents_month"]:
        return
    made = limits.get("documents_this_month", 0)
    if made + asked > limits["max_documents_month"]:
        raise RuntimeError(
            f"waiting: this workspace's plan ({limits['plan']}) allows "
            f"{limits['max_documents_month']} documents a month and {made} are "
            "made — the rest wait for next month or a bigger plan")


async def check_users(session, adding_email: str) -> None:
    """Refuse a NEW active member over the plan's people limit."""
    from sqlalchemy import func, select
    from app.models.platform import Plan, WorkspaceSubscription
    from app.models.workspace_member import WorkspaceMember
    row = (await session.execute(
        select(WorkspaceSubscription.status, Plan.name, Plan.max_users)
        .join(Plan, Plan.key == WorkspaceSubscription.plan_key))).first()
    if row is None or row[0] == "unlimited" or not row[2]:
        return
    already = (await session.execute(select(WorkspaceMember.id).where(
        WorkspaceMember.email == adding_email.strip().lower(),
        WorkspaceMember.active.is_(True)))).first()
    if already is not None:
        return
    active = int((await session.execute(select(func.count()).select_from(
        WorkspaceMember).where(WorkspaceMember.active.is_(True)))).scalar() or 0)
    if active >= row[2]:
        raise LimitError(f"This workspace's plan ({row[1]}) allows {row[2]} "
                         f"people and {active} are active. Remove someone, or "
                         "ask for a bigger plan.")


async def usage(session, workspace_id=None) -> dict:
    """{workspace_id: {...}} for one workspace or all. Counts only — never
    what the documents or records say."""
    from sqlalchemy import text
    params = {"m": _month_start()}
    where = ""
    if workspace_id is not None:
        where = "WHERE w.id = :w"
        params["w"] = workspace_id
    rows = (await session.execute(text(f"""
        SELECT w.id,
          (SELECT count(*) FROM stored_documents d WHERE d.workspace_id = w.id) AS docs,
          (SELECT count(*) FROM stored_documents d WHERE d.workspace_id = w.id
             AND d.created_at >= :m) AS docs_month,
          (SELECT coalesce(sum(d.file_size), 0) FROM stored_documents d WHERE d.workspace_id = w.id)
          + (SELECT coalesce(sum(p.file_size), 0) FROM csp_photos p WHERE p.workspace_id = w.id)
          + (SELECT coalesce(sum(t.file_size), 0) FROM document_templates t WHERE t.workspace_id = w.id)
          + (SELECT coalesce(sum(v.file_size), 0) FROM document_template_versions v WHERE v.workspace_id = w.id)
          + (SELECT coalesce(sum(f.file_size), 0) FROM workspace_files f WHERE f.workspace_id = w.id)
            AS storage_bytes,
          (SELECT count(*) FROM workspace_members m WHERE m.workspace_id = w.id AND m.active) AS people,
          (SELECT count(*) FROM csp_records r WHERE r.workspace_id = w.id) AS records
        FROM workspaces w {where}
    """), params)).all()
    return {str(r[0]): {"documents": int(r[1]), "documents_this_month": int(r[2]),
                        "storage_bytes": int(r[3]), "people": int(r[4]),
                        "records": int(r[5])} for r in rows}
