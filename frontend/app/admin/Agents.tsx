"use client";

/**
 * Admin — Agents
 *
 * Six workers, each with one responsibility and a record of what it did.
 *
 * The screen is built around the distinction that matters: what an agent
 * may do by itself, and what it must ask about. A finding carrying a
 * proposal is shown as a decision, not a notification — accepting it is a
 * deliberate act, because an agent that could quietly remap a placeholder
 * could quietly print the wrong name on every certificate.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { AgentInfo, AgentFinding, AgentRun, ApiError } from "../lib/api";

export default function Agents({
  canSeeHistory = false,
  canAct = false,
}: {
  /** Running, switching and approving agents is the Super Admin's
   *  (decided 12 Oct 2026, tracker No. 88). An Admin sees everything but
   *  the buttons; the server refuses those actions too. */
  canAct?: boolean;
  /** The run history is the Workspace Owner's alone: it records who
   *  triggered each pass and every error raised, which is an audit of how
   *  the workspace has been operated rather than a view of the work. The
   *  button is hidden rather than offered and then refused. */
  canSeeHistory?: boolean;
}) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [findings, setFindings] = useState<AgentFinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  // What each agent has actually done. Fetched when its history is opened
  // rather than for all six up front — the answer to "has this one been
  // working?" is wanted for one agent at a time.
  const [history, setHistory] = useState<string | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  async function showHistory(key: string) {
    if (history === key) {
      setHistory(null);
      return;
    }
    setHistory(key);
    setRuns([]);
    setLoadingRuns(true);
    try {
      setRuns((await api.agentRuns(key)).runs);
    } catch (e) {
      setError((e as ApiError).detail || "Could not load that history.");
    } finally {
      setLoadingRuns(false);
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, f] = await Promise.all([
        api.listAgents(),
        api.agentFindings(),
      ]);
      setAgents(a.agents);
      setFindings(f.findings);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the agents.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runNow(key: string) {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      const r = await api.runAgent(key);
      setNotice(`${key}: ${r.summary}`);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not run that agent.");
    } finally {
      setBusy("");
    }
  }

  async function toggle(key: string, enabled: boolean) {
    setBusy(key);
    setError("");
    try {
      await api.toggleAgent(key, enabled);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not change that.");
    } finally {
      setBusy("");
    }
  }

  async function decide(id: string, accept: boolean) {
    setBusy(id);
    setError("");
    try {
      const r = accept
        ? await api.acceptFinding(id)
        : await api.rejectFinding(id);
      setNotice(
        accept
          ? (r as { note?: string }).note ??
            "Recorded. Apply it on the matching screen."
          : "Declined."
      );
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not record that.");
    } finally {
      setBusy("");
    }
  }

  const decisions = findings.filter((f) => f.needs_decision);
  const notes = findings.filter((f) => !f.needs_decision);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">
          Agents
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 max-w-3xl">
          Each one owns a single question and answers it on a schedule. None
          of them decides whether a document is valid — that stays
          deterministic. What they add is noticing, routing and proposing.
        </p>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      {/* Anything waiting on a person */}
      {decisions.length > 0 && (
        <div className="rounded-xl border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-5">
          <h3 className="text-sm font-bold uppercase tracking-wider text-amber-900 dark:text-amber-300 mb-1">
            Waiting for your decision ({decisions.length})
          </h3>
          <p className="text-xs text-amber-800 dark:text-amber-400 mb-4">
            An agent will not change configuration on its own. These are its
            suggestions.
          </p>
          <div className="space-y-3">
            {decisions.map((f) => (
              <div
                key={f.id}
                className="p-3 rounded-lg bg-white dark:bg-gray-800 border border-amber-200 dark:border-amber-800"
              >
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  {f.title}
                </p>
                {f.detail && (
                  <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                    {f.detail}
                  </p>
                )}
                <div className="flex items-center gap-3 mt-3">
                  {canAct && (<>
                  <button
                    onClick={() => decide(f.id, true)}
                    disabled={busy === f.id}
                    className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => decide(f.id, false)}
                    disabled={busy === f.id}
                    className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:underline disabled:opacity-50"
                  >
                    Decline
                  </button>
                  </>)}
                  <span className="text-xs text-gray-400 ml-auto">
                    from the {f.agent} agent
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* The agents themselves */}
      <div className="space-y-3">
        {loading && (
          <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>
        )}
        {agents.map((a) => (
          <div
            key={a.key}
            className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
          >
            <div className="p-5 flex items-start justify-between gap-4 flex-wrap">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-bold text-gray-900 dark:text-white">
                    {a.name}
                  </h3>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                      a.enabled
                        ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                        : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                    }`}
                  >
                    {a.enabled ? "Running" : "Off"}
                  </span>
                  <span className="text-[11px] text-gray-500">
                    {a.every_minutes
                      ? `every ${a.every_minutes} min`
                      : "on demand"}
                  </span>
                  {a.consecutive_failures > 0 && (
                    <span className="text-[11px] text-red-600 font-medium">
                      failed {a.consecutive_failures}× in a row
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 italic">
                  {a.owns}
                </p>
                {a.last_summary && (
                  <p className="text-xs text-gray-500 mt-2">
                    Last run: {a.last_summary}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setOpen(open === a.key ? null : a.key)}
                  className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 px-2"
                >
                  {open === a.key ? "Hide" : "What it does"}
                </button>
                {canSeeHistory && (
                  <button
                    onClick={() => showHistory(a.key)}
                    className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 px-2"
                  >
                    {history === a.key ? "Hide history" : "History"}
                  </button>
                )}
                {canAct && (<>
                <button
                  onClick={() => runNow(a.key)}
                  disabled={busy === a.key}
                  className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
                >
                  {busy === a.key ? "Running…" : "Run now"}
                </button>
                <button
                  onClick={() => toggle(a.key, !a.enabled)}
                  disabled={busy === a.key}
                  className={`px-3 py-1.5 text-sm rounded-lg font-medium disabled:opacity-50 ${
                    a.enabled
                      ? "text-red-600 hover:underline"
                      : "bg-eko hover:bg-eko-dark text-white"
                  }`}
                >
                  {a.enabled ? "Turn off" : "Turn on"}
                </button>
                </>)}
              </div>
            </div>

            {open === a.key && (
              <div className="px-5 pb-5 pt-0 grid gap-4 md:grid-cols-3 text-sm border-t border-gray-100 dark:border-gray-700 mt-1">
                <Column title="What it does" items={a.does} />
                <Column title="What it may do alone" items={a.may} />
                <Column title="What it must ask about" items={a.proposes} />
              </div>
            )}

            {canSeeHistory && history === a.key && (
              <div className="px-5 pb-5 pt-4 border-t border-gray-100 dark:border-gray-700">
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
                  Every run, newest first
                </p>
                {loadingRuns && (
                  <p className="text-sm text-gray-500">Loading…</p>
                )}
                {!loadingRuns && runs.length === 0 && (
                  <p className="text-sm text-gray-400">
                    This agent has never run.
                  </p>
                )}
                {runs.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="text-xs uppercase text-gray-500">
                        <tr>
                          <th className="pb-2 pr-4 font-semibold">When</th>
                          <th className="pb-2 pr-4 font-semibold">Started by</th>
                          <th className="pb-2 pr-4 font-semibold">Result</th>
                          <th className="pb-2 pr-4 font-semibold">What it concluded</th>
                          <th className="pb-2 font-semibold">Found</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                        {runs.map((r) => (
                          <tr key={r.id}>
                            <td className="py-2 pr-4 whitespace-nowrap text-gray-600 dark:text-gray-400">
                              {new Date(r.started_at).toLocaleString()}
                            </td>
                            <td className="py-2 pr-4 text-gray-600 dark:text-gray-400">
                              {/* "schedule" means it ran on its own; an
                                  email means somebody clicked Run now. */}
                              {r.triggered_by === "schedule"
                                ? "the schedule"
                                : r.triggered_by || "—"}
                            </td>
                            <td className="py-2 pr-4">
                              <span
                                className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                                  r.status === "ok"
                                    ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                                    : r.status === "skipped"
                                    ? "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                                    : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                                }`}
                              >
                                {r.status}
                              </span>
                            </td>
                            <td className="py-2 pr-4 text-gray-700 dark:text-gray-300">
                              {r.summary}
                              {r.error && (
                                <span className="block text-xs text-red-600 dark:text-red-400">
                                  {r.error}
                                </span>
                              )}
                            </td>
                            <td className="py-2 tabular-nums text-gray-600 dark:text-gray-400">
                              {r.findings || ""}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Things it simply noticed */}
      {notes.length > 0 && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5">
          <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-3">
            Noticed ({notes.length})
          </h3>
          <div className="space-y-2">
            {notes.slice(0, 25).map((f) => (
              <div key={f.id} className="flex items-start gap-3 text-sm">
                <span
                  className={`mt-1 w-2 h-2 rounded-full shrink-0 ${
                    f.severity === "critical"
                      ? "bg-red-500"
                      : f.severity === "warning"
                      ? "bg-amber-500"
                      : "bg-gray-300"
                  }`}
                />
                <div>
                  <p className="text-gray-800 dark:text-gray-200">{f.title}</p>
                  {f.detail && (
                    <p className="text-xs text-gray-500">{f.detail}</p>
                  )}
                </div>
                <span className="text-[11px] text-gray-400 ml-auto shrink-0">
                  {f.agent}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Column({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
        {title}
      </p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item} className="text-gray-700 dark:text-gray-300 text-xs">
            • {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Banner({
  kind,
  children,
}: {
  kind: "ok" | "error";
  children: React.ReactNode;
}) {
  const style =
    kind === "ok"
      ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-700 dark:text-green-300"
      : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300";
  return (
    <div className={`px-4 py-3 rounded-lg border text-sm ${style}`}>
      {children}
    </div>
  );
}
