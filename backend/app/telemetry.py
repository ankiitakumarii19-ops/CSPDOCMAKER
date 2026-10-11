"""
CSP DocMaker — telemetry: nothing fails silently

Requested 12 Oct 2026 (PROJECT-REGISTER No. 79, AI_SPEC.md §4). One module,
used by the API and the Celery workers alike.

What it gives every piece of work:

  * IDs. A run_id (one HTTP request, or one background task), a request_id
    (the HTTP request; the same as run_id there) and an operation_id (each
    step). They are attached to every log line automatically.
  * Spans. OpenTelemetry traces, one span per operation and per external
    call, written as JSON lines to logs/traces.jsonl (no server needed;
    an OTLP exporter can be added later without touching call sites).
  * Structured logs. JSON lines in logs/app.jsonl (rotating) and readable
    lines on the console, both carrying the IDs.
  * operation(): START -> SUCCESS / FAILED, with duration, context and, on
    failure, the error type, message and full traceback. The exception is
    always re-raised — this records, it never swallows.
  * external_call(): the same for a call to another service, plus WHAT KIND
    of failure it was (timeout, connection, auth, rate_limit, server,
    client, malformed, empty, schema) and the attempt number.
  * Crash capture: uncaught exceptions in any thread are logged as CRASH
    DETECTED with the last successful and the currently running operation;
    hard crashes (segfaults) are written by faulthandler to logs/crash.log.
  * Redaction. Emails, phone numbers, bearer tokens, JWTs, API keys and
    password/token/secret values are masked in every log line and span
    attribute before anything is written.

There is no LLM in this system (AI_SPEC.md D1); llm_* attributes are
reserved for if one is ever added.
"""

import contextvars
import faulthandler
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor, SpanExporter, SpanExportResult,
)
from opentelemetry.trace import Status, StatusCode

LOG_DIR = os.environ.get(
    "LOG_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "logs"))

run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
operation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("operation_id", default="")
operation_name_var: contextvars.ContextVar[str] = contextvars.ContextVar("operation_name", default="")

# For crash reports: what last worked, per process.
_last_success = {"operation": "", "at": ""}

_tracer = trace.get_tracer("cspdocmaker")
_configured = False
_lock = threading.Lock()


def new_id() -> str:
    return uuid.uuid4().hex[:16]


_APP_DIR = os.path.dirname(os.path.abspath(__file__))


def where_failed(exc: BaseException) -> Dict[str, str]:
    """The innermost function of OUR code that the error passed through,
    and the very place it was raised (which may be inside a library)."""
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    if not frames:
        return {}
    raised = frames[-1]
    ours = next((f for f in reversed(frames)
                 if os.path.abspath(f.filename).startswith(_APP_DIR)
                 and not f.filename.endswith("telemetry.py")), None)
    out = {"raised_in": f"{raised.name} ({os.path.basename(raised.filename)}:{raised.lineno})"}
    if ours:
        out["failed_function"] = ours.name
        out["failed_at"] = f"{os.path.relpath(ours.filename, os.path.dirname(_APP_DIR))}:{ours.lineno}"
    return out


# ---- redaction ---------------------------------------------------------------

_REDACTIONS = [
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]+"), r"\1 [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[JWT]"),
    (re.compile(r"\bwabs_[A-Za-z0-9]+"), "[KEY]"),
    (re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key|otp|"
                r"refresh_token|access_token|client_secret)(\"?\s*[:=]\s*\"?)"
                r"[^\s\",;&]+"), r"\1\2[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?<![\w])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\w])"), "[PHONE]"),
]


def redact(value: Any) -> Any:
    """Mask secrets and personal contact details in a string (or str())."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = value if isinstance(value, str) else str(value)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# ---- spans to a JSON-lines file ---------------------------------------------

class JsonlSpanExporter(SpanExporter):
    """Writes each finished span as one JSON line. Never raises."""

    def __init__(self, path: str):
        self.path = path

    def export(self, spans) -> SpanExportResult:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                for span in spans:
                    f.write(json.dumps(_span_dict(span), ensure_ascii=False) + "\n")
            return SpanExportResult.SUCCESS
        except Exception as e:  # the app must not die because a log file did
            sys.stderr.write(f"telemetry: could not write span: {e}\n")
            return SpanExportResult.FAILURE

    def shutdown(self):
        return None


def _span_dict(span: ReadableSpan) -> dict:
    ctx = span.get_span_context()
    parent = span.parent
    return {
        "type": "span",
        "name": span.name,
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_span_id": format(parent.span_id, "016x") if parent else None,
        "start": _iso(span.start_time),
        "end": _iso(span.end_time),
        "duration_ms": round(((span.end_time or 0) - (span.start_time or 0)) / 1e6, 2),
        "status": span.status.status_code.name,
        "status_message": redact(span.status.description) if span.status.description else None,
        "attributes": {k: redact(v) for k, v in (span.attributes or {}).items()},
        "events": [{"name": e.name, "time": _iso(e.timestamp),
                    "attributes": {k: redact(v) for k, v in (e.attributes or {}).items()}}
                   for e in span.events],
        "service": span.resource.attributes.get("service.name"),
    }


def _iso(ns: Optional[int]) -> Optional[str]:
    if not ns:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()


# ---- logs ----------------------------------------------------------------------

class _ContextFilter(logging.Filter):
    """Attach IDs and redact the message on every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get() or "-"
        record.request_id = request_id_var.get() or "-"
        record.operation_id = operation_id_var.get() or "-"
        record.operation = operation_name_var.get() or "-"
        span = trace.get_current_span().get_span_context()
        record.trace_id = format(span.trace_id, "032x") if span.is_valid else "-"
        try:
            message = record.getMessage()
        except Exception as e:
            # A badly formatted log call must not lose the line — or hide
            # that it was badly formatted.
            message = f"{record.msg} [log formatting failed: {type(e).__name__}: {e}; args={record.args!r}]"
        record.msg, record.args = redact(message), None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "severity": record.levelname,
            "run_id": getattr(record, "run_id", "-"),
            "request_id": getattr(record, "request_id", "-"),
            "operation_id": getattr(record, "operation_id", "-"),
            "operation": getattr(record, "operation", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
            "component": record.name,
            "function": record.funcName,
            "file": f"{record.filename}:{record.lineno}",
            "message": record.getMessage(),
        }
        for key in ("failed_function", "failed_at", "raised_in",
                    "event", "status", "duration_ms", "service", "error_type",
                    "error_message", "failure_kind", "attempt", "max_attempts",
                    "retryable", "recovered", "context"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["traceback"] = redact("".join(traceback.format_exception(*record.exc_info)))
        return json.dumps(out, ensure_ascii=False, default=str)


CONSOLE_FORMAT = ("%(asctime)s %(levelname)-8s [%(name)s] run=%(run_id)s "
                  "op=%(operation)s | %(message)s")


def setup(service: str, level: str = "INFO") -> None:
    """Configure logging, tracing and crash capture once per process."""
    global _configured
    with _lock:
        if _configured:
            return
        os.makedirs(LOG_DIR, exist_ok=True)

        root = logging.getLogger()
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        for handler in list(root.handlers):
            root.removeHandler(handler)
        context = _ContextFilter()

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT, "%Y-%m-%d %H:%M:%S"))
        console.addFilter(context)
        root.addHandler(console)

        jsonl = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "app.jsonl"), maxBytes=20_000_000,
            backupCount=10, encoding="utf-8")
        jsonl.setFormatter(JsonFormatter())
        jsonl.addFilter(context)
        root.addHandler(jsonl)

        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        provider.add_span_processor(SimpleSpanProcessor(
            JsonlSpanExporter(os.path.join(LOG_DIR, "traces.jsonl"))))
        trace.set_tracer_provider(provider)

        _install_crash_capture()
        try:
            instrument_google_api()
        except ImportError as e:
            logging.getLogger(__name__).warning(
                "Google API client not installed; Sheets calls not traced: %s", e)
        _configured = True
        logging.getLogger(__name__).info(
            "telemetry ready: service=%s, logs in %s", service, LOG_DIR)


# ---- operations -----------------------------------------------------------------

def _context_text(context: Optional[dict]) -> Optional[str]:
    if not context:
        return None
    return redact(", ".join(f"{k}={v}" for k, v in context.items()))


@contextmanager
def operation(name: str, component: str = "", **context):
    """One traceable step: START -> SUCCESS/FAILED, duration, traceback.

    Re-raises whatever went wrong. `context` holds SAFE identifying details
    only (IDs, counts, file names) — it is redacted, but keep it small.
    """
    log = logging.getLogger(component or __name__)
    op_id = new_id()
    tokens = (operation_id_var.set(op_id), operation_name_var.set(name))
    started = time.perf_counter()
    attributes = {"operation": name, "operation_id": op_id,
                  "component": component or "-"}
    attributes.update({f"ctx.{k}": redact(v) for k, v in context.items()})
    with _tracer.start_as_current_span(name, attributes=attributes) as span:
        log.info("[STEP] %s START%s", name,
                 f" ({_context_text(context)})" if context else "",
                 extra={"event": "start", "context": _context_text(context)})
        try:
            yield span
        except BaseException as e:
            duration = round((time.perf_counter() - started) * 1000, 1)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, f"{type(e).__name__}: {e}"))
            log.error("[STEP] %s FAILED after %sms: %s: %s", name, duration,
                      type(e).__name__, e, exc_info=True,
                      extra={**where_failed(e),
                             "event": "failed", "status": "FAILED",
                             "duration_ms": duration,
                             "error_type": type(e).__name__,
                             "error_message": redact(str(e)),
                             "failure_kind": getattr(e, "failure_kind", None),
                             "context": _context_text(context)})
            raise
        else:
            duration = round((time.perf_counter() - started) * 1000, 1)
            span.set_status(Status(StatusCode.OK))
            _last_success.update(operation=name,
                                 at=datetime.now(timezone.utc).isoformat())
            log.info("[STEP] %s SUCCESS in %sms", name, duration,
                     extra={"event": "success", "status": "SUCCESS",
                            "duration_ms": duration})
        finally:
            operation_id_var.reset(tokens[0])
            operation_name_var.reset(tokens[1])


def traced(name: Optional[str] = None, component: Optional[str] = None):
    """Decorator form of operation()."""
    def wrap(fn):
        op_name = name or fn.__name__
        comp = component or fn.__module__

        @wraps(fn)
        def inner(*args, **kwargs):
            with operation(op_name, comp):
                return fn(*args, **kwargs)
        return inner
    return wrap


# ---- external services -------------------------------------------------------------

TIMEOUT = "timeout"
CONNECTION = "connection"
AUTH = "auth"
RATE_LIMIT = "rate_limit"
SERVER = "server"
CLIENT = "client"
MALFORMED = "malformed"
EMPTY = "empty"
SCHEMA = "schema"
UNKNOWN = "unknown"
RETRYABLE = frozenset({TIMEOUT, CONNECTION, RATE_LIMIT, SERVER})


def http_failure_kind(status: Optional[int]) -> Optional[str]:
    """What an HTTP status says went wrong, or None for success."""
    if status is None or 200 <= status < 300:
        return None
    if status in (401, 403):
        return AUTH
    if status == 429:
        return RATE_LIMIT
    if status in (408, 504):
        return TIMEOUT
    if status >= 500:
        return SERVER
    return CLIENT


def classify(exc: BaseException) -> str:
    """Which kind of failure an exception from a client library is."""
    if getattr(exc, "failure_kind", None):
        return exc.failure_kind
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    status = (getattr(getattr(exc, "resp", None), "status", None)
              or getattr(getattr(exc, "response", None), "status_code", None)
              or getattr(exc, "status_code", None))
    if isinstance(status, int):
        kind = http_failure_kind(status)
        if kind:
            return kind
    if "timeout" in name or "timed out" in text or isinstance(exc, TimeoutError):
        return TIMEOUT
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)) or "decode" in name:
        return MALFORMED
    if ("connect" in name or "connection" in text or "unreachable" in text
            or "servernotfound" in name or "name resolution" in text
            or isinstance(exc, ConnectionError)):
        return CONNECTION
    if "auth" in name or "permission" in text or "unauthor" in text or "forbidden" in text:
        return AUTH
    if "rate" in text and "limit" in text:
        return RATE_LIMIT
    if "smtpauthentication" in name:
        return AUTH
    return UNKNOWN


@contextmanager
def external_call(service: str, operation_name: str, attempt: int = 1,
                  max_attempts: int = 1, **context):
    """Trace one call to another service; classify and re-raise failures.

    Use the attempt numbers when the caller retries, so the log reads
    "attempt 1 of 3 FAILED (timeout) ... attempt 2 of 3 SUCCESS".
    """
    log = logging.getLogger(f"external.{service}")
    started = time.perf_counter()
    attributes = {"service": service, "operation": operation_name,
                  "attempt": attempt, "max_attempts": max_attempts}
    attributes.update({f"ctx.{k}": redact(v) for k, v in context.items()})
    with _tracer.start_as_current_span(f"{service}.{operation_name}",
                                       attributes=attributes) as span:
        try:
            yield span
        except BaseException as e:
            kind = classify(e)
            try:
                e.failure_kind = kind
            except (AttributeError, TypeError) as refused:
                # A few exception types refuse new attributes. The kind is
                # still in the log line and the span below; say so.
                log.debug("could not tag %s with failure_kind: %s",
                          type(e).__name__, refused)
            duration = round((time.perf_counter() - started) * 1000, 1)
            retry_next = kind in RETRYABLE and attempt < max_attempts
            span.record_exception(e)
            span.set_attribute("failure_kind", kind)
            span.set_status(Status(StatusCode.ERROR, f"{kind}: {type(e).__name__}"))
            log.log(logging.WARNING if retry_next else logging.ERROR,
                    "[CALL] %s.%s attempt %d of %d FAILED (%s) after %sms: "
                    "%s: %s%s", service, operation_name, attempt, max_attempts,
                    kind, duration, type(e).__name__, e,
                    " — will retry" if retry_next else "",
                    exc_info=not retry_next,
                    extra={**where_failed(e),
                           "event": "call_failed", "status": "FAILED",
                           "service": service, "failure_kind": kind,
                           "attempt": attempt, "max_attempts": max_attempts,
                           "retryable": kind in RETRYABLE,
                           "duration_ms": duration,
                           "error_type": type(e).__name__,
                           "error_message": redact(str(e)),
                           "context": _context_text(context)})
            raise
        else:
            duration = round((time.perf_counter() - started) * 1000, 1)
            span.set_status(Status(StatusCode.OK))
            log.info("[CALL] %s.%s attempt %d of %d SUCCESS in %sms",
                     service, operation_name, attempt, max_attempts, duration,
                     extra={"event": "call_ok", "status": "SUCCESS",
                            "service": service, "attempt": attempt,
                            "max_attempts": max_attempts,
                            "duration_ms": duration})


class ExternalResponseError(RuntimeError):
    """A reply that arrived but cannot be used (empty, malformed, wrong shape)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.failure_kind = kind


# ---- runs (HTTP requests and background tasks) ----------------------------------------

@contextmanager
def run(run_id: Optional[str] = None, request_id: Optional[str] = None,
        name: str = "run"):
    """Bind IDs for the duration of one request or task."""
    rid = run_id or new_id()
    tokens = (run_id_var.set(rid), request_id_var.set(request_id or ""))
    try:
        yield rid
    finally:
        run_id_var.reset(tokens[0])
        request_id_var.reset(tokens[1])


# ---- crashes --------------------------------------------------------------------------

def crash_report(exc_type, exc, tb, where: str = "process") -> None:
    logging.getLogger("crash").critical(
        "CRASH DETECTED in %s | run=%s | last successful operation: %s (%s) | "
        "operation running: %s | %s: %s", where, run_id_var.get() or "-",
        _last_success["operation"] or "none yet", _last_success["at"] or "-",
        operation_name_var.get() or "none", exc_type.__name__, exc,
        exc_info=(exc_type, exc, tb),
        extra={"event": "crash", "status": "CRASHED",
               "error_type": exc_type.__name__,
               "error_message": redact(str(exc))})


def _install_crash_capture() -> None:
    previous = sys.excepthook

    def on_uncaught(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            crash_report(exc_type, exc, tb, "main thread")
        previous(exc_type, exc, tb)

    sys.excepthook = on_uncaught

    def on_thread(args):
        if args.exc_type is not SystemExit:
            crash_report(args.exc_type, args.exc_value, args.exc_traceback,
                         f"thread {getattr(args.thread, 'name', '?')}")

    threading.excepthook = on_thread

    # Crashes Python cannot catch (a segfault in a C library — this app has
    # had one) are written here by the interpreter itself.
    crash_file = open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8")
    faulthandler.enable(file=crash_file, all_threads=True)


def last_success() -> Dict[str, str]:
    return dict(_last_success)


def note_http(span, service: str, operation_name: str, status: int,
              ok_statuses=(200, 201, 202, 204)) -> Optional[str]:
    """Record an HTTP status on the call's span; log what kind of failure a
    non-OK status is. Returns the failure kind, or None if it was fine.
    Telemetry must never break the caller: an unknown status is noted only."""
    if not isinstance(status, int):
        span.set_attribute("http.status_code", str(status))
        return None
    span.set_attribute("http.status_code", status)
    if status in ok_statuses:
        return None
    kind = http_failure_kind(status) or CLIENT
    span.set_attribute("failure_kind", kind)
    span.set_status(Status(StatusCode.ERROR, f"HTTP {status} ({kind})"))
    logging.getLogger(f"external.{service}").warning(
        "[CALL] %s.%s answered HTTP %s (%s)", service, operation_name, status,
        kind, extra={"event": "call_http_error", "status": "FAILED",
                     "service": service, "failure_kind": kind})
    return kind


_google_instrumented = False


def instrument_google_api() -> None:
    """Trace every Google API request (Sheets) at its single choke point:
    googleapiclient's HttpRequest.execute. The operation name is the API
    method id, e.g. sheets.spreadsheets.values.get — never the data."""
    global _google_instrumented
    if _google_instrumented:
        return
    from googleapiclient import http as google_http

    original = google_http.HttpRequest.execute

    @wraps(original)
    def execute(self, *args, **kwargs):
        method = getattr(self, "methodId", None) or "request"
        with external_call("google_sheets", method):
            return original(self, *args, **kwargs)

    google_http.HttpRequest.execute = execute
    _google_instrumented = True
