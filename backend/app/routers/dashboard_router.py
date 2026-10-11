"""
CSP DocMaker — building and reading dashboards

Admins and Workspace Owners both build and read dashboards. A dashboard
reports on work; shaping that report is part of doing the work.

Two refusals are deliberate:

  * The system dashboard cannot be deleted or hidden. Document Operations
    reports on the thing this product exists to do, and a workspace with no
    screen for that is a workspace nobody can run.
  * A widget naming a metric nothing computes is refused when it is SAVED.
    A dashboard that builds fine and then fails to render is worse than one
    that refuses to be built.

Retiring a dashboard sets active=false. It never deletes the data behind
it, so switching it back on brings the whole record with it.
"""

import logging
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.dashboard import WIDGET_KINDS, Dashboard, DashboardWidget
from app.services import metric_compute, metric_drilldown, metric_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/dashboards", tags=["admin", "dashboards"])


def _who(user: dict) -> str:
    """Who is doing this, for the log and the audit trail.

    A token always carries `sub`; it does not always carry `email`, and
    logging "None" for who deleted something is worse than useless.
    """
    return (user or {}).get("email") or (user or {}).get("sub") or "unknown"



# ---- what the builder sends ---------------------------------------------

class WidgetIn(BaseModel):
    kind: str
    metric: str
    title: str
    config: Dict = Field(default_factory=dict)
    width: int = 1


class DashboardIn(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    icon: str = "fa-chart-simple"
    widgets: List[WidgetIn] = Field(default_factory=list)


class DashboardPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    active: Optional[bool] = None
    position: Optional[int] = None
    widgets: Optional[List[WidgetIn]] = None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "dashboard"


def _check_widgets(widgets: List[WidgetIn]) -> None:
    """Refuse anything that could not render, before it is stored."""
    for widget in widgets:
        if widget.kind not in WIDGET_KINDS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{widget.kind!r} is not a kind of widget. "
                f"Choose from: {', '.join(WIDGET_KINDS)}.",
            )
        if not metric_registry.exists(widget.metric):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Nothing here measures {widget.metric!r}. A dashboard can "
                f"only show metrics this system knows how to compute.",
            )
        metric = metric_registry.get(widget.metric)
        if metric.widgets and widget.kind not in metric.widgets:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{metric.label!r} cannot be shown as a {widget.kind}. "
                f"It fits: {', '.join(metric.widgets)}.",
            )
        if not metric_compute.is_computable(widget.metric):
            # Registered but unimplemented: a bug, not the admin's mistake.
            raise HTTPException(
                status.HTTP_501_NOT_IMPLEMENTED,
                f"{metric.label!r} is listed but not yet implemented.",
            )


def _summary(dashboard: Dashboard) -> dict:
    return {
        "id": str(dashboard.id),
        "slug": dashboard.slug,
        "name": dashboard.name,
        "description": dashboard.description,
        "icon": dashboard.icon,
        "is_system": dashboard.is_system,
        "active": dashboard.active,
        "position": dashboard.position,
        "widget_count": len(dashboard.widgets),
        # Said explicitly so a UI never has to infer it.
        "can_remove": not dashboard.is_system,
        "can_hide": not dashboard.is_system,
    }


def _widget_out(widget: DashboardWidget) -> dict:
    metric = (metric_registry.get(widget.metric)
              if metric_registry.exists(widget.metric) else None)
    return {
        "id": str(widget.id),
        "kind": widget.kind,
        "metric": widget.metric,
        "title": widget.title,
        "config": widget.config or {},
        "width": widget.width,
        "position": widget.position,
        "shape": metric.shape if metric else None,
        # Whether a drill-down actually exists, not merely whether the
        # metric claims to be drillable. A card that invites a click and
        # then 404s is worse than one that does not invite it.
        "drillable": metric_drilldown.is_drillable(widget.metric),
    }


async def _get(session: AsyncSession, slug: str) -> Dashboard:
    dashboard = (await session.execute(
        select(Dashboard).where(Dashboard.slug == slug)
    )).scalars().first()
    if dashboard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No dashboard called {slug!r}.")
    return dashboard


def _replace_widgets(dashboard: Dashboard, widgets: List[WidgetIn]) -> None:
    dashboard.widgets.clear()
    for position, widget in enumerate(widgets):
        dashboard.widgets.append(DashboardWidget(
            kind=widget.kind, metric=widget.metric, title=widget.title,
            config=widget.config or {}, width=max(1, min(4, widget.width)),
            position=position,
        ))


# ---- endpoints -----------------------------------------------------------

@router.get("")
async def list_dashboards(
    include_hidden: bool = False,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Every dashboard in this workspace, in display order."""
    dashboards = (await session.execute(
        select(Dashboard).order_by(Dashboard.position, Dashboard.name)
    )).scalars().all()
    # An Admin never sees a retired dashboard; a Super Admin can, to bring
    # one back.
    is_owner = user.get("role") == "super_admin"
    if not (include_hidden and is_owner):
        dashboards = [d for d in dashboards if d.active]
    return {"dashboards": [_summary(d) for d in dashboards]}


@router.get("/metrics")
async def available_metrics(user=Depends(require_role("admin", "super_admin"))):
    """The builder's palette: what a widget may be made to show."""
    return {"groups": metric_registry.groups(), "widget_kinds": list(WIDGET_KINDS)}


@router.get("/metrics/{metric_key}/records")
async def metric_records(
    metric_key: str,
    field: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """The records behind one number on a dashboard.

    `field` names the clicked row for a metric that is a table rather than
    a single number — which document, for "Documents CSPs already hold".

    Declared before /{slug} only for readability — the paths differ in
    length, so the router would not confuse them either way.
    """
    try:
        return await metric_drilldown.records_for(metric_key, session, field)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/{slug}")
async def read_dashboard(
    slug: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """A dashboard with its widgets filled in."""
    dashboard = await _get(session, slug)
    if not dashboard.active and user.get("role") != "super_admin":
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No dashboard called {slug!r}.")

    widgets = []
    for widget in dashboard.widgets:
        payload = _widget_out(widget)
        try:
            payload["data"] = await metric_compute.compute(widget.metric,
                                                           session)
        except KeyError as e:
            # One broken widget must not blank the whole screen.
            payload["error"] = str(e)
            logger.error("dashboard_router: %s could not be computed: %s",
                         widget.metric, e)
        widgets.append(payload)

    return {**_summary(dashboard), "widgets": widgets}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    body: DashboardIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Build a new dashboard."""
    _check_widgets(body.widgets)

    slug = _slugify(body.name)
    existing = (await session.execute(
        select(Dashboard).where(Dashboard.slug == slug)
    )).scalars().first()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A dashboard called {body.name!r} already exists here.")

    highest = (await session.execute(
        select(Dashboard.position).order_by(Dashboard.position.desc()).limit(1)
    )).scalar() or 0

    dashboard = Dashboard(
        slug=slug, name=body.name.strip(), description=body.description,
        icon=body.icon or "fa-chart-simple", is_system=False, active=True,
        position=highest + 1,
    )
    _replace_widgets(dashboard, body.widgets)
    session.add(dashboard)
    await session.commit()

    logger.info("dashboard_router.create_dashboard: %s built by %s (%d widgets)",
                slug, _who(user), len(body.widgets))
    return _summary(dashboard)


@router.patch("/{slug}")
async def update_dashboard(
    slug: str,
    body: DashboardPatch,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Rename it, rearrange its widgets, hide it, or bring it back."""
    dashboard = await _get(session, slug)

    if body.active is False and dashboard.is_system:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{dashboard.name} cannot be hidden. It reports on document "
            f"issuing, which is what this system is for.",
        )

    if body.name is not None:
        dashboard.name = body.name.strip() or dashboard.name
    if body.description is not None:
        dashboard.description = body.description or None
    if body.icon is not None:
        dashboard.icon = body.icon or dashboard.icon
    if body.position is not None:
        dashboard.position = body.position
    if body.active is not None:
        dashboard.active = body.active
    if body.widgets is not None:
        _check_widgets(body.widgets)
        _replace_widgets(dashboard, body.widgets)

    await session.commit()
    logger.info("dashboard_router.update_dashboard: %s changed by %s",
                slug, _who(user))
    return _summary(dashboard)


@router.delete("/{slug}")
async def delete_dashboard(
    slug: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Remove a dashboard. The data it showed is untouched."""
    dashboard = await _get(session, slug)
    if dashboard.is_system:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{dashboard.name} cannot be removed. Every workspace needs a "
            f"screen for the documents it issues.",
        )

    name = dashboard.name
    await session.delete(dashboard)
    await session.commit()
    logger.info("dashboard_router.delete_dashboard: %s removed by %s",
                slug, _who(user))
    return {
        "deleted": slug,
        "message": f"{name} removed. Nothing it showed was deleted — the "
                   f"records, submissions and history are all still here.",
    }
