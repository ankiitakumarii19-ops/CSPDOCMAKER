"""Telemetry: nothing fails silently (PROJECT-REGISTER No. 79, 12 Oct 2026).

Each test causes a real failure (or success) and reads what was written to
the log and trace files, so these prove the records exist — not just that
the code ran.
"""

import json
import logging
import os
import time

import httpx
import pytest

from app import telemetry


def _lines(name):
    path = os.path.join(telemetry.LOG_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _logs_for(run_id):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return [r for r in _lines("app.jsonl") if r.get("run_id") == run_id]


def _spans_named(name):
    return [s for s in _lines("traces.jsonl") if s.get("name") == name]


@pytest.fixture(autouse=True)
def _ready():
    telemetry.setup("cspdocmaker-test")


# ---- operations ---------------------------------------------------------------

def test_a_successful_step_records_start_success_and_duration():
    with telemetry.run() as run_id:
        with telemetry.operation("unit_ok_step", "tests", csp_id="1A850344"):
            time.sleep(0.01)
    records = _logs_for(run_id)
    events = [r.get("event") for r in records]
    assert events == ["start", "success"]
    done = records[-1]
    assert done["status"] == "SUCCESS" and done["duration_ms"] >= 10
    assert done["operation"] == "unit_ok_step" and done["operation_id"] != "-"
    assert "csp_id=1A850344" in records[0]["context"]
    assert _spans_named("unit_ok_step")[-1]["status"] == "OK"


def test_a_failed_step_records_type_message_traceback_and_reraises():
    with telemetry.run() as run_id:
        with pytest.raises(ValueError, match="clusters"):
            with telemetry.operation("unit_failing_step", "tests"):
                raise ValueError("Number of clusters cannot exceed samples")
    failed = [r for r in _logs_for(run_id) if r.get("event") == "failed"][0]
    assert failed["severity"] == "ERROR" and failed["status"] == "FAILED"
    assert failed["error_type"] == "ValueError"
    assert "clusters" in failed["error_message"]
    assert "Traceback" in failed["traceback"]
    assert failed["function"] and failed["component"] == "tests"
    span = _spans_named("unit_failing_step")[-1]
    assert span["status"] == "ERROR"
    assert any(e["name"] == "exception" for e in span["events"])


def test_ids_are_on_every_line_and_steps_nest():
    with telemetry.run(request_id="req-123") as run_id:
        with telemetry.operation("outer_step", "tests"):
            with telemetry.operation("inner_step", "tests"):
                logging.getLogger("tests").info("inside")
    inside = [r for r in _logs_for(run_id) if r["message"] == "inside"][0]
    assert inside["request_id"] == "req-123" and inside["operation"] == "inner_step"
    inner, outer = _spans_named("inner_step")[-1], _spans_named("outer_step")[-1]
    assert inner["parent_span_id"] == outer["span_id"]
    assert inner["trace_id"] == outer["trace_id"]


# ---- external services: failures are told apart --------------------------------

@pytest.mark.parametrize("error,kind", [
    (httpx.ReadTimeout("read timed out"), telemetry.TIMEOUT),
    (httpx.ConnectError("connection refused"), telemetry.CONNECTION),
    (TimeoutError("timed out"), telemetry.TIMEOUT),
    (json.JSONDecodeError("Expecting value", "", 0), telemetry.MALFORMED),
    (telemetry.ExternalResponseError(telemetry.EMPTY, "no rows"), telemetry.EMPTY),
    (telemetry.ExternalResponseError(telemetry.SCHEMA, "no job_id"), telemetry.SCHEMA),
])
def test_each_kind_of_failure_is_named(error, kind):
    with telemetry.run() as run_id:
        with pytest.raises(type(error)):
            with telemetry.external_call("unit_service", "do_thing"):
                raise error
    failed = [r for r in _logs_for(run_id) if r.get("event") == "call_failed"][0]
    assert failed["failure_kind"] == kind
    assert failed["service"] == "unit_service"


@pytest.mark.parametrize("status,kind", [
    (401, telemetry.AUTH), (403, telemetry.AUTH), (429, telemetry.RATE_LIMIT),
    (500, telemetry.SERVER), (503, telemetry.SERVER), (504, telemetry.TIMEOUT),
    (404, telemetry.CLIENT), (200, None), (204, None),
])
def test_http_statuses_are_classified(status, kind):
    assert telemetry.http_failure_kind(status) in (kind, None) if kind is None \
        else telemetry.http_failure_kind(status) == kind


def test_an_http_error_status_is_logged_with_its_kind():
    with telemetry.run() as run_id:
        with telemetry.external_call("unit_http", "get") as span:
            assert telemetry.note_http(span, "unit_http", "get", 429) == telemetry.RATE_LIMIT
    note = [r for r in _logs_for(run_id) if r.get("event") == "call_http_error"][0]
    assert note["failure_kind"] == telemetry.RATE_LIMIT


def test_retries_are_explicit_attempt_by_attempt():
    with telemetry.run() as run_id:
        for attempt in (1, 2):
            try:
                with telemetry.external_call("unit_retry", "fetch",
                                             attempt=attempt, max_attempts=2):
                    if attempt == 1:
                        raise httpx.ReadTimeout("slow")
            except httpx.ReadTimeout:
                continue
    records = [r for r in _logs_for(run_id) if r.get("service") == "unit_retry"]
    assert records[0]["event"] == "call_failed" and records[0]["attempt"] == 1
    assert records[0]["severity"] == "WARNING", "a retryable failure is a warning"
    assert records[0]["retryable"] is True
    assert records[1]["event"] == "call_ok" and records[1]["attempt"] == 2


def test_a_non_retryable_failure_is_an_error_not_a_retry():
    with telemetry.run() as run_id:
        with pytest.raises(telemetry.ExternalResponseError):
            with telemetry.external_call("unit_auth", "login", attempt=1,
                                         max_attempts=3):
                raise telemetry.ExternalResponseError(telemetry.AUTH, "bad key")
    failed = [r for r in _logs_for(run_id) if r.get("event") == "call_failed"][0]
    assert failed["severity"] == "ERROR" and failed["retryable"] is False
    assert "will retry" not in failed["message"]


def test_google_api_calls_are_traced_at_their_choke_point():
    from googleapiclient import http as google_http
    assert getattr(google_http.HttpRequest.execute, "__wrapped__", None) is not None


# ---- secrets never reach the logs ---------------------------------------------------

@pytest.mark.parametrize("raw,leak", [
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig_123", "eyJhbGci"),
    ("key wabs_FAKEexample000000", "wabs_FAKE"),
    ("password=hunter2 next", "hunter2"),
    ('{"client_secret": "s3cr3t"}', "s3cr3t"),
    ("mail ankita.kumari.intern@eko.co.in now", "ankita.kumari"),
    ("call 9876543210 today", "9876543210"),
    ("call +91 98765 43210 today", "98765 43210"),
])
def test_secrets_and_contact_details_are_masked(raw, leak):
    assert leak not in telemetry.redact(raw)


def test_a_logged_secret_never_reaches_the_file():
    with telemetry.run() as run_id:
        logging.getLogger("tests").error("login failed password=hunter2 for "
                                         "someone@eko.co.in")
    line = _logs_for(run_id)[0]
    assert "hunter2" not in json.dumps(line)
    assert "someone@eko.co.in" not in json.dumps(line)


def test_csp_codes_are_not_mistaken_for_phone_numbers():
    assert "1A850344" in telemetry.redact("CSP 1A850344 processed")


# ---- crashes ---------------------------------------------------------------------------

def test_a_crash_report_names_the_last_success_and_the_running_step():
    with telemetry.run() as run_id:
        with telemetry.operation("step_before_crash", "tests"):
            pass
        token = telemetry.operation_name_var.set("step_that_crashed")
        try:
            raise RuntimeError("boom")
        except RuntimeError as e:
            telemetry.crash_report(type(e), e, e.__traceback__, "unit test")
        finally:
            telemetry.operation_name_var.reset(token)
    crash = [r for r in _logs_for(run_id) if r.get("event") == "crash"][0]
    assert crash["severity"] == "CRITICAL" and "CRASH DETECTED" in crash["message"]
    assert "step_before_crash" in crash["message"]
    assert "step_that_crashed" in crash["message"]
    assert "Traceback" in crash["traceback"]


# ---- what the user sees -------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="session")
async def test_every_response_carries_a_request_id(client):
    r = await client.get("/api/auth/config")
    assert len(r.headers["X-Request-ID"]) >= 8


@pytest.mark.asyncio(loop_scope="session")
async def test_a_given_request_id_is_kept_and_a_bad_one_replaced(client):
    r = await client.get("/api/auth/config", headers={"X-Request-ID": "trace-me-42"})
    assert r.headers["X-Request-ID"] == "trace-me-42"
    r = await client.get("/api/auth/config",
                         headers={"X-Request-ID": "bad id; drop table"})
    assert r.headers["X-Request-ID"] != "bad id; drop table"


@pytest.mark.asyncio(loop_scope="session")
async def test_an_unexpected_error_gives_the_user_an_error_id(migrated_db, monkeypatch):
    # Like a real server: the error becomes a 500 response, not an exception
    # thrown at the caller (the test client re-raises by default).
    from app.main import app
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    from app.services import auth_service

    async def broken(*a, **k):
        raise RuntimeError("database exploded")
    monkeypatch.setattr(auth_service, "get_user_by_email", broken)
    r = await client.post("/api/auth/resend-otp", json={"email": "a@eko.co.in"},
                          headers={"X-Request-ID": "err-777"})
    assert r.status_code == 500
    body = r.json()
    assert body["error_id"] == "err-777"
    assert ("POST /api/auth/resend-otp" in body["detail"]
            and "err-777" in body["detail"])
    assert "database exploded" not in body["detail"], "internals leaked to the user"
    failed = [x for x in _logs_for("err-777") if x.get("event") in ("failed", "unhandled")]
    assert failed and any("database exploded" in x.get("error_message", "") for x in failed)
