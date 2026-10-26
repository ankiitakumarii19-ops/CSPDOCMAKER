"use client";

/**
 * Admin — Data quality (tracker No. 146)
 *
 * The app fills some of a CSP's blanks by itself: from INFO (AO, RBO, DC,
 * ASM, LHO, State, RM…), from the Zoho Lead (email, address, state,
 * gender) and from the temporary Address tab. This screen shows how often
 * people kept those values and how often they corrected them — on the
 * CSP's own form, in the app's sheet editor, in the Google Sheet or here —
 * so a rule that guesses wrong shows up as a number, with the cases listed.
 *
 * Context (the sheets the app reads, and how fresh), the harness (how the
 * app checks itself, No. 149) and the auto-filled values themselves (check
 * or correct) are at the top; Setup section, Admins and Super Admins. The
 * context and the harness are in the Knowledge Base too.
 */

import { useCallback, useEffect, useState } from "react";

import AutoFilledValues from "./AutoFilledValues";
import ContextSources from "./ContextSources";
import HarnessChecks from "./HarnessChecks";
import InfoSuggestions from "./InfoSuggestions";
import ContactFixes from "./ContactFixes";
import UnansweredQuestions from "./UnansweredQuestions";
import { api } from "../lib/api";
import type { ApiError, QualityCorrection, QualityScoreboard } from "../lib/api";

const PAGE = 50;

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function pct(value: number | null) {
  return value === null ? "—" : `${value}%`;
}

export default function DataQuality() {
  const [board, setBoard] = useState<QualityScoreboard | null>(null);
  const [fixes, setFixes] = useState<QualityCorrection[]>([]);
  const [total, setTotal] = useState(0);
  const [field, setField] = useState("");
  const [error, setError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  // Bumped after a value is confirmed or corrected, to recount.
  const [version, setVersion] = useState(0);

  const loadFixes = useCallback(
    (offset: number) =>
      api
        .qualityCorrections({ limit: PAGE, offset, field })
        .then((r) => {
          setTotal(r.total);
          setFixes((old) => (offset ? [...old, ...r.corrections] : r.corrections));
        })
        .catch((e) => setError((e as ApiError).detail || "Could not load the corrections.")),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- version: reload after an edit
    [field, version]
  );

  useEffect(() => {
    api
      .qualityScoreboard()
      .then(setBoard)
      .catch((e) => setError((e as ApiError).detail || "Could not load the scoreboard."));
  }, [version]);
  useEffect(() => {
    loadFixes(0);
  }, [loadFixes]);

  const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";
  const t = board?.total;
  const inUse = t ? t.auto + t.confirmed + t.corrected : 0;
  const acceptanceTone =
    t?.acceptance_rate == null
      ? "text-gray-900 dark:text-white"
      : t.acceptance_rate >= 75
      ? "text-green-700 dark:text-green-400"
      : "text-red-600 dark:text-red-400";

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Data quality</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 max-w-3xl">
          What the app reads, the values it filled in by itself — from INFO, the Zoho Lead or the
          Address tab — and what people did with them. A correction is any change made on the
          CSP&apos;s form, in the sheet editor, in the Google Sheet or here. Counted from 26 Oct
          2026; earlier fills are not known.
        </p>
      </div>

      <ContextSources />
      <HarnessChecks version={version} />
      {/* The feedback loops (No. 150). Loop 4 (golden cases) runs on the
          laptop before every push; its row is in the Harness table. */}
      <InfoSuggestions onChanged={() => setVersion((v) => v + 1)} />
      <ContactFixes version={version} />
      <UnansweredQuestions onChanged={() => setVersion((v) => v + 1)} />
      <AutoFilledValues onChanged={() => setVersion((v) => v + 1)} />

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {t && (
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
          {[
            ["Filled values in use", String(inUse), "text-gray-900 dark:text-white",
             `${t.withdrawn} no longer supplied`],
            ["Kept without correction", pct(t.acceptance_rate), acceptanceTone, "target above 75%"],
            ["Checked by a person and kept", pct(t.checked_kept_rate),
             "text-gray-900 dark:text-white", `${t.confirmed + t.corrected} checked so far`],
            ["Corrected", String(t.corrected), "text-amber-600 dark:text-amber-400",
             `${t.auto} not checked yet`],
            ["Characters changed, on average", t.avg_edit_distance === null ? "—" : String(t.avg_edit_distance),
             "text-gray-900 dark:text-white", "per correction; lower is better"],
          ].map(([label, value, tone, hint]) => (
            <div key={label} className={`${card} p-4`}>
              <div className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
              <div className="text-sm text-gray-700 dark:text-gray-300">{label}</div>
              <div className="text-xs text-gray-500 mt-1">{hint}</div>
            </div>
          ))}
        </div>
      )}

      <section className={card}>
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
          <h3 className="font-semibold text-gray-900 dark:text-white">By field and source</h3>
          <p className="text-xs text-gray-500">Click a row to see its corrections.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-5 py-2">Field</th>
                <th className="px-5 py-2">Filled from</th>
                <th className="px-5 py-2 text-right">Filled</th>
                <th className="px-5 py-2 text-right">Not checked</th>
                <th className="px-5 py-2 text-right">Confirmed</th>
                <th className="px-5 py-2 text-right">Corrected</th>
                <th className="px-5 py-2 text-right">Kept</th>
                <th className="px-5 py-2 text-right">Checked &amp; kept</th>
                <th className="px-5 py-2 text-right">Avg. chars changed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {board?.fields.map((r) => (
                <tr
                  key={`${r.field}:${r.source}`}
                  onClick={() => setField(field === r.field ? "" : r.field)}
                  className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                    field === r.field ? "bg-eko/5" : ""
                  }`}
                >
                  <td className="px-5 py-2 text-gray-900 dark:text-white">{r.label}</td>
                  <td className="px-5 py-2 text-gray-600 dark:text-gray-300">{r.source_label}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{r.filled}</td>
                  <td className="px-5 py-2 text-right tabular-nums text-gray-500">{r.auto}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{r.confirmed}</td>
                  <td className={`px-5 py-2 text-right tabular-nums ${r.corrected ? "text-amber-600 dark:text-amber-400 font-semibold" : ""}`}>
                    {r.corrected}
                  </td>
                  <td className="px-5 py-2 text-right tabular-nums">{pct(r.acceptance_rate)}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{pct(r.checked_kept_rate)}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{r.avg_edit_distance ?? "—"}</td>
                </tr>
              ))}
              {board && board.fields.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-5 py-6 text-sm text-gray-500">
                    Nothing filled automatically yet. The CSP sheet sync records INFO&apos;s fills on
                    its next run.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {board && board.trend.length > 0 && (
        <section className={card}>
          <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold text-gray-900 dark:text-white">Week by week</h3>
            <p className="text-xs text-gray-500">
              Fewer corrections, and fewer characters changed, mean the rules are getting better.
            </p>
          </div>
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-5 py-2">Week of</th>
                <th className="px-5 py-2 text-right">Values filled</th>
                <th className="px-5 py-2 text-right">Corrections</th>
                <th className="px-5 py-2 text-right">Avg. chars changed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {board.trend.map((w) => (
                <tr key={w.week}>
                  <td className="px-5 py-2 text-gray-900 dark:text-white">
                    {new Date(w.week).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                  </td>
                  <td className="px-5 py-2 text-right tabular-nums">{w.filled}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{w.corrections}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{w.avg_edit_distance ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className={card}>
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center gap-3">
          <h3 className="font-semibold text-gray-900 dark:text-white flex-1">
            Corrections{field ? ` — ${board?.fields.find((r) => r.field === field)?.label ?? field}` : ""}{" "}
            <span className="text-sm font-normal text-gray-500">({total})</span>
          </h3>
          {field && (
            <button onClick={() => setField("")} className="text-sm text-eko hover:underline">
              Show all
            </button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-5 py-2">CSP</th>
                <th className="px-5 py-2">Field</th>
                <th className="px-5 py-2">The app filled</th>
                <th className="px-5 py-2">Changed to</th>
                <th className="px-5 py-2 text-right">Chars</th>
                <th className="px-5 py-2">Where, by whom</th>
                <th className="px-5 py-2">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {fixes.map((c, i) => (
                <tr key={`${c.csp_id}:${c.field}:${c.created_at}:${i}`}>
                  <td className="px-5 py-2 font-mono text-xs text-gray-700 dark:text-gray-300">{c.csp_id}</td>
                  <td className="px-5 py-2 text-gray-900 dark:text-white">
                    {c.label}
                    <div className="text-xs text-gray-500">{c.source_label}</div>
                  </td>
                  <td className="px-5 py-2 text-gray-500 break-words max-w-xs">{c.auto_value}</td>
                  <td className="px-5 py-2 text-gray-900 dark:text-white break-words max-w-xs">{c.new_value}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{c.edit_distance}</td>
                  <td className="px-5 py-2 text-gray-600 dark:text-gray-300">
                    {c.changed_via}
                    {c.changed_by && <div className="text-xs text-gray-500">{c.changed_by}</div>}
                  </td>
                  <td className="px-5 py-2 text-gray-500 whitespace-nowrap">{when(c.created_at)}</td>
                </tr>
              ))}
              {fixes.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-6 text-sm text-gray-500">No corrections yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {fixes.length < total && (
          <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700">
            <button
              disabled={loadingMore}
              onClick={async () => {
                setLoadingMore(true);
                await loadFixes(fixes.length);
                setLoadingMore(false);
              }}
              className="text-sm text-eko hover:underline disabled:opacity-50"
            >
              {loadingMore ? "Loading…" : `Show ${Math.min(PAGE, total - fixes.length)} more`}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
