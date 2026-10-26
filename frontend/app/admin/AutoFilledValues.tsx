"use client";

/**
 * Data quality → Auto-filled values (tracker No. 146): every value the app
 * filled in by itself, with why, for an Admin or Super Admin to check.
 *
 *   Confirm — "this is right": marked as checked. Nothing is written.
 *   Correct — the right value is written to the CSP sheet, exactly as the
 *             sheet editor writes it, and counted as a correction by them.
 *
 * Nothing is sent to anyone. A corrected value is used the next time that
 * CSP's documents are made — as if it had been typed into the sheet. The RM
 * is not correctable here (it decides who owns the CSP).
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, QualityValue } from "../lib/api";

const PAGE = 50;

const FILTERS: [string, string][] = [
  ["auto", "Not checked yet"],
  ["corrected", "Corrected"],
  ["confirmed", "Confirmed"],
  ["", "All"],
];

const STATUS: Record<QualityValue["status"], { label: string; cls: string }> = {
  auto: { label: "Not checked", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  confirmed: { label: "Confirmed", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  corrected: { label: "Corrected", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  withdrawn: { label: "No longer filled", cls: "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400" },
};

const key = (v: QualityValue) => `${v.csp_id}:${v.field}`;

export default function AutoFilledValues({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState("auto");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<QualityValue[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<{ key: string; value: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [rowError, setRowError] = useState<{ key: string; text: string } | null>(null);

  const load = useCallback(
    (offset: number) =>
      api
        .qualityValues({ status, q: q.trim(), limit: PAGE, offset })
        .then((r) => {
          setError("");
          setTotal(r.total);
          setRows((old) => (offset ? [...old, ...r.values] : r.values));
        })
        .catch((e) => setError((e as ApiError).detail || "Could not load the values.")),
    [status, q]
  );

  useEffect(() => {
    load(0);
  }, [load]);

  async function act(v: QualityValue, newValue?: string) {
    setBusy(key(v));
    setRowError(null);
    try {
      const body = { csp_id: v.csp_id, field: v.field, current_value: v.current_value };
      const updated =
        newValue === undefined
          ? await api.confirmQualityValue(body)
          : await api.correctQualityValue({ ...body, new_value: newValue });
      setRows((old) => old.map((r) => (key(r) === key(v) ? updated : r)));
      setEditing(null);
      onChanged();
    } catch (e) {
      setRowError({ key: key(v), text: (e as ApiError).detail || "Could not save." });
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
            Auto-filled values — check or correct{" "}
            <span className="text-sm font-normal text-gray-500">({total})</span>
          </h3>
          <p className="text-xs text-gray-500">
            Confirm marks a value as right (nothing is written). Correct writes the right value to
            the CSP sheet, as the sheet editor does; it is used the next time that CSP&apos;s
            documents are made. Nothing is sent to anyone.
          </p>
        </div>
        <div className="flex gap-1">
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
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="CSP code, name or value…"
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
        />
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-5 py-2">CSP</th>
              <th className="px-5 py-2">Field</th>
              <th className="px-5 py-2">Value</th>
              <th className="px-5 py-2">Why this value</th>
              <th className="px-5 py-2">State</th>
              <th className="px-5 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {rows.map((v) => {
              const k = key(v);
              const isEditing = editing?.key === k;
              return (
                <tr key={k} className="align-top">
                  <td className="px-5 py-2">
                    <div className="text-gray-900 dark:text-white">{v.csp_name || "—"}</div>
                    <div className="text-xs font-mono text-gray-500">{v.csp_id}</div>
                  </td>
                  <td className="px-5 py-2 text-gray-900 dark:text-white whitespace-nowrap">{v.label}</td>
                  <td className="px-5 py-2 max-w-xs">
                    {isEditing ? (
                      <input
                        autoFocus
                        value={editing.value}
                        onChange={(e) => setEditing({ key: k, value: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && editing.value.trim()) act(v, editing.value);
                          if (e.key === "Escape") setEditing(null);
                        }}
                        className="w-full px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
                      />
                    ) : (
                      <div className="text-gray-900 dark:text-white break-words">{v.current_value}</div>
                    )}
                    {v.status === "corrected" && (
                      <div className="text-xs text-gray-500 mt-1 break-words">
                        The app had filled: {v.auto_value}
                      </div>
                    )}
                    {rowError?.key === k && (
                      <div className="text-xs text-red-600 dark:text-red-400 mt-1">{rowError.text}</div>
                    )}
                  </td>
                  <td className="px-5 py-2 text-gray-600 dark:text-gray-300 max-w-xs">
                    <div>{v.source_label}</div>
                    <div className="text-xs text-gray-500">{v.detail}</div>
                  </td>
                  <td className="px-5 py-2 whitespace-nowrap">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS[v.status].cls}`}>
                      {STATUS[v.status].label}
                    </span>
                    {v.checked_via && (
                      <div className="text-xs text-gray-500 mt-1">
                        {v.checked_via}
                        {v.checked_by ? ` · ${v.checked_by}` : ""}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-2 whitespace-nowrap text-right">
                    {!v.editable ? (
                      <span className="text-xs text-gray-400" title={v.not_editable_reason}>
                        <i className="fas fa-lock mr-1"></i>Not here
                      </span>
                    ) : isEditing ? (
                      <div className="flex gap-1 justify-end">
                        <button
                          disabled={busy === k || !editing.value.trim()}
                          onClick={() => act(v, editing.value)}
                          className={`${button} bg-navy-900 text-white hover:bg-navy-800`}
                        >
                          {busy === k ? "Saving…" : "Save to sheet"}
                        </button>
                        <button
                          disabled={busy === k}
                          onClick={() => setEditing(null)}
                          className={`${button} text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700`}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex gap-1 justify-end">
                        {v.status === "auto" && (
                          <button
                            disabled={busy === k}
                            onClick={() => act(v)}
                            className={`${button} bg-green-50 text-green-700 hover:bg-green-100 dark:bg-green-900/30 dark:text-green-300`}
                          >
                            <i className="fas fa-check mr-1"></i>Confirm
                          </button>
                        )}
                        <button
                          disabled={busy === k}
                          onClick={() => {
                            setRowError(null);
                            setEditing({ key: k, value: v.current_value });
                          }}
                          className={`${button} text-eko hover:bg-eko/10`}
                        >
                          <i className="fas fa-pen mr-1"></i>Correct
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && !error && (
              <tr>
                <td colSpan={6} className="px-5 py-6 text-sm text-gray-500">
                  {status === "auto" ? "Nothing waiting to be checked." : "Nothing here."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {rows.length < total && (
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700">
          <button onClick={() => load(rows.length)} className="text-sm text-eko hover:underline">
            Show {Math.min(PAGE, total - rows.length)} more
          </button>
        </div>
      )}
    </section>
  );
}
