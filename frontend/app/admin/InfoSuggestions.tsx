"use client";

/**
 * Data quality → Loop 1: suggested INFO fixes (tracker No. 150).
 *
 * When people correct a value INFO filled in the same way on several CSPs,
 * the app suggests fixing INFO itself. Accept = the team will correct the
 * INFO sheet (the app does not write INFO); the app marks it "Fixed" once
 * INFO gives the right value. Dismiss = not a real INFO mistake.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, InfoSuggestion } from "../lib/api";

const FILTERS: [string, string][] = [
  ["open", "Waiting for a decision"],
  ["accepted", "Accepted"],
  ["fixed", "Fixed"],
  ["dismissed", "Dismissed"],
  ["", "All"],
];

const STATUS: Record<InfoSuggestion["status"], { label: string; cls: string }> = {
  open: { label: "Waiting for a decision", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  accepted: { label: "Accepted — fix INFO", cls: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  fixed: { label: "Fixed in INFO", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  dismissed: { label: "Dismissed", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
};

export default function InfoSuggestions({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState("open");
  const [rows, setRows] = useState<InfoSuggestion[] | null>(null);
  const [minCsps, setMinCsps] = useState(2);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(
    () =>
      api
        .qualitySuggestions(status)
        .then((r) => {
          setRows(r.suggestions);
          setMinCsps(r.min_csps);
          setError("");
        })
        .catch((e) => setError((e as ApiError).detail || "Could not load the suggestions.")),
    [status]
  );

  useEffect(() => {
    load();
  }, [load]);

  async function decide(s: InfoSuggestion, action: "accept" | "dismiss") {
    setBusy(s.id);
    try {
      await api.decideSuggestion(s.id, action);
      await load();
      onChanged();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the decision.");
    } finally {
      setBusy("");
    }
  }

  const button = "px-2.5 py-1 rounded text-xs font-semibold disabled:opacity-50";

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[16rem]">
          <h3 className="font-semibold text-gray-900 dark:text-white">
            Loop 1 — suggested INFO fixes
          </h3>
          <p className="text-xs text-gray-500">
            The same correction to an INFO value on {minCsps} or more CSPs. <b>Fixed in INFO by the app
            itself</b> (within 30 minutes): AO and RBO Name — only the corrected branches move to the
            right row, the other branches are not touched — and a DC&apos;s or ASM&apos;s own email or phone.
            Every changed cell is listed below; anything it cannot do safely stays here with the reason.
            Names, LHO and State: Accept means your team corrects INFO; it is marked Fixed once INFO gives
            the right value.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {FILTERS.map(([value, label]) => (
            <button
              key={label}
              onClick={() => setStatus(value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
                status === value
                  ? "bg-eko/10 text-eko"
                  : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="divide-y divide-gray-100 dark:divide-gray-700">
        {rows?.map((s) => (
          <div key={s.id} className="px-5 py-3 flex flex-wrap items-start gap-4">
            <div className="flex-1 min-w-[18rem] text-sm">
              <div className="text-gray-900 dark:text-white">
                <b>{s.label}</b>: INFO gives <b>{s.from_value}</b>, people changed it to{" "}
                <b className="text-green-700 dark:text-green-400">{s.to_value}</b> on{" "}
                {s.csps.length} CSPs
              </div>
              <div className="text-xs text-gray-500 mt-0.5">{s.rule}</div>
              <div className="text-xs text-gray-500 mt-1">
                {s.csps.map((c) => `${c.name || "—"} (${c.csp_id})`).join(" · ")}
              </div>
              {s.still_wrong > 0 && s.status !== "fixed" && (
                <div className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                  INFO still gives {s.from_value} to {s.still_wrong} more CSP(s) nobody has checked.
                </div>
              )}
              {s.applied.length > 0 && (
                <ul className="text-xs text-gray-600 dark:text-gray-300 mt-1 list-disc ml-4">
                  {s.applied.map((a, i) => (
                    <li key={i}>
                      INFO {a.cell}: {a.before ? <>&ldquo;{a.before}&rdquo; → </> : null}&ldquo;{a.after}&rdquo;
                    </li>
                  ))}
                </ul>
              )}
              {s.note && s.status !== "fixed" && (
                <div className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                  Not changed automatically: {s.note}
                </div>
              )}
              {s.decided_by && (
                <div className="text-xs text-gray-400 mt-1">
                  {s.status === "dismissed" ? "Dismissed" : "Accepted"} by {s.decided_by}
                  {s.fixed_at ? ` · fixed ${new Date(s.fixed_at).toLocaleDateString("en-IN")}` : ""}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS[s.status].cls}`}>
                {STATUS[s.status].label}
              </span>
              {(s.status === "open" || s.status === "dismissed") && (
                <button
                  disabled={busy === s.id}
                  onClick={() => decide(s, "accept")}
                  className={`${button} bg-green-50 text-green-700 hover:bg-green-100 dark:bg-green-900/30 dark:text-green-300`}
                >
                  <i className="fas fa-check mr-1"></i>Accept
                </button>
              )}
              {(s.status === "open" || s.status === "accepted") && (
                <button
                  disabled={busy === s.id}
                  onClick={() => decide(s, "dismiss")}
                  className={`${button} text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700`}
                >
                  Dismiss
                </button>
              )}
            </div>
          </div>
        ))}
        {rows && rows.length === 0 && !error && (
          <p className="px-5 py-6 text-sm text-gray-500">
            {status === "open" ? "Nothing waiting for a decision." : "Nothing here."}
          </p>
        )}
      </div>
    </section>
  );
}
