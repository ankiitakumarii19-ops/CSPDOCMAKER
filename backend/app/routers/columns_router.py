"""
CSP DocMaker — Setup → Columns (PROJECT-REGISTER No. 211, Stage 4, ZU-04)

Super Admin only (feature "columns", locked: a wrong column would write a
CSP's details into the wrong cells).

  GET  /api/admin/columns          every field with the heading in force
  POST /api/admin/columns/guess    the app's guess from the sheet's headings
  PUT  /api/admin/columns          {"columns": {field: heading}} — save

The rules of the guess: services/data_shape.py.
"""

import asyncio
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import off_loop  # slow calls beside the server (No. 251)
from app.database import get_session
from app.dependencies import require_role
from app.services import data_shape

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/columns", tags=["admin", "columns"])
owner = require_role("super_admin")


class ColumnsIn(BaseModel):
    columns: Dict[str, Optional[str]]


@router.get("")
async def overview(session: AsyncSession = Depends(get_session),
                   user=Depends(owner)):
    return await data_shape.describe(session)


@router.post("/guess")
async def guess(user=Depends(owner)):
    from app.workspace_context import current_workspace_id, workspace
    wid = current_workspace_id()

    def read():
        with workspace(wid):
            return data_shape.main_headers()
    try:
        headers = await off_loop.google(read)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Could not read the sheet's headings: "
                            f"{type(e).__name__}: {str(e)[:200]}")
    found = data_shape.guess(headers)
    return {"headers": headers, "guess": found,
            "not_found": [f["field"] for f in data_shape.fields()
                          if f["field"] not in found]}


@router.put("")
async def save(body: ColumnsIn, session: AsyncSession = Depends(get_session),
               user=Depends(owner)):
    try:
        return await data_shape.save(session, body.columns, user)
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
