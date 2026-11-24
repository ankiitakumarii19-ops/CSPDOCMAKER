"""
CSP DocMaker — Setup → Feature access (PROJECT-REGISTER No. 206, Stage 2)

Super Admin only (the feature "feature_access" is locked to them):

  GET    /api/admin/feature-access                         features, roles, the
                                                           role × feature grid,
                                                           people
  PUT    /api/admin/feature-access/roles/{role}/{feature}  {"allowed": true|false|null}
  PUT    /api/admin/feature-access/people/{email}/{feature} {"allowed": …}
  POST   /api/admin/feature-access/roles                   {"name", "copy_from"}
  PATCH  /api/admin/feature-access/roles/{role}            {"name"?, "record_scope"?}
  DELETE /api/admin/feature-access/roles/{role}            a role you made, unused
  PUT    /api/admin/feature-access/members/{email}/role    {"role": key|null}
  GET    /api/admin/feature-access/history

Everyone signed in:

  GET    /api/me/access     what this person may use (the screens follow it)

null = back to today's access. Every change is in the history and the audit
log. What each feature is: services/feature_catalog.py; the rules:
services/feature_access.py.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_user, require_role
from app.services import feature_access
from app.services.feature_access import AccessError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/feature-access",
                   tags=["admin", "feature-access"])
me_router = APIRouter(prefix="/api/me", tags=["me"])

owner = require_role("super_admin")


class AllowedIn(BaseModel):
    allowed: Optional[bool] = None


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    copy_from: str = Field(min_length=1, max_length=60)


class RoleChange(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    record_scope: Optional[str] = None


class MemberRoleIn(BaseModel):
    role: Optional[str] = None


async def _do(session, coro):
    try:
        out = await coro
    except AccessError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return out


@router.get("")
async def overview(session: AsyncSession = Depends(get_session),
                   user=Depends(owner)):
    return await feature_access.describe(session)


@router.get("/history")
async def history(limit: int = Query(100, ge=1, le=500),
                  session: AsyncSession = Depends(get_session),
                  user=Depends(owner)):
    return {"changes": await feature_access.history(session, limit)}


@router.put("/roles/{role}/{feature}")
async def set_for_role(role: str, feature: str, body: AllowedIn,
                       session: AsyncSession = Depends(get_session),
                       user=Depends(owner)):
    await _do(session, feature_access.set_for_role(
        session, role, feature, body.allowed, user))
    return await feature_access.describe(session)


@router.put("/people/{email}/{feature}")
async def set_for_person(email: str, feature: str, body: AllowedIn,
                         session: AsyncSession = Depends(get_session),
                         user=Depends(owner)):
    await _do(session, feature_access.set_for_person(
        session, email, feature, body.allowed, user))
    return await feature_access.describe(session)


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleIn,
                      session: AsyncSession = Depends(get_session),
                      user=Depends(owner)):
    role = await _do(session, feature_access.create_role(
        session, body.name, body.copy_from, user))
    return {"role": role, **(await feature_access.describe(session))}


@router.patch("/roles/{role}")
async def change_role(role: str, body: RoleChange,
                      session: AsyncSession = Depends(get_session),
                      user=Depends(owner)):
    await _do(session, feature_access.change_role(
        session, role, user, name=body.name, record_scope=body.record_scope))
    return await feature_access.describe(session)


@router.delete("/roles/{role}")
async def delete_role(role: str,
                      session: AsyncSession = Depends(get_session),
                      user=Depends(owner)):
    await _do(session, feature_access.delete_role(session, role, user))
    return await feature_access.describe(session)


@router.put("/members/{email}/role")
async def set_member_role(email: str, body: MemberRoleIn,
                          session: AsyncSession = Depends(get_session),
                          user=Depends(owner)):
    await _do(session, feature_access.set_member_role(
        session, email, body.role, user))
    return await feature_access.describe(session)


@me_router.get("/access")
async def my_access(user=Depends(get_current_user)):
    return feature_access.mine(user)
