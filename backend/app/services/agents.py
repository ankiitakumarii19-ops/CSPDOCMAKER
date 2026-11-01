"""
CSP DocMaker — what each agent actually does

Six implementations. Every one is ordinary code reading the database and
reporting what it sees. None of them decides whether a document is valid,
whether a photo is the right size, or whether a required field is present —
that remains where it was, deterministic, because being right matters more
there than being clever.

What they add is the layer that was missing: somebody whose job it is to
notice.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.agent import CRITICAL, INFO, WARNING
from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.models.data_source import DataSource
from app.models.document_template import DocumentTemplate
from app.models.processing_job import ProcessingJob
from app.models.sync_run import SyncRun
from app.services import field_ownership as fo
from app.services.agent_runner import Finding, Outcome, performs

from app.services.data_request_service import fields_to_ask as drs_fields_to_ask

logger = logging.getLogger(__name__)


def _blank(record, name: str) -> bool:
    value = getattr(record, name, None)
    return not (str(value).strip() if value is not None else "")


# =========================================================================
# Setup Agent — is this workspace ready?
# =========================================================================

@performs("setup")
def setup_agent(session) -> Outcome:
    findings, problems = [], 0

    sources = session.execute(select(DataSource)).scalars().all()
    if not sources:
        problems += 1
        findings.append(Finding(
            title="No data source is configured",
            detail="Records cannot arrive until a source is connected.",
            severity=CRITICAL,
        ))
    for source in sources:
        if source.last_status == "failed":
            problems += 1
            findings.append(Finding(
                title=f"Data source '{source.name}' last failed",
                detail=source.last_error or "No reason was recorded.",
                severity=WARNING,
                subject_type="data_source", subject_id=str(source.id),
            ))

    templates = session.execute(select(DocumentTemplate)).scalars().all()
    if not templates:
        problems += 1
        findings.append(Finding(
            title="No document templates",
            detail="Upload at least one before anything can be issued.",
            severity=CRITICAL,
        ))

    for template in templates:
        mapping = template.placeholder_map or {}
        unmapped = [p for p, f in mapping.items() if not f]
        if unmapped:
            problems += 1
            # A proposal, not a change: mapping a placeholder decides what
            # prints on an official document.
            findings.append(Finding(
                title=f"'{template.name}' has {len(unmapped)} unmapped "
                      f"placeholder(s)",
                detail=f"Nothing fills {', '.join(sorted(unmapped))}. The "
                       f"document would print a blank there.",
                severity=WARNING,
                proposal={"action": "map_placeholders",
                          "template": template.code,
                          "placeholders": sorted(unmapped)},
                subject_type="document_template", subject_id=template.code,
            ))
        elif not template.active and mapping:
            findings.append(Finding(
                title=f"'{template.name}' is ready but not active",
                detail="Every placeholder is mapped. It can be switched on.",
                severity=INFO,
                proposal={"action": "activate_template",
                          "template": template.code},
                subject_type="document_template", subject_id=template.code,
            ))

    summary = (
        f"{len(sources)} source(s), {len(templates)} template(s). "
        + (f"{problems} thing(s) need attention."
           if problems else "Nothing is blocking this workspace.")
    )
    return Outcome(summary=summary, findings=findings,
                   detail={"sources": len(sources),
                           "templates": len(templates),
                           "problems": problems})


# =========================================================================
# Data Agent — who should be asked for what?
# =========================================================================

@performs("data")
def data_agent(session) -> Outcome:
    from app.services.rm_resolution import UNRESOLVED

    records = session.execute(select(CSPRecord)).scalars().all()
    findings = []
    need_csp, need_rm, complete = [], [], 0

    for record in records:
        missing = fo.missing(record)
        csp_side = missing[fo.CSP]
        # Only the ones the directory can never answer are a person's job.
        org_side = fo.unfillable_by_info(missing[fo.ORG])
        if not csp_side and not org_side:
            complete += 1
            continue
        if csp_side:
            need_csp.append(record.csp_id)
        if org_side:
            need_rm.append(record.csp_id)

    unowned = [r.csp_id for r in records if r.rm_resolution == UNRESOLVED]
    if unowned:
        findings.append(Finding(
            title=f"{len(unowned)} record(s) belong to no RM",
            detail=f"Every RM can see {', '.join(unowned[:10])}"
                   + (" and others." if len(unowned) > 10 else "."),
            severity=WARNING,
        ))

    if need_csp:
        findings.append(Finding(
            title=f"{len(need_csp)} CSP(s) must supply their own details",
            detail="Only the CSP knows these, so their RM cannot fill them.",
            severity=INFO,
        ))
    if need_rm:
        findings.append(Finding(
            title=f"{len(need_rm)} record(s) need details INFO could not fill",
            detail="The CSP is asked for these on WhatsApp (an RM is never "
                   "asked). Adding AO and RBO columns to INFO fills them "
                   "automatically instead.",
            severity=INFO,
        ))

    return Outcome(
        summary=f"{len(records)} record(s): {complete} complete, "
                f"{len(need_csp)} missing their own details, {len(need_rm)} "
                f"missing details INFO could not fill.",
        findings=findings,
        detail={"total": len(records), "complete": complete,
                "need_csp": len(need_csp), "need_rm": len(need_rm),
                "unowned": len(unowned)},
    )


# =========================================================================
# Verification Agent — does what they sent agree with what we had?
# =========================================================================

@performs("verification")
def verification_agent(session) -> Outcome:
    """Decides every difference itself — the newest value wins (No. 171,
    services/verification_auto.py). Nothing waits for a person; each
    decision is logged once, with the old and new value."""
    from app.config import get_settings
    from app.models.agent import ACCEPTED, AgentFinding, PROPOSED
    from app.services import message_sender
    from app.services import verification_auto as va

    now = datetime.now(timezone.utc)
    requests = session.execute(select(DataRequest)).scalars().all()
    findings = []
    answered = [r for r in requests if r.status == "answered"]
    open_now = [r for r in requests
                if r.status == "open" and _aware(r.expires_at) > now]
    expired = [r for r in requests
               if r.status in ("open", "expired")
               and _aware(r.expires_at) <= now]

    # The cards it used to leave for a person are closed: it decides now.
    for card in session.execute(select(AgentFinding).where(
            AgentFinding.agent_key == "verification",
            AgentFinding.status == PROPOSED)).scalars():
        card.status, card.decided_by, card.decided_at = (
            ACCEPTED, "verification agent (automatic)", now)

    records = {r.csp_id: r for r in session.execute(
        select(CSPRecord).where(CSPRecord.csp_id.in_(
            {r.csp_id for r in answered}))).scalars()} if answered else {}
    decisions = []
    for request, name, submitted in va.newest_answers(answered):
        record = records.get(request.csp_id)
        if record is None:
            continue
        d = va.decide(request, name, submitted, getattr(record, name, None))
        if d is not None:
            decisions.append(d)

    logged = va.already_logged(session, [d.key for d in decisions])
    fresh = [d for d in decisions if d.key not in logged]
    on_server = message_sender.link_is_reachable(get_settings().public_app_url)
    kept, written, failed, waiting = 0, 0, 0, 0
    for d in fresh:
        if d.kind == va.KEPT_SHEET:
            va.log(session, d)
            kept += 1
            continue
        if not on_server:
            # Only the server writes to the sheet; it decides this one.
            waiting += 1
            continue
        try:
            va.write_answer(session, d, records[d.csp_id])
        except Exception as e:
            # Logged with its reason and tried again next run.
            logger.error("verification_agent: could not write %s %s to the "
                         "sheet: %s: %s", d.csp_id, d.field,
                         type(e).__name__, e, exc_info=True)
            failed += 1
            continue
        va.log(session, d)
        written += 1

    if kept or written:
        findings.append(Finding(
            title=f"Decided by itself: {written} CSP answer(s) written to the "
                  f"sheet, {kept} newer sheet value(s) kept",
            detail="The newest value wins. Each one is listed under "
                   "\"Decided automatically\" with the old and new value.",
            severity=INFO,
        ))
    if failed:
        findings.append(Finding(
            title=f"{failed} CSP answer(s) could not be written to the sheet",
            detail="Tried again on the next run. The reason is in the log.",
            severity=WARNING,
        ))

    if expired:
        findings.append(Finding(
            title=f"{len(expired)} link(s) expired unanswered",
            detail="These CSPs were asked and never replied. They need a "
                   "fresh link.",
            severity=INFO,
        ))

    return Outcome(
        summary=f"{len(answered)} answered, {len(open_now)} still open, "
                f"{len(expired)} expired; {len(decisions)} difference(s): "
                f"{written} answer(s) written to the sheet, {kept} newer "
                f"sheet value(s) kept"
                + (f", {waiting} left for the server" if waiting else "")
                + (f", {failed} failed" if failed else "") + ".",
        findings=findings,
        detail={"answered": len(answered), "open": len(open_now),
                "expired": len(expired), "differences": len(decisions),
                "written": written, "kept": kept, "failed": failed,
                "waiting_for_server": waiting},
    )


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# =========================================================================
# Document Agent — what is ready to be produced?
# =========================================================================

@performs("document")
def document_agent(session) -> Outcome:
    from app.services import document_registry as registry

    templates = [s for s in registry.all_specs(active_only=True)]
    records = session.execute(select(CSPRecord)).scalars().all()
    findings = []

    if not templates:
        findings.append(Finding(
            title="No active document template",
            detail="Nothing can be issued until one is activated.",
            severity=CRITICAL,
        ))

    ready, blocked = [], []
    needed = set()
    for spec in templates:
        needed |= set(spec.placeholder_map.values())
    # Only fields that live on a record; dates are computed at issue time.
    needed = {f for f in needed if hasattr(CSPRecord, f)}

    for record in records:
        if any(_blank(record, f) for f in needed):
            blocked.append(record.csp_id)
        else:
            ready.append(record.csp_id)

    if blocked:
        findings.append(Finding(
            title=f"{len(blocked)} record(s) cannot be issued yet",
            detail=f"Waiting on data: {', '.join(blocked[:10])}"
                   + (" and others." if len(blocked) > 10 else "."),
            severity=INFO,
        ))

    return Outcome(
        summary=f"{len(templates)} active template(s); {len(ready)} record(s) "
                f"ready, {len(blocked)} blocked.",
        findings=findings,
        detail={"templates": len(templates), "ready": len(ready),
                "blocked": len(blocked)},
    )


# =========================================================================
# Communication Agent — who needs to hear something?
# =========================================================================

# How many may be messaged in one run without somebody saying so. Beyond
# this the agent proposes rather than sends: a first bulk send is the kind
# of thing that should be meant.
BULK_THRESHOLD = 25


@performs("communication")
def communication_agent(session) -> Outcome:
    from app.models.messaging import MessageChannel
    from app.services import message_sender as sender
    from app.services.alert_composer import normalize_mobile

    channels = session.execute(
        select(MessageChannel).where(MessageChannel.active.is_(True))
    ).scalars().all()
    findings = []

    if not channels:
        return Outcome(
            summary="No channel is configured, so nothing can be sent.",
            findings=[Finding(
                title="No messaging channel",
                detail="Add a WhatsApp or email channel before this agent "
                       "can do anything.",
                severity=WARNING,
            )],
            detail={"channels": 0},
        )

    records = session.execute(select(CSPRecord)).scalars().all()
    asked = {r.csp_id for r in session.execute(
        select(DataRequest).where(DataRequest.status.in_(("open", "answered")))
    ).scalars().all()}

    to_ask, unreachable = [], []
    for record in records:
        if record.csp_id in asked:
            continue
        if not drs_fields_to_ask(record):
            continue
        if normalize_mobile(record.mobile or ""):
            to_ask.append(record.csp_id)
        elif (record.email or "").strip():
            to_ask.append(record.csp_id)        # email fallback
        else:
            unreachable.append(record.csp_id)

    if unreachable:
        findings.append(Finding(
            title=f"{len(unreachable)} CSP(s) cannot be reached at all",
            detail=f"No usable mobile and no email: "
                   f"{', '.join(unreachable[:10])}. Their RM has to collect "
                   f"the details in person.",
            severity=WARNING,
        ))

    if len(to_ask) > BULK_THRESHOLD:
        # Messaging a large group is the kind of thing somebody should
        # have meant to do, so the agent asks instead of doing it.
        findings.append(Finding(
            title=f"{len(to_ask)} CSPs are waiting to be asked",
            detail=f"That is more than {BULK_THRESHOLD} in one go. Nothing "
                   f"was sent — approve this and they will go out on the "
                   f"next run.",
            severity=INFO,
            proposal={"action": "send_data_requests",
                      "count": len(to_ask), "csp_ids": to_ask[:500]},
        ))
        return Outcome(
            summary=f"{len(to_ask)} CSP(s) waiting to be asked — too many to "
                    f"send without approval.",
            findings=findings,
            detail={"channels": len(channels), "to_ask": len(to_ask),
                    "unreachable": len(unreachable), "sent": 0},
        )

    # Small enough to just do.
    sent, failed = 0, []
    for csp_id in to_ask:
        record = session.execute(
            select(CSPRecord).where(CSPRecord.csp_id == csp_id)
        ).scalars().first()
        if record is None:
            continue
        try:
            outcome = sender.ask_for_details(session, record)
        except (sender.NoChannel, sender.NoTemplate) as e:
            findings.append(Finding(title="Cannot send", detail=str(e),
                                    severity=WARNING))
            break
        if outcome.get("sent"):
            sent += 1
        elif outcome.get("reason"):
            failed.append((csp_id, outcome["reason"]))

    for csp_id, reason in failed[:10]:
        findings.append(Finding(
            title=f"{csp_id} could not be asked",
            detail=reason, severity=WARNING,
            subject_type="csp", subject_id=csp_id,
        ))

    return Outcome(
        summary=f"{sent} asked, {len(failed)} could not be, "
                f"{len(unreachable)} unreachable.",
        findings=findings,
        detail={"channels": len(channels), "to_ask": len(to_ask),
                "sent": sent, "failed": len(failed),
                "unreachable": len(unreachable)},
    )


# =========================================================================
# Monitoring Agent — is anything quietly broken?
# =========================================================================

@performs("monitoring")
def monitoring_agent(session) -> Outcome:
    from app.models.agent import AgentState

    now = datetime.now(timezone.utc)
    findings = []

    # Has each source synced when it should have?
    for source in session.execute(select(DataSource)).scalars().all():
        if not source.active:
            continue
        due = (source.sync_interval_minutes or 15) * 3
        last = source.last_synced_at
        if last is None:
            findings.append(Finding(
                title=f"'{source.name}' has never synced",
                detail="It is active but has not run once.",
                severity=WARNING,
                subject_type="data_source", subject_id=str(source.id),
            ))
        elif _aware(last) < now - timedelta(minutes=due):
            findings.append(Finding(
                title=f"'{source.name}' has not synced recently",
                detail=f"Last ran {_aware(last):%d %b %H:%M}; it should run "
                       f"every {source.sync_interval_minutes} minutes.",
                severity=WARNING,
                subject_type="data_source", subject_id=str(source.id),
            ))

    # Recent sync failures.
    recent = session.execute(
        select(SyncRun).where(SyncRun.started_at > now - timedelta(hours=6))
    ).scalars().all()
    failed = [r for r in recent if r.status == "failed"]
    if failed:
        findings.append(Finding(
            title=f"{len(failed)} sync(s) failed in the last 6 hours",
            detail=(failed[-1].error_message or "")[:300],
            severity=WARNING if len(failed) < 5 else CRITICAL,
        ))

    # Jobs that stopped part-way.
    # A job is "stuck" only if it is not in a state it can legitimately
    # rest in. Both the finished states and the failure states count as
    # rested — a failure is already reported elsewhere, and calling it
    # stuck as well would report the same problem twice.
    from app.models.enums import JobState

    at_rest = [
        state for state in JobState
        if state.name.startswith("FAILED_")
        or state in (JobState.EMAIL_SENT, JobState.COMPLETED)
    ]
    stuck = session.execute(
        select(ProcessingJob).where(
            ProcessingJob.created_at < now - timedelta(hours=2),
            ProcessingJob.current_state.notin_(at_rest),
        )
    ).scalars().all()
    if stuck:
        findings.append(Finding(
            title=f"{len(stuck)} job(s) have been part-way for over 2 hours",
            detail=", ".join(f"{j.csp_id} at {j.current_state}"
                             for j in stuck[:8]),
            severity=WARNING,
        ))

    # An agent failing repeatedly.
    for state in session.execute(select(AgentState)).scalars().all():
        if (state.consecutive_failures or 0) >= 3:
            findings.append(Finding(
                title=f"The {state.agent_key} agent has failed "
                      f"{state.consecutive_failures} times in a row",
                detail=state.last_summary or "",
                severity=CRITICAL,
                proposal={"action": "disable_agent", "agent": state.agent_key},
                subject_type="agent", subject_id=state.agent_key,
            ))

    healthy = not findings
    return Outcome(
        summary="Nothing is stuck or failing." if healthy
                else f"{len(findings)} thing(s) need looking at.",
        findings=findings,
        detail={"issues": len(findings), "failed_syncs": len(failed),
                "stuck_jobs": len(stuck)},
    )
