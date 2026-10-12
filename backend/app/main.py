"""
CSP Document Generation & Email Automation Platform — FastAPI Application

Main application entry point. Configures CORS, routers, error handling,
and lifecycle events.
"""

import logging
import re
from contextlib import asynccontextmanager

from sqlalchemy import select

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.database import init_db, close_db

settings = get_settings()

# Logging, tracing and crash capture (No. 79): structured JSON logs in
# logs/app.jsonl, OpenTelemetry spans in logs/traces.jsonl, IDs on every line.
from app import telemetry
telemetry.setup("cspdocmaker-api", settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — startup and shutdown hooks."""
    logger.info("CSP DocMaker API starting up...")
    await init_db()
    logger.info("Database initialized.")

    # The supplied templates' placeholder maps live in code; the rows that
    # represent them were seeded without one. Reconcile on startup so the
    # admin screen does not show them as unmapped.
    try:
        from app.database import async_session_factory
        from app.models.workspace import Workspace
        from app.services.document_template_service import (
            sync_builtin_dashboards, sync_builtin_data_sources,
            sync_builtin_messages,
            sync_builtin_templates,
        )
        from app.workspace_context import all_workspaces, workspace

        async with async_session_factory() as session:
            with all_workspaces():
                first = (await session.execute(
                    select(Workspace).order_by(Workspace.created_at)
                )).scalars().first()
            if first is not None:
                with workspace(first.id):
                    await sync_builtin_templates(session)
                    await sync_builtin_data_sources(session)
                    await sync_builtin_dashboards(session)
                    await sync_builtin_messages(session)
    except Exception as e:
        # Never stop the API over this: it is a convenience, not a dependency.
        logger.warning("Could not reconcile built-in templates: %s: %s",
                       type(e).__name__, e)
    yield
    logger.info("CSP DocMaker API shutting down...")
    await close_db()


app = FastAPI(
    title="CSP DocMaker API",
    description="CSP Document Generation & Email Automation Platform — Internal EKO API",
    version="1.0.0",
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
    lifespan=lifespan,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    # Local development, plus wherever this is actually served from.
    # PUBLIC_APP_URL is the address CSPs are sent to, so browser calls
    # arrive with that origin — without it here they are blocked, and the
    # failure looks like the app is broken rather than misconfigured.
    allow_origins=[
        o for o in (
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            settings.public_app_url.rstrip("/"),
        ) if o
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Global Error Handler ----
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Unhandled errors: a clear message with an Error ID for the user.

    The full traceback was already logged by the request's operation
    (telemetry), under the same ID. The user gets what failed, an ID to
    quote, and what to do — not internals.
    """
    error_id = getattr(request.state, "request_id", None) or telemetry.new_id()
    operation = f"{request.method} {request.url.path}"
    with telemetry.run(run_id=error_id, request_id=error_id):
        logger.error(
            "Unhandled %s on %s (error_id=%s): %s", type(exc).__name__,
            operation, error_id, exc,
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={**telemetry.where_failed(exc),
                   "event": "unhandled", "status": "FAILED",
                   "error_type": type(exc).__name__,
                   "error_message": telemetry.redact(str(exc))},
        )
    return JSONResponse(
        status_code=500,
        headers={"X-Request-ID": error_id},
        content={
            "detail": (f"Failed while handling {operation} "
                       f"(Error ID {error_id}). Please try again; if it "
                       f"keeps failing, send this Error ID to support."),
            "error_id": error_id,
            "operation": operation,
            "next_action": "Retry once; if it fails again, report the Error ID.",
        },
    )


# ---- Health Check ----
@app.get("/api/health", tags=["System"])
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "CSP DocMaker API",
        "version": "1.0.0",
    }



# ---- Which workspace is this request for? ----
#
# Every scoped query is filtered to the workspace in force, and every row
# written takes it. Nothing sets it by itself, so it is set here, once, from
# whoever is signed in.
#
# A request with no resolvable workspace stays unscoped and therefore cannot
# write — which is the right failure. Filing a row under a guessed customer
# is worse than refusing it. The public CSP form is exempt: it has no signed
# in user and sets its own workspace from the token in the link.

_UNSCOPED_PATHS = ("/api/csp-form", "/api/auth", "/api/public", "/health",
                   "/docs", "/openapi")


@app.middleware("http")
async def _set_workspace(request, call_next):
    from app.database import async_session_factory
    from app.services import jwt_service
    from app.workspace_context import workspace

    path = request.url.path
    if any(path.startswith(prefix) for prefix in _UNSCOPED_PATHS):
        return await call_next(request)

    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return await call_next(request)

    try:
        claims = jwt_service.decode_token(header.split(" ", 1)[1].strip())
        email = (claims or {}).get("sub") or (claims or {}).get("email")
    except Exception as e:
        # An invalid token is the router's business to reject (it answers
        # 401), not ours — but it is noted, never silent.
        logger.info("request token could not be read (%s: %s); the endpoint "
                    "will reject it", type(e).__name__, e)
        return await call_next(request)

    if not email:
        return await call_next(request)

    # The token names the workspace chosen at sign-in, and the role held
    # there. Both are re-checked against the database on EVERY request, so
    # removing someone, or changing their role, takes effect at once rather
    # than when their token expires.
    #
    # A signed-in request that cannot be placed in a workspace is REFUSED.
    # Letting it through would run it unfiltered — across every workspace.
    from fastapi.responses import JSONResponse
    from app.services import workspace_service

    def refuse(code: int, message: str):
        return JSONResponse(status_code=code, content={"detail": message})

    try:
        async with async_session_factory() as session:
            chosen = claims.get("ws")
            if chosen:
                member = await workspace_service.membership(
                    session, email, chosen)
            else:
                # A token from before workspaces were chosen at sign-in.
                # Accepted only when there is exactly one place it can mean.
                found = await workspace_service.memberships(session, email)
                member = found[0][0] if len(found) == 1 else None
    except Exception as e:
        logger.error("Could not check workspace membership for %s: %s: %s",
                     email, type(e).__name__, e)
        return refuse(503, "Please try again in a moment.")

    if member is None:
        return refuse(403, "You no longer have access to this workspace. "
                           "Please log in again.")
    if member.role.value != claims.get("role"):
        return refuse(401, "Your role has changed. Please log in again.")

    with workspace(member.workspace_id):
        return await call_next(request)



_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@app.middleware("http")
async def _trace_request(request, call_next):
    """Every request: an ID, a span, START/SUCCESS/FAILED, and the ID back
    in the X-Request-ID header so a user can quote it (No. 79).

    Added after the workspace middleware, so it is the outermost one and
    wraps everything else."""
    given = request.headers.get("x-request-id", "")
    request_id = given if _SAFE_ID.match(given) else telemetry.new_id()
    request.state.request_id = request_id
    with telemetry.run(run_id=request_id, request_id=request_id):
        with telemetry.operation(
                f"HTTP {request.method} {request.url.path}", "api.request",
                method=request.method, path=request.url.path) as span:
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            if response.status_code >= 500:
                logger.error("%s %s answered %s (request_id=%s)",
                             request.method, request.url.path,
                             response.status_code, request_id)
    response.headers["X-Request-ID"] = request_id
    return response

# ---- API Routers ----
from app.routers.auth_router import router as auth_router
from app.routers.csp_router import router as csp_router
from app.routers.document_router import router as document_router
from app.routers.alert_router import router as alert_router
from app.routers.template_router import router as template_router
from app.routers.access_router import router as access_router
from app.routers.csp_form_router import router as csp_form_router
from app.routers.dashboard_router import router as dashboard_router
from app.routers.agent_router import router as agent_router
from app.routers.messaging_router import router as messaging_router
from app.routers.sheet_router import router as sheet_router
from app.routers.database_router import router as database_router
from app.routers.workflow_router import router as workflow_router
from app.routers.admin_router import router as admin_router

app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(csp_router, prefix="/api/csps", tags=["CSP"])
app.include_router(document_router)  # already has /api/documents prefix
app.include_router(workflow_router)  # already has /api/workflows prefix
app.include_router(admin_router)     # already has /api/admin prefix
app.include_router(alert_router)     # already has /api/alerts prefix
app.include_router(template_router)  # already has /api/admin/templates prefix
app.include_router(access_router)    # already has /api/admin/access prefix
app.include_router(dashboard_router) # already has /api/admin/dashboards prefix
app.include_router(agent_router)     # already has /api/admin/agents prefix
app.include_router(messaging_router) # already has /api/admin/messaging prefix
app.include_router(sheet_router)     # already has /api/admin/sheets prefix
app.include_router(database_router)  # /api/admin/database — Super Admin, read-only
app.include_router(csp_form_router)  # PUBLIC — no login; token is the credential
from app.routers.public_document_router import router as public_document_router
app.include_router(public_document_router)  # PUBLIC — signed 7-day link (No. 78)

