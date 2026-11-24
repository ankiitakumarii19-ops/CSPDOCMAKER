"""
CSP DocMaker — Setup → Connections (PROJECT-REGISTER No. 210, Stage 3)

Super Admin only (the feature "connections" is locked to them):

  GET    /api/admin/connections               the workspace's sheets, email,
                                              WhatsApp and CRM (secrets only
                                              as set / not set)
  PUT    /api/admin/connections/{key}         {"value": ...}
  DELETE /api/admin/connections/{key}         remove this workspace's own value
  POST   /api/admin/connections/test/{group}  sheets | email | whatsapp | crm

What each one is and the rule that keeps Eko's connections Eko's:
services/connection_catalog.py.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.services import connections
from app.services.connection_catalog import ConnectionError_

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/connections",
                   tags=["admin", "connections"])
owner = require_role("super_admin")


class ValueIn(BaseModel):
    value: Any = None


@router.get("")
async def overview(session: AsyncSession = Depends(get_session),
                   user=Depends(owner)):
    return await connections.describe(session)


@router.post("/test/{group}")
async def test(group: str, user=Depends(owner)):
    try:
        return await connections.run_test(group, user)
    except ConnectionError_ as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.put("/{key}")
async def set_value(key: str, body: ValueIn,
                    session: AsyncSession = Depends(get_session),
                    user=Depends(owner)):
    try:
        await connections.set_value(session, key, body.value, user)
    except ConnectionError_ as e:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return await connections.describe(session)


@router.delete("/{key}")
async def clear(key: str, session: AsyncSession = Depends(get_session),
                user=Depends(owner)):
    try:
        await connections.clear(session, key, user)
    except ConnectionError_ as e:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return await connections.describe(session)
