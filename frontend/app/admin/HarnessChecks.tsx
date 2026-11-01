"use client";

/**
 * Data quality → Harness (tracker No. 149): every way the app checks its
 * own work — the auto-fill record, corrections, kept rate, freshness,
 * sending failures, unanswered chat questions, golden cases, tests — and
 * where each stands now. The same list is in the Knowledge Base ("How does
 * the app check itself?").
 *
 * Check, What it watches and How can be edited (No. 171); Now and State
 * stay the app's own. A save also rewrites the chat's answer.
 */

import { useEffect, useState } from "react";

import { EditButtons } from "./ContextSources";
import { api } from "../lib/api";
import type { ApiError, HarnessCheck } from "../lib/api";

const STATE: Record<HarnessCheck["state"], { label: string; cls: string }> = {
  ok: { label: "Working", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  attention: { label: "Needs a look", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  empty: { label: "No data yet", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  laptop: { label: "Checked before each push", cls: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
};

export default function HarnessChecks({ version }: { version: number }) {
  const [checks, setChecks] = useState<HarnessCheck[] | null>(null);
  const [draft, setDraft] = useState<HarnessCheck[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError("");
    try {
      await api.saveQualityTexts(
        "harness",
        draft.map(({ key, name, watches, how }) => ({ key, name, watches, how }))
      );
      setChecks((await api.qualityHarness()).checks);
      setDraft(null);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const change = (i: number, field: "name" | "watches" | "how", value: string) =>
    setDraft((d) => d && d.map((c, j) => (j === i ? { ...c, [field]: value } : c)));
  const input =
    "w-full px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm";

  useEffect(() => {
    api
      .qualityHarness()
      .then((r) => {
        setChecks(r.checks);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load the checks."));
  }, [version]);

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">Harness — how the app checks itself</h3>
          <p className="text-xs text-gray-500">
            Every check on the app&apos;s own work, and where it stands now.
          </p>
        </div>
        <EditButtons
          editing={draft !== null}
          saving={saving}
          onEdit={() => checks && setDraft(checks.map((c) => ({ ...c })))}
          onSave={save}
          onCancel={() => setDraft(null)}
        />
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-5 py-2">Check</th>
              <th className="px-5 py-2">What it watches</th>
              <th className="px-5 py-2">How</th>
              <th className="px-5 py-2">Now</th>
              <th className="px-5 py-2">State</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {(draft ?? checks)?.map((c, i) => (
              <tr key={c.key} className="align-top">
                {draft ? (
                  <>
                    <td className="px-5 py-2 min-w-[10rem]">
                      <input className={input} value={c.name} maxLength={80}
                        onChange={(e) => change(i, "name", e.target.value)} />
                    </td>
                    <td className="px-5 py-2 min-w-[14rem]">
                      <textarea className={input} rows={3} value={c.watches} maxLength={1000}
                        onChange={(e) => change(i, "watches", e.target.value)} />
                    </td>
                    <td className="px-5 py-2 min-w-[14rem]">
                      <textarea className={input} rows={3} value={c.how} maxLength={1000}
                        onChange={(e) => change(i, "how", e.target.value)} />
                    </td>
                  </>
                ) : (
                  <>
                    <td className="px-5 py-2 text-gray-900 dark:text-white whitespace-nowrap">{c.name}</td>
                    <td className="px-5 py-2 text-gray-600 dark:text-gray-300">{c.watches}</td>
                    <td className="px-5 py-2 text-gray-500">{c.how}</td>
                  </>
                )}
                <td className="px-5 py-2 text-gray-900 dark:text-white">{c.now}</td>
                <td className="px-5 py-2 whitespace-nowrap">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${STATE[c.state].cls}`}>
                    {STATE[c.state].label}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
