"use client";

/**
 * Admin — Agent health (No. 252)
 *
 * Every agent (the six background agents and the chat) measured from what
 * it already records: does it run, on time, how fast against its own
 * normal, are its results good, are its proposals accepted. One score per
 * agent, the open issues (also in the header bell and emailed), the history
 * day by day, and what the agents learned — safe lessons applied by
 * themselves with Undo, the rest waiting for the Super Admin.
 *
 * Status is always an icon AND a word, never colour alone. Charts are one
 * series each (the score, 0-100) with a hover read-out and a table view.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { useMedia } from "../lib/useMedia";
import type {
  AgentHealth as Health,
  AgentHealthAgent,
  AgentHealthDay,
  AgentImprovement,
  AgentIssue,
  ApiError,
} from "../lib/api";

const STATUS: Record<string, { label: string; icon: string; chip: string }> = {
  green: {
    label: "Healthy",
    icon: "fa-check-circle",
    chip: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  },
  amber: {
    label: "Needs a look",
    icon: "fa-exclamation-triangle",
    chip: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  },
  red: {
    label: "Problem",
    icon: "fa-times-circle",
    chip: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  },
  grey: {
    label: "No data yet",
    icon: "fa-minus-circle",
    chip: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  },
  off: {
    label: "Switched off",
    icon: "fa-power-off",
    chip: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  },
};

const SEVERITY: Record<string, { label: string; icon: string; tone: string }> = {
  critical: { label: "Critical", icon: "fa-times-circle", tone: "text-red-700 dark:text-red-300" },
  warning: { label: "Warning", icon: "fa-exclamation-triangle", tone: "text-amber-700 dark:text-amber-300" },
};

const KIND_LABEL: Record<string, string> = {
  mute_rejected: "Stops asking",
  kb_phrasing: "Chat learned a wording",
  kb_entry: "Answer needed",
  disable_failing: "Switch off",
};

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${Math.round(v * 10) / 10}%`;
}

function secs(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function when(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function ago(minutes: number | null) {
  if (minutes === null) return "never";
  if (minutes < 2) return "just now";
  if (minutes < 120) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return `${Math.floor(minutes / 1440)} days ago`;
}

function StatusChip({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.grey;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${s.chip}`}>
      <i className={`fas ${s.icon}`} aria-hidden="true"></i>
      {s.label}
    </span>
  );
}

/** A small score line for a card: last 14 days, no axes. */
function Sparkline({ points }: { points: { day: string; score: number | null }[] }) {
  const values = points.filter((p) => p.score !== null);
  if (values.length < 2) {
    return <p className="text-xs text-gray-400 h-8 flex items-center">History builds up day by day.</p>;
  }
  const w = 120;
  const h = 32;
  const step = w / Math.max(points.length - 1, 1);
  const y = (s: number) => h - 2 - (s / 100) * (h - 4);
  let d = "";
  let pen = false;
  points.forEach((p, i) => {
    if (p.score === null) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${(i * step).toFixed(1)},${y(p.score).toFixed(1)} `;
    pen = true;
  });
  const last = values[values.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-28 h-8 text-eko" role="img"
      aria-label={`Score over ${points.length} days, latest ${last.score}`}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The score day by day (0-100) with a hover read-out. One series. */
function ScoreChart({ rows }: { rows: AgentHealthDay[] }) {
  const [hover, setHover] = useState<number | null>(null);
  // A narrower drawing on a phone, so the labels stay readable when scaled.
  const phone = useMedia("(max-width: 639px)");
  if (!rows.length) {
    return <p className="text-sm text-gray-500 py-6">No history yet — one point is kept each day from today.</p>;
  }
  const w = phone ? 360 : 900;
  const h = 200;
  const left = 32;
  const right = 8;
  const top = 10;
  const bottom = 24;
  const inner = w - left - right;
  const step = inner / Math.max(rows.length - 1, 1);
  const x = (i: number) => left + (rows.length === 1 ? inner / 2 : i * step);
  const y = (s: number) => top + (1 - s / 100) * (h - top - bottom);
  let d = "";
  let pen = false;
  rows.forEach((r, i) => {
    if (r.score === null) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(r.score).toFixed(1)} `;
    pen = true;
  });
  const shown = hover !== null ? rows[hover] : null;
  const labelEvery = Math.max(1, Math.ceil(rows.length / (phone ? 4 : 6)));
  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full h-auto text-eko"
        role="img"
        aria-label="Score per day, 0 to 100"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - box.left) / box.width) * w;
          const i = Math.round((px - left) / (step || 1));
          setHover(Math.min(rows.length - 1, Math.max(0, i)));
        }}
      >
        {[0, 50, 100].map((g) => (
          <g key={g}>
            <line x1={left} x2={w - right} y1={y(g)} y2={y(g)} className="stroke-gray-200 dark:stroke-gray-700" strokeWidth={1} />
            <text x={left - 6} y={y(g) + 4} textAnchor="end" className="fill-gray-500 dark:fill-gray-400" fontSize={11}>{g}</text>
          </g>
        ))}
        {rows.map((r, i) =>
          (i % labelEvery === 0 && rows.length - 1 - i >= labelEvery) || i === rows.length - 1 ? (
            <text
              key={r.day}
              x={x(i)}
              y={h - 6}
              textAnchor={rows.length > 1 && i === rows.length - 1 ? "end" : i === 0 && rows.length > 1 ? "start" : "middle"}
              className="fill-gray-500 dark:fill-gray-400"
              fontSize={11}
            >
              {new Date(r.day + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}
            </text>
          ) : null
        )}
        <path d={d} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        {rows.length === 1 && rows[0].score !== null && (
          <circle cx={x(0)} cy={y(rows[0].score)} r={4} fill="currentColor" />
        )}
        {shown && hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={top} y2={h - bottom} className="stroke-gray-400" strokeWidth={1} />
            {shown.score !== null && (
              <circle cx={x(hover)} cy={y(shown.score)} r={5} fill="currentColor" className="stroke-white dark:stroke-gray-800" strokeWidth={2} />
            )}
          </g>
        )}
      </svg>
      {shown && (
        <div className="absolute top-1 right-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs shadow">
          <div className="font-semibold text-gray-900 dark:text-white">
            {new Date(shown.day + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
          </div>
          <div className="text-gray-700 dark:text-gray-300">Score: {shown.score ?? "—"}</div>
          <div className="text-gray-500 dark:text-gray-400">Runs worked: {pct(shown.success_rate)} · Result: {pct(shown.result_rate)}</div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-gray-500 dark:text-gray-400 truncate" title={hint ? `${label} — ${hint}` : label}>{label}</div>
      <div className="text-sm font-semibold text-gray-900 dark:text-white">{value}</div>
    </div>
  );
}

export default function AgentHealth({ onOpenKnowledge }: { onOpenKnowledge?: () => void }) {
  const [data, setData] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [rows, setRows] = useState<AgentHealthDay[]>([]);
  const [showTable, setShowTable] = useState(false);
  const [pastIssues, setPastIssues] = useState<AgentIssue[] | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.agentHealth());
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load Agent health.");
    } finally {
      setLoading(false);
    }
  }, []);

  // First load and a refresh every 2 minutes (state set only in callbacks).
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .agentHealth()
        .then((d) => {
          if (!alive) return;
          setData(d);
          setError("");
        })
        .catch((e) => alive && setError((e as ApiError).detail || "Could not load Agent health."))
        .finally(() => alive && setLoading(false));
    tick();
    const t = setInterval(tick, 120_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    api
      .agentHealthHistory(days, open)
      .then((r) => setRows(r.rows))
      .catch((e) => setError((e as ApiError).detail || "Could not load the history."));
  }, [open, days]);

  async function checkNow() {
    setBusy("check");
    setNotice("");
    try {
      const r = await api.agentHealthCheck();
      setNotice(
        `Checked ${r.agents} agents: ${r.issues.open} open issue(s)` +
          (r.issues.opened ? `, ${r.issues.opened} new` : "") +
          (r.issues.resolved ? `, ${r.issues.resolved} fixed` : "") +
          (r.improvements.applied ? `; learned ${r.improvements.applied}` : "") +
          (r.improvements.proposed ? `; ${r.improvements.proposed} suggestion(s) for you` : "") +
          "."
      );
      await load();
      if (pastIssues) setPastIssues((await api.agentHealthIssues("resolved")).issues);
    } catch (e) {
      setError((e as ApiError).detail || "The check could not finish.");
    } finally {
      setBusy("");
    }
  }

  async function decide(imp: AgentImprovement, action: "apply" | "dismiss" | "undo") {
    setBusy(imp.id);
    setNotice("");
    try {
      await api.agentImprovement(imp.id, action);
      setNotice(action === "undo" ? "Undone." : action === "apply" ? "Applied." : "Noted — it won't be suggested again.");
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "That did not work.");
    } finally {
      setBusy("");
    }
  }

  async function toggleHistory() {
    if (pastIssues) {
      setPastIssues(null);
      return;
    }
    try {
      setPastIssues((await api.agentHealthIssues("resolved")).issues);
    } catch (e) {
      setError((e as ApiError).detail || "Could not load past issues.");
    }
  }

  const selected: AgentHealthAgent | undefined = useMemo(
    () => data?.agents.find((a) => a.key === open),
    [data, open]
  );

  if (loading && !data) {
    return <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      {/* Heading */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Agent health</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            How well each agent and the chat do their job, measured from what they record.
            Checked every 15 minutes{data?.checked_at ? ` — last ${when(data.checked_at)}` : ""}.
          </p>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <div className="text-right">
            <div className="text-xs text-gray-500 dark:text-gray-400">Overall</div>
            <div className="text-3xl font-bold text-gray-900 dark:text-white leading-none">
              {data?.overall ?? "—"}
              <span className="text-sm font-normal text-gray-500"> / 100</span>
            </div>
          </div>
          <button
            onClick={checkNow}
            disabled={busy === "check"}
            className="px-4 py-2 rounded-lg bg-eko text-white text-sm font-medium hover:opacity-90 disabled:opacity-50"
          >
            <i className={`fas ${busy === "check" ? "fa-spinner fa-spin" : "fa-sync-alt"} mr-2`}></i>
            Check now
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-300 flex justify-between gap-4">
          <span>{error}</span>
          <button onClick={() => setError("")} className="underline shrink-0">Close</button>
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 px-4 py-3 text-sm text-green-800 dark:text-green-300">
          {notice}
        </div>
      )}

      {/* Issues */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <h3 className="font-bold text-gray-900 dark:text-white">
            Open issues {data ? `(${data.issues.length})` : ""}
          </h3>
          <button onClick={toggleHistory} className="text-sm text-eko hover:underline">
            {pastIssues ? "Hide past issues" : "Show past issues"}
          </button>
        </div>
        {data && data.issues.length === 0 && (
          <p className="text-sm text-gray-600 dark:text-gray-300">
            <i className="fas fa-check-circle text-green-600 mr-2" aria-hidden="true"></i>
            Nothing wrong right now. Issues are also emailed to the Super Admins and shown in the bell.
          </p>
        )}
        <ul className="space-y-2">
          {data?.issues.map((i) => (
            <li key={i.id} className="rounded-lg border border-gray-100 dark:border-gray-700 p-3">
              <div className="flex items-start gap-2">
                <i className={`fas ${SEVERITY[i.severity]?.icon} mt-0.5 ${SEVERITY[i.severity]?.tone}`} aria-hidden="true"></i>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">
                    <span className={`${SEVERITY[i.severity]?.tone} mr-1`}>{SEVERITY[i.severity]?.label}:</span>
                    {i.title}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400">{i.detail}</div>
                  <div className="text-xs text-gray-400 mt-1">Since {when(i.first_seen_at)}</div>
                </div>
              </div>
            </li>
          ))}
        </ul>
        {pastIssues && (
          <div className="mt-4">
            <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Past issues</h4>
            {pastIssues.length === 0 ? (
              <p className="text-sm text-gray-500">None yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 border-b border-gray-200 dark:border-gray-700">
                      <th className="py-2 pr-3">Issue</th>
                      <th className="py-2 pr-3">From</th>
                      <th className="py-2">Fixed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pastIssues.map((i) => (
                      <tr key={i.id} className="border-b border-gray-100 dark:border-gray-700/50">
                        <td className="py-2 pr-3 text-gray-800 dark:text-gray-200">{i.title}</td>
                        <td className="py-2 pr-3 text-gray-500 whitespace-nowrap">{when(i.first_seen_at)}</td>
                        <td className="py-2 text-gray-500 whitespace-nowrap">{when(i.resolved_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Agents */}
      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {data?.agents.map((a) => (
          <button
            key={a.key}
            onClick={() => setOpen(open === a.key ? null : a.key)}
            className={`text-left rounded-xl border bg-white dark:bg-gray-800 p-4 transition-shadow hover:shadow ${
              open === a.key ? "border-eko ring-1 ring-eko" : "border-gray-200 dark:border-gray-700"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-bold text-gray-900 dark:text-white truncate">{a.name}</div>
                <div className="mt-1"><StatusChip status={a.status} /></div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-3xl font-bold text-gray-900 dark:text-white leading-none">{a.score ?? "—"}</div>
                <div className="text-xs text-gray-500">score</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-4">
              {a.key === "chat" ? (
                <>
                  <Metric label="Questions (24 h)" value={String(a.run.runs)} />
                  <Metric label="Typical answer time" value={secs(a.run.p50_ms)} />
                </>
              ) : (
                <>
                  <Metric label="Worked (24 h)" value={pct(a.run.success_rate)} hint={`${a.run.ok} of ${a.run.ok + a.run.failed}`} />
                  <Metric label="On schedule" value={a.run.on_schedule === null ? "on demand" : pct(a.run.on_schedule)} />
                </>
              )}
              <Metric label={a.result.label} value={pct(a.result.rate)} hint={`${a.result.good} of ${a.result.total}, ${a.result.basis}`} />
              <Metric label="Slow runs (p95)" value={secs(a.run.p95_ms)} hint={a.baseline_p95_ms ? `Its normal: ${secs(a.baseline_p95_ms)}` : "Its normal is learned over 3+ days"} />
            </div>
            <div className="flex items-end justify-between mt-3 gap-2">
              <span className="text-xs text-gray-500">
                {a.key === "chat"
                  ? `Last question ${a.run.last_question_at ? when(a.run.last_question_at) : "—"}`
                  : `Last run ${ago(a.minutes_since_last_run)}`}
                {a.open_issues ? ` · ${a.open_issues} issue(s)` : ""}
              </span>
              <Sparkline points={a.trend} />
            </div>
          </button>
        ))}
      </section>

      {/* One agent in full */}
      {selected && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <h3 className="font-bold text-gray-900 dark:text-white">{selected.name}</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 italic">{selected.owns}</p>
            </div>
            <div className="flex items-center gap-2">
              {[7, 30, 90].map((n) => (
                <button
                  key={n}
                  onClick={() => setDays(n)}
                  className={`px-3 py-1 rounded-full text-xs font-medium ${
                    days === n ? "bg-eko text-white" : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
                  }`}
                >
                  {n} days
                </button>
              ))}
              <button onClick={() => setOpen(null)} className="text-sm text-gray-500 hover:underline ml-2">Close</button>
            </div>
          </div>

          <ScoreChart rows={rows} />
          <button onClick={() => setShowTable(!showTable)} className="text-sm text-eko hover:underline">
            {showTable ? "Hide the numbers" : "Show the numbers day by day"}
          </button>
          {showTable && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b border-gray-200 dark:border-gray-700">
                    <th className="py-2 pr-3">Day</th>
                    <th className="py-2 pr-3">Score</th>
                    <th className="py-2 pr-3">Runs</th>
                    <th className="py-2 pr-3">Worked</th>
                    <th className="py-2 pr-3">On schedule</th>
                    <th className="py-2 pr-3">Slow (p95)</th>
                    <th className="py-2">{selected.result.label}</th>
                  </tr>
                </thead>
                <tbody>
                  {[...rows].reverse().map((r) => (
                    <tr key={r.day} className="border-b border-gray-100 dark:border-gray-700/50 text-gray-800 dark:text-gray-200">
                      <td className="py-1.5 pr-3 whitespace-nowrap">{r.day}</td>
                      <td className="py-1.5 pr-3">{r.score ?? "—"}</td>
                      <td className="py-1.5 pr-3">{r.runs ?? "—"}</td>
                      <td className="py-1.5 pr-3">{pct(r.success_rate)}</td>
                      <td className="py-1.5 pr-3">{pct(r.on_schedule)}</td>
                      <td className="py-1.5 pr-3">{secs(r.p95_ms)}</td>
                      <td className="py-1.5">{pct(r.result_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 pt-2 border-t border-gray-100 dark:border-gray-700">
            {selected.key !== "chat" && (
              <>
                <Metric label="Runs in 24 h" value={`${selected.run.runs} (${selected.run.failed} failed, ${selected.run.skipped} skipped)`} />
                <Metric label="Runs that worked" value={pct(selected.run.success_rate)} hint={`Bar: ${data?.bars.success}%`} />
                <Metric label="On schedule" value={selected.run.on_schedule === null ? "on demand" : `${pct(selected.run.on_schedule)} of ${selected.run.expected_runs}`} />
                <Metric label="Failed in a row" value={String(selected.consecutive_failures)} hint={`Alert at ${data?.bars.agent_failures}`} />
              </>
            )}
            <Metric label="Typical time (p50)" value={secs(selected.run.p50_ms)} />
            <Metric label="Slow runs (p95)" value={secs(selected.run.p95_ms)} />
            <Metric label="Its normal (p95, 14 days)" value={selected.baseline_p95_ms ? secs(selected.baseline_p95_ms) : "learning"} />
            <Metric label={selected.result.label} value={`${pct(selected.result.rate)} (${selected.result.good} of ${selected.result.total})`} hint={`Bar: ${selected.key === "chat" ? data?.bars.chat : data?.bars.result}% — ${selected.result.basis}`} />
            {selected.key !== "chat" && (
              <>
                <Metric label="Findings in 24 h" value={`${selected.run.findings} (${selected.run.critical} critical)`} />
                <Metric label="Findings per run" value={selected.run.findings_per_run === null ? "—" : String(selected.run.findings_per_run)} />
                <Metric label="Proposals accepted (30 days)" value={`${pct(selected.decisions.acceptance_rate)} (${selected.decisions.accepted} of ${selected.decisions.accepted + selected.decisions.rejected})`} hint={`Bar: ${data?.bars.acceptance}%`} />
                <Metric label="Proposals waiting" value={selected.decisions.waiting ? `${selected.decisions.waiting}, oldest ${Math.round(selected.decisions.oldest_waiting_hours ?? 0)} h` : "none"} />
                <Metric label="Quieted by a lesson (24 h)" value={String(selected.run.quieted)} />
              </>
            )}
          </div>
          {selected.result.note && <p className="text-sm text-gray-600 dark:text-gray-400">{selected.result.note}.</p>}

          {selected.key === "chat" && data && data.unanswered.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Asked most, not answered</h4>
              <ul className="text-sm space-y-1">
                {data.unanswered.map((u) => (
                  <li key={u.question} className="text-gray-700 dark:text-gray-300">
                    “{u.question}” <span className="text-gray-500">— {u.times_asked}×</span>
                  </li>
                ))}
              </ul>
              {onOpenKnowledge && (
                <button onClick={onOpenKnowledge} className="mt-2 text-sm text-eko hover:underline">
                  Answer them in the Knowledge Base
                </button>
              )}
            </div>
          )}
        </section>
      )}

      {/* Improvements */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
        <div>
          <h3 className="font-bold text-gray-900 dark:text-white">Improving itself</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {data?.auto_improve
              ? "Safe lessons are applied by the agents themselves, each with Undo. Anything that could reach a CSP, a document or a message waits for you."
              : "Self-improving is off (Settings → Agent health): every lesson waits for you."}
          </p>
        </div>

        <div>
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
            Waiting for you ({data?.improvements.waiting.length ?? 0})
          </h4>
          {data && data.improvements.waiting.length === 0 && (
            <p className="text-sm text-gray-500">Nothing to decide.</p>
          )}
          <ul className="space-y-2">
            {data?.improvements.waiting.map((imp) => (
              <li key={imp.id} className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3">
                <div className="text-xs font-medium text-amber-800 dark:text-amber-300">{KIND_LABEL[imp.kind] ?? imp.kind}</div>
                <div className="text-sm font-medium text-gray-900 dark:text-white">{imp.title}</div>
                <div className="text-sm text-gray-600 dark:text-gray-400">{imp.evidence}</div>
                <div className="flex gap-3 mt-2">
                  {imp.kind === "kb_entry" ? (
                    onOpenKnowledge && (
                      <button onClick={onOpenKnowledge} className="px-3 py-1.5 rounded-lg bg-eko text-white text-sm font-medium">
                        Write the answer
                      </button>
                    )
                  ) : (
                    <button
                      onClick={() => decide(imp, "apply")}
                      disabled={busy === imp.id}
                      className="px-3 py-1.5 rounded-lg bg-eko text-white text-sm font-medium disabled:opacity-50"
                    >
                      Apply
                    </button>
                  )}
                  <button
                    onClick={() => decide(imp, "dismiss")}
                    disabled={busy === imp.id}
                    className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:underline disabled:opacity-50"
                  >
                    Not needed
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
            History {data ? `(${data.improvements.in_force} in force)` : ""}
          </h4>
          {data && data.improvements.history.length === 0 && (
            <p className="text-sm text-gray-500">Nothing learned yet. Lessons come from how people use the agents and the chat.</p>
          )}
          <ul className="divide-y divide-gray-100 dark:divide-gray-700">
            {data?.improvements.history.map((imp) => (
              <li key={imp.id} className="py-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-gray-900 dark:text-white">{imp.title}</div>
                  <div className="text-xs text-gray-500">
                    {KIND_LABEL[imp.kind] ?? imp.kind} · {imp.status}
                    {imp.automatic ? " by itself" : imp.decided_by ? ` by ${imp.decided_by}` : ""} · {when(imp.decided_at || imp.created_at)}
                    {imp.note ? ` · ${imp.note}` : ""}
                  </div>
                </div>
                {imp.can_undo && (
                  <button
                    onClick={() => decide(imp, "undo")}
                    disabled={busy === imp.id}
                    className="text-sm text-red-600 hover:underline shrink-0 disabled:opacity-50"
                  >
                    Undo
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
