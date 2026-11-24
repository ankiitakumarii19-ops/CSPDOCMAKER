"use client";

/**
 * Setup — Columns (No. 211, Stage 4; ZU-04)
 *
 * Which column of the workspace's main sheet is which field. Eko's column
 * names are the start; "Guess from my sheet" reads the sheet's headings and
 * suggests one for each field (fixed rules, no AI) — the Super Admin only
 * confirms or corrects, then saves.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, ColumnsGuess, ColumnsView } from "../lib/api";

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";
const btn = "px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50";
const select =
  "w-full px-2 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white";

export default function Columns() {
  const [view, setView] = useState<ColumnsView | null>(null);
  const [guess, setGuess] = useState<ColumnsGuess | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .columns()
      .then((v) => {
        if (!alive) return;
        setView(v);
        setChosen(Object.fromEntries(v.fields.map((f) => [f.field, f.header])));
      })
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the columns."));
    return () => {
      alive = false;
    };
  }, []);

  async function runGuess() {
    setBusy(true);
    setError("");
    try {
      const g = await api.guessColumns();
      setGuess(g);
      setChosen((c) => {
        const next = { ...c };
        Object.entries(g.guess).forEach(([field, s]) => (next[field] = s.header));
        g.not_found.forEach((field) => {
          if (!g.headers.includes(next[field])) next[field] = "";
        });
        return next;
      });
      setMessage(`Read ${g.headers.length} headings. Check each guess, then Save.`);
    } catch (e) {
      setError((e as ApiError).detail || "Could not read the sheet.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      const v = await api.saveColumns(chosen);
      setView(v);
      setMessage("Saved. The next sheet read uses these columns.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (!view) {
    return (
      <div className="text-sm text-gray-500">
        {error ? <span className="text-red-600 dark:text-red-400">{error}</span> : "Loading…"}
      </div>
    );
  }

  const options = guess ? guess.headers : [];
  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Columns</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Which column of your main sheet holds each field. Eko&apos;s column names are the start; press
          <strong> Guess from my sheet</strong> and only correct what is wrong.
        </p>
      </div>
      <div className="flex gap-2">
        <button className={`${btn} border border-eko text-eko-dark dark:text-eko`} disabled={busy} onClick={runGuess}>
          {busy ? "Reading…" : "Guess from my sheet"}
        </button>
        <button className={`${btn} bg-eko hover:bg-eko-dark text-white`} disabled={busy} onClick={save}>
          Save
        </button>
      </div>
      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div className="text-sm text-eko-dark dark:text-eko">{message}</div>}
      <section className={`${card} divide-y divide-gray-100 dark:divide-gray-700`}>
        {view.fields.map((f) => {
          const g = guess?.guess[f.field];
          const value = chosen[f.field] ?? "";
          return (
            <div key={f.field} className="p-3 flex flex-col sm:flex-row sm:items-center gap-2">
              <div className="sm:w-1/3">
                <div className="text-sm font-semibold text-gray-900 dark:text-white">{f.label}</div>
                <div className="text-[11px] text-gray-500">Eko: {f.eko_header}</div>
              </div>
              <div className="sm:w-2/5">
                {options.length > 0 ? (
                  <select
                    className={select}
                    value={value}
                    onChange={(e) => setChosen({ ...chosen, [f.field]: e.target.value })}
                  >
                    <option value="">— not in my sheet —</option>
                    {options.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={select}
                    value={value}
                    onChange={(e) => setChosen({ ...chosen, [f.field]: e.target.value })}
                  />
                )}
              </div>
              <div className="sm:w-1/4 text-[11px]">
                {g ? (
                  <span
                    className={
                      g.score >= 0.9 ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"
                    }
                  >
                    {g.score >= 0.9 ? "Sure" : "Likely"} — {g.how}
                  </span>
                ) : guess ? (
                  <span className="text-gray-400">No guess</span>
                ) : f.own ? (
                  <span className="text-gray-500">Your own name</span>
                ) : null}
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
