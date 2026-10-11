r"""Show one run, step by step, from the telemetry logs (PROJECT-REGISTER No. 79).

    python scripts/show_run.py <id>            # Run ID, Request ID or Error ID
    python scripts/show_run.py <id> --full     # full tracebacks
    python scripts/show_run.py --failures 10   # the 10 most recent failed runs

Reads logs/app.jsonl (and its rotated copies) and logs/traces.jsonl. Prints
the timeline (START / SUCCESS / FAILED, calls with their attempt numbers,
retries, crashes) and, when something failed, an ERROR REPORT in the
project's agreed format. Read-only: it changes nothing.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.environ.get("LOG_DIR", os.path.join(HERE, "..", "logs"))

HINTS = {
    "timeout": "The service did not answer in time. Check it is up and the network is "
               "stable; the call is retryable.",
    "connection": "The service could not be reached (DNS, network, or it is down). Check "
                  "connectivity from this machine.",
    "auth": "The service refused our credentials. Check the key/token in backend/.env "
            "and that it has not expired or been revoked.",
    "rate_limit": "The service is throttling us. Wait and retry; reduce how often we call it.",
    "server": "The service failed on its side (5xx). Retry later; if it persists, raise it "
              "with the service owner.",
    "client": "The service rejected the request itself (4xx). Check what we sent "
              "(path, parameters).",
    "malformed": "The reply could not be read (not JSON / not a PDF). Check the service's "
                 "response format.",
    "empty": "The reply was empty where data was expected.",
    "schema": "The reply was missing fields we rely on; the service may have changed.",
}


def _read_jsonl(pattern):
    rows = []
    for path in sorted(glob.glob(pattern), reverse=True):   # oldest rotation first
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        rows.append({"severity": "WARNING", "message":
                                     f"(unreadable log line in {os.path.basename(path)})"})
    return rows


def _logs():
    return _read_jsonl(os.path.join(LOG_DIR, "app.jsonl*"))


def _matches(row, wanted):
    return wanted in (row.get("run_id"), row.get("request_id"),
                      row.get("trace_id"), row.get("operation_id"))


def show(wanted, full=False):
    logs = [r for r in _logs() if _matches(r, wanted)]
    if not logs:
        print(f"No log lines found for {wanted!r} in {os.path.abspath(LOG_DIR)}.")
        return 1
    logs.sort(key=lambda r: r.get("time", ""))
    run_id = logs[0].get("run_id")
    print(f"RUN {run_id}   ({len(logs)} log lines, "
          f"{logs[0].get('time', '?')} → {logs[-1].get('time', '?')})\n")

    last_ok, failures, retries, crashed = None, [], 0, False
    for r in logs:
        event, sev = r.get("event"), r.get("severity", "")
        mark = {"start": "→", "success": "✓", "failed": "✗", "call_ok": "✓",
                "call_failed": "✗", "call_http_error": "!", "retry": "↻",
                "crash": "‼", "unhandled": "✗"}.get(event, " ")
        line = f"{r.get('time', '')[11:23]} {sev:<8} {mark} {r.get('message', '')}"
        if r.get("duration_ms") is not None and "ms" not in line:
            line += f"  [{r['duration_ms']} ms]"
        print(line)
        if event in ("success", "call_ok"):
            last_ok = r
        if event in ("failed", "call_failed", "unhandled", "crash") or sev in ("ERROR", "CRITICAL"):
            failures.append(r)
            tb = r.get("traceback")
            if tb:
                body = tb.rstrip().splitlines()
                shown = body if full else body[-12:]
                if not full and len(body) > 12:
                    print("      … (use --full for the whole traceback)")
                for t in shown:
                    print("      " + t)
        if event == "retry" or (event == "call_failed" and r.get("retryable")
                                and (r.get("attempt") or 1) < (r.get("max_attempts") or 1)):
            retries += 1
        if event == "crash":
            crashed = True

    if not failures:
        print("\nRESULT: no failures in this run.")
        return 0

    first = failures[0]
    final = logs[-1]
    recovered = final.get("event") in ("success", "call_ok") and not crashed
    kind = next((f.get("failure_kind") for f in failures if f.get("failure_kind")), None)
    print("\n" + "=" * 70)
    print("ERROR REPORT")
    print(f"Run ID:                   {run_id}")
    print(f"Time:                     {first.get('time')}")
    print(f"Status:                   {'RECOVERED' if recovered else ('CRASHED' if crashed else 'FAILED')}")
    print(f"Failed Component:         {first.get('component')}")
    print(f"Function:                 {first.get('failed_function') or first.get('function')}"
          f"  ({first.get('failed_at') or first.get('file')})")
    if first.get("raised_in"):
        print(f"Raised In:                {first.get('raised_in')}")
    print(f"Operation:                {first.get('operation')}")
    print(f"What Was Happening:       {first.get('context') or first.get('message')}")
    print(f"Error Type:               {first.get('error_type')}")
    print(f"Error Message:            {first.get('error_message') or first.get('message')}")
    if first.get("service"):
        print(f"External Service:         {first.get('service')} "
              f"(attempt {first.get('attempt')} of {first.get('max_attempts')})")
    print(f"Failure Kind:             {kind or 'not an external call'}")
    print(f"Previous Successful Step: {last_ok.get('operation') if last_ok else 'none in this run'}")
    print(f"Failed Step:              {first.get('operation')}")
    print(f"Retry:                    {'yes (' + str(retries) + ')' if retries else 'no'}")
    print(f"Recovery:                 {'a later step succeeded' if recovered else 'none — run ended in failure'}")
    print(f"Likely Cause:             {HINTS.get(kind, 'See the error message and traceback above.')}")
    print("Traceback:                shown above" + ("" if full else " (last lines; --full for all)"))
    return 2


def recent_failures(n):
    logs = [r for r in _logs() if r.get("event") in ("failed", "call_failed", "unhandled", "crash")
            and r.get("severity") in ("ERROR", "CRITICAL")]
    seen, out = set(), []
    for r in sorted(logs, key=lambda r: r.get("time", ""), reverse=True):
        if r.get("run_id") in seen:
            continue
        seen.add(r.get("run_id"))
        out.append(r)
        if len(out) >= n:
            break
    if not out:
        print("No failures recorded.")
        return 0
    for r in out:
        print(f"{r.get('time', '')[:19]}  run={r.get('run_id')}  "
              f"{r.get('operation')}  {r.get('error_type') or ''}: "
              f"{(r.get('error_message') or r.get('message', ''))[:90]}")
    print("\nShow one with:  python scripts/show_run.py <run>")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", nargs="?", help="Run ID, Request ID or Error ID")
    ap.add_argument("--full", action="store_true", help="full tracebacks")
    ap.add_argument("--failures", type=int, metavar="N",
                    help="list the N most recent failed runs")
    a = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError) as e:
            print(f"(could not switch console to UTF-8: {e})")
    if a.failures:
        return recent_failures(a.failures)
    if not a.id:
        ap.print_help()
        return 1
    return show(a.id, a.full)


if __name__ == "__main__":
    sys.exit(main())
