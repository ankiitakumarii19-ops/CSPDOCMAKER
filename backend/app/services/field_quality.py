"""
CSP DocMaker — how good are the values the app fills in by itself? (No. 146)

The app fills a CSP's blanks from INFO (in the sheet sync), from the Zoho
Lead's typed fields and from the temporary Address tab. Every such value is
recorded here with the reason it was chosen (field_provenance), and every
time a person changes one — the CSP on their form, an Eko user in the app's
sheet editor, anyone in the Google Sheet itself — the change is logged with
its edit distance from the original value (field_corrections).

That gives three things:

  * a "where did this value come from?" note on the CSP's panel;
  * a scoreboard: per field and source, how many filled values people
    kept, how many they corrected, and by how much;
  * a list of the corrections themselves — the cases a rule got wrong.

All functions take a SYNC Session (the workers' kind); an async caller uses
`await session.run_sync(field_quality.<fn>, ...)`. Nothing here is allowed
to stop the work it observes: the callers wrap it, log any failure with its
traceback and carry on — a missed measurement is a logged error, never a
failed sync or a CSP told their form did not go through.

Deterministic. No AI anywhere (AI_SPEC D1).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select

from app.models.field_provenance import FieldCorrection, FieldProvenance

logger = logging.getLogger(__name__)

SOURCES = {
    "info": "INFO tab",
    "zoho": "Zoho Lead",
    "address_tab": "Address tab",
}

VIA = {
    "csp_form": "CSP's own form",
    "sheet_editor": "App sheet editor",
    "sheet": "Google Sheet",
}

STATUS = ("auto", "confirmed", "corrected", "withdrawn")



class Known:
    """The provenance rows in hand, indexed by CSP then field, so the sync
    can look up one row's fields without scanning every CSP's."""

    def __init__(self, rows: Iterable[FieldProvenance] = ()):
        self._by: Dict[str, Dict[str, FieldProvenance]] = {}
        for p in rows:
            self.add(p)

    def add(self, p: FieldProvenance) -> None:
        self._by.setdefault(p.csp_id, {})[p.field] = p

    def get(self, csp_id: str, field: str) -> Optional[FieldProvenance]:
        return self._by.get(csp_id, {}).get(field)

    def of(self, csp_id: str) -> Dict[str, FieldProvenance]:
        return dict(self._by.get(csp_id, {}))


def norm(value) -> str:
    """Compared and stored the way the sheet shows it: spaces collapsed."""
    return " ".join(str(value or "").split())


def levenshtein(a: str, b: str) -> int:
    """Characters to insert, delete or change to turn a into b."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def load(session, csp_ids: Optional[Iterable[str]] = None) -> Known:
    """The provenance rows of this workspace (or of these CSPs)."""
    query = select(FieldProvenance)
    if csp_ids is not None:
        ids = sorted(set(csp_ids))
        if not ids:
            return Known()
        query = query.where(FieldProvenance.csp_id.in_(ids))
    return Known(session.execute(query).scalars().all())


# ---- an automatic fill --------------------------------------------------

def record_fill(session, csp_id: str, field: str, value: str, source: str,
                detail: str, known: Optional[Known] = None,
                now: Optional[datetime] = None) -> Optional[FieldProvenance]:
    """The app has just filled this field by itself. Starts (or restarts)
    its record as an unchecked guess. A blank value records nothing."""
    value = norm(value)
    if not csp_id or not value:
        return None
    now = now or datetime.now(timezone.utc)
    if known is None:
        known = load(session, [csp_id])
    p = known.get(csp_id, field)
    if p is None:
        p = FieldProvenance(csp_id=csp_id, field=field)
        session.add(p)
        known.add(p)
    elif (p.source, p.auto_value, p.detail, p.status) == (
            source, value, detail[:500], "auto"):
        return p      # nothing new — the sync sees the same fill every run
    p.source, p.detail = source, detail[:500]
    p.auto_value = p.current_value = value
    p.status, p.edit_distance = "auto", None
    p.checked_via = p.checked_by = p.checked_at = None
    p.filled_at = now
    return p


# ---- a person looked at it ----------------------------------------------

def _seen(session, p: FieldProvenance, value: str, via: str,
          by: Optional[str], now: datetime, confirm: bool) -> str:
    """A person-set value for a filled field. Returns 'confirmed',
    'corrected', or '' when it changes nothing."""
    value = norm(value)
    if not value or p.status == "withdrawn":
        return ""     # a blank means "no opinion", never "delete"
    if value == p.current_value:
        if confirm and p.status == "auto":
            p.status = "confirmed"
            p.checked_via, p.checked_by, p.checked_at = via, by, now
            return "confirmed"
        return ""
    distance = levenshtein(p.auto_value, value)
    session.add(FieldCorrection(
        csp_id=p.csp_id, field=p.field, source=p.source,
        auto_value=p.auto_value, old_value=p.current_value, new_value=value,
        edit_distance=distance, changed_via=via, changed_by=by))
    p.current_value = value
    p.status = "confirmed" if value == p.auto_value else "corrected"
    p.edit_distance = distance if p.status == "corrected" else None
    p.checked_via, p.checked_by, p.checked_at = via, by, now
    logger.info("field_quality: %s %s %s via %s (distance %d)",
                p.csp_id, p.field, p.status, via, distance)
    return "corrected"


def record_check(session, csp_id: str, values: Dict[str, str], via: str,
                 by: Optional[str] = None,
                 confirm: bool = True) -> Dict[str, int]:
    """A person sent these values for this CSP (the CSP's form, the sheet
    editor). A value equal to the filled one confirms it — unless confirm
    is False, for a screen that sends a whole row back whether or
    not anyone looked at each cell; a different one is a correction. Fields
    the app never filled are ignored."""
    now = datetime.now(timezone.utc)
    known = load(session, [csp_id])
    counts = {"confirmed": 0, "corrected": 0}
    for field, value in (values or {}).items():
        p = known.get(csp_id, field)
        if p is None:
            continue
        outcome = _seen(session, p, value, via, by, now, confirm=confirm)
        if outcome:
            counts[outcome] += 1
    return counts


# ---- what the sheet sync sees each run ----------------------------------

def observe_sync(session, known: Known, csp_id: str, mapped: Dict[str, str],
                 info_filled: Dict[str, str],
                 now: Optional[datetime] = None) -> int:
    """One CSP row as the sync built it. `info_filled` is {field: why} for
    the blanks INFO filled THIS run; every other value came from the sheet.

    Returns the number of corrections found (sheet edits nobody recorded
    from inside the app — someone typed in the Google Sheet)."""
    now = now or datetime.now(timezone.utc)
    for field, why in info_filled.items():
        record_fill(session, csp_id, field, mapped.get(field, ""), "info",
                    why, known=known, now=now)

    corrections = 0
    for field, p in known.of(csp_id).items():
        if field in info_filled or p.status == "withdrawn":
            continue
        value = norm(mapped.get(field, ""))
        if not value:
            if p.source == "info" and p.status == "auto":
                # INFO no longer supplies it and the sheet has none: the
                # guess is gone, without anyone having judged it.
                p.status, p.current_value = "withdrawn", ""
            continue
        # An INFO value now typed into the sheet unchanged: someone kept it.
        confirm = p.source == "info"
        if _seen(session, p, value, "sheet", None, now,
                 confirm=confirm) == "corrected":
            corrections += 1
    return corrections


# ---- reading it back ----------------------------------------------------

def sources_for(session, csp_id: str) -> Dict[str, dict]:
    """{field: where its value came from} for one CSP's panel."""
    out = {}
    for field, p in load(session, [csp_id]).of(csp_id).items():
        if p.status == "withdrawn":
            continue
        out[field] = {
            "source": p.source,
            "source_label": SOURCES.get(p.source, p.source),
            "detail": p.detail,
            "status": p.status,
            "auto_value": p.auto_value,
            "checked_via": VIA.get(p.checked_via or "", p.checked_via),
            "checked_at": p.checked_at.isoformat() if p.checked_at else None,
            "filled_at": p.filled_at.isoformat() if p.filled_at else None,
        }
    return out


def _label(field: str) -> str:
    from app.services import field_ownership
    return field_ownership.LABELS.get(field, field.replace("_", " ").title())


def scoreboard(session, weeks: int = 8) -> dict:
    """Per field and source: filled, kept, corrected, by how much; and the
    weekly trend of fills and corrections."""
    rows = session.execute(
        select(FieldProvenance.field, FieldProvenance.source,
               FieldProvenance.status, func.count(),
               func.avg(FieldProvenance.edit_distance))
        .group_by(FieldProvenance.field, FieldProvenance.source,
                  FieldProvenance.status)).all()

    groups: Dict[Tuple[str, str], dict] = {}
    for field, source, status, count, avg in rows:
        g = groups.setdefault((field, source), {
            "field": field, "label": _label(field), "source": source,
            "source_label": SOURCES.get(source, source),
            **{s: 0 for s in STATUS}, "avg_edit_distance": None})
        g[status] = count
        if status == "corrected" and avg is not None:
            g["avg_edit_distance"] = round(float(avg), 1)

    def rates(g: dict) -> dict:
        live = g["auto"] + g["confirmed"] + g["corrected"]
        checked = g["confirmed"] + g["corrected"]
        g["filled"] = live + g["withdrawn"]
        # Not corrected by anyone, out of every value still in use: the
        # memo's "implicit acceptance rate" (target > 75%).
        g["acceptance_rate"] = (round(100 * (live - g["corrected"]) / live, 1)
                                if live else None)
        # Kept, out of the values a person actually looked at — the
        # stricter number, because "nobody has checked yet" is not "right".
        g["checked_kept_rate"] = (round(100 * g["confirmed"] / checked, 1)
                                  if checked else None)
        return g

    fields = sorted((rates(g) for g in groups.values()),
                    key=lambda g: (-g["corrected"], g["label"], g["source"]))
    total = rates({s: sum(g[s] for g in fields) for s in STATUS})
    corrected = [g for g in fields if g["corrected"]]
    total["avg_edit_distance"] = (
        round(sum(g["avg_edit_distance"] * g["corrected"] for g in corrected)
              / sum(g["corrected"] for g in corrected), 1)
        if corrected else None)

    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    fill_week = func.date_trunc("week", FieldProvenance.filled_at)
    fixes_week = func.date_trunc("week", FieldCorrection.created_at)
    fills = dict(session.execute(
        select(fill_week, func.count()).where(
            FieldProvenance.filled_at >= since).group_by(fill_week)).all())
    fixes = {w: (n, d) for w, n, d in session.execute(
        select(fixes_week, func.count(),
               func.avg(FieldCorrection.edit_distance))
        .where(FieldCorrection.created_at >= since)
        .group_by(fixes_week)).all()}
    trend = [{
        "week": w.date().isoformat(),
        "filled": fills.get(w, 0),
        "corrections": fixes.get(w, (0, None))[0],
        "avg_edit_distance": (round(float(fixes[w][1]), 1)
                              if w in fixes and fixes[w][1] is not None
                              else None),
    } for w in sorted(set(fills) | set(fixes))]

    return {"total": total, "fields": fields, "trend": trend}


def recent_corrections(session, limit: int = 50, offset: int = 0,
                       field: str = "") -> dict:
    query = select(FieldCorrection)
    count = select(func.count()).select_from(FieldCorrection)
    if field:
        query = query.where(FieldCorrection.field == field)
        count = count.where(FieldCorrection.field == field)
    rows = session.execute(query.order_by(FieldCorrection.created_at.desc())
                           .offset(offset).limit(limit)).scalars().all()
    return {
        "total": session.execute(count).scalar() or 0,
        "corrections": [{
            "csp_id": c.csp_id,
            "field": c.field,
            "label": _label(c.field),
            "source_label": SOURCES.get(c.source, c.source),
            "auto_value": c.auto_value,
            "old_value": c.old_value,
            "new_value": c.new_value,
            "edit_distance": c.edit_distance,
            "changed_via": VIA.get(c.changed_via, c.changed_via),
            "changed_by": c.changed_by,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in rows],
    }


# ---- how fresh is each sheet? -------------------------------------------

def _freshness_sources(settings) -> List[Tuple[str, str, int, bool]]:
    """(sync_runs.source, label, expected minutes between runs, shown even
    with no runs yet)."""
    return [
        ("csp", "CSP sheet", settings.csp_sync_interval_minutes, True),
        ("authorization", "Sign-in list",
         settings.google_sheets_sync_interval_minutes, True),
        ("source_sheets", "Calling & Lead sheets",
         settings.source_sheets_interval_minutes,
         bool(settings.calling_sheet_id and settings.lead_sheet_id)),
        ("address", "Address tab", settings.source_sheets_interval_minutes,
         False),
    ]


def freshness(session, settings, now: Optional[datetime] = None,
              with_errors: bool = False) -> List[dict]:
    """One badge per sheet the app reads: when it last read it fully, and
    whether that is as expected.

    ok      — read within three intervals (plus five minutes' grace)
    stale   — the last good read is older than that
    stuck   — runs start but never finish (the 22-23 Oct CSP sync, No. 144)
    failed  — the newest finished run failed
    never   — no read has ever completed
    """
    from app.models.sync_run import SyncRun

    now = now or datetime.now(timezone.utc)
    out = []
    for source, label, minutes, always in _freshness_sources(settings):
        minutes = max(int(minutes or 1), 1)
        runs = session.execute(
            select(SyncRun).where(SyncRun.source == source)
            .order_by(SyncRun.started_at.desc()).limit(50)).scalars().all()
        if not runs and not always:
            continue
        last_ok = next((r for r in runs if r.status == "completed"), None)
        last_done = next((r for r in runs
                          if r.status in ("completed", "failed")), None)
        stale_after = timedelta(minutes=3 * minutes + 5)
        stuck_after = timedelta(minutes=max(15, 5 * minutes))
        unfinished = sum(1 for r in runs if r.status == "running"
                         and now - r.started_at > stuck_after)
        ok_at = (last_ok.finished_at or last_ok.started_at) if last_ok else None
        fresh = ok_at is not None and now - ok_at <= stale_after

        if last_done is not None and last_done.status == "failed":
            state = "failed"
        elif unfinished and not fresh:
            state = "stuck"
        elif ok_at is None:
            state = "never"
        elif not fresh:
            state = "stale"
        else:
            state = "ok"
        badge = {
            "source": source,
            "label": label,
            "status": state,
            "last_success_at": ok_at.isoformat() if ok_at else None,
            "minutes_since_success": (int((now - ok_at).total_seconds() // 60)
                                      if ok_at else None),
            "expected_every_minutes": minutes,
            "unfinished_runs": unfinished,
        }
        if with_errors and state == "failed":
            badge["error"] = (last_done.error_message or "")[:300]
        out.append(badge)
    return out
