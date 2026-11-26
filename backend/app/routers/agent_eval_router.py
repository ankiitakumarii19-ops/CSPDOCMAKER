"""
CSP DocMaker — Agent health API (No. 252)

GET  /api/admin/agents/evaluation                 the screen: scores, numbers,
                                                  open issues, improvements
GET  /api/admin/agents/evaluation/history         daily rows (?days=, ?agent=)
GET  /api/admin/agents/evaluation/issues          ?status=open|resolved|all
POST /api/admin/agents/evaluation/check           check now (as the timer does)
POST /api/admin/agents/evaluation/improvements/{id}/apply | dismiss | undo

The Super Admin's, like the Agents screen (feature "agents", which may be
handed to Admins in Feature access). Everything is worked out in
services/agent_eval.py.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.services import agent_eval

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/agents/evaluation",
                   tags=["Agent health"])
owner = require_role("super_admin")


def _who(user: dict) -> str:
    return (user.get("sub") or user.get("email") or "").lower()


@router.get("", summary="Every agent's score, numbers, issues and lessons")
async def overview(session: AsyncSession = Depends(get_session),
                   user=Depends(owner)):
    return await session.run_sync(lambda s: agent_eval.overview(s))


@router.get("/history", summary="One row per agent per day")
async def history(days: int = Query(30, ge=1, le=365),
                  agent: Optional[str] = Query(None, max_length=60),
                  session: AsyncSession = Depends(get_session),
                  user=Depends(owner)):
    rows = await session.run_sync(
        lambda s: agent_eval.history(s, days=days, agent=agent))
    return {"days": days, "rows": rows}


@router.get("/issues", summary="Open, resolved or all issues")
async def issues(status_: str = Query("open", alias="status",
                                      pattern="^(open|resolved|all)$"),
                 session: AsyncSession = Depends(get_session),
                 user=Depends(owner)):
    rows = await session.run_sync(lambda s: agent_eval.issues(s, status_))
    return {"issues": rows}


@router.post("/check", summary="Check every agent now")
async def check_now(session: AsyncSession = Depends(get_session),
                    user=Depends(owner)):
    try:
        result = await session.run_sync(lambda s: agent_eval.evaluate(s))
    except Exception as e:
        await session.rollback()
        logger.error("agent_eval_router: the check by %s failed: %s: %s",
                     _who(user), type(e).__name__, e, exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"The check could not finish: {type(e).__name__}. "
                            "It is in the server log.")
    logger.info("agent_eval_router: checked now by %s: %s", _who(user), result)
    return result


async def _decide(session: AsyncSession, improvement_id: str, user: dict,
                  action) -> dict:
    from app.models.agent_eval import AgentImprovement
    try:
        key = uuid.UUID(improvement_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such improvement.")

    def work(s):
        imp = s.get(AgentImprovement, key)
        if imp is None:
            raise LookupError
        action(s, imp, _who(user))
        s.commit()
        return agent_eval._improvement_row(imp)

    try:
        return await session.run_sync(work)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such improvement.")
    except agent_eval.ImprovementError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.post("/improvements/{improvement_id}/apply")
async def apply_improvement(improvement_id: str,
                            session: AsyncSession = Depends(get_session),
                            user=Depends(owner)):
    return await _decide(session, improvement_id, user, agent_eval.apply)


@router.post("/improvements/{improvement_id}/dismiss")
async def dismiss_improvement(improvement_id: str,
                              session: AsyncSession = Depends(get_session),
                              user=Depends(owner)):
    return await _decide(session, improvement_id, user, agent_eval.dismiss)


@router.post("/improvements/{improvement_id}/undo")
async def undo_improvement(improvement_id: str,
                           session: AsyncSession = Depends(get_session),
                           user=Depends(owner)):
    return await _decide(session, improvement_id, user, agent_eval.undo)
