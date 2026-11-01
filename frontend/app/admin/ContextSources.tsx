"use client";

/**
 * Data quality → Context (tracker No. 146): every sheet the app reads, when
 * it was last read fully, how often it should be, and — for Admins and
 * Super Admins — why the newest read failed. The same data as the header
 * chips, in full.
 *
 * The words (sheet name, "Used for") can be edited (No. 171); the dates
 * and states stay the app's own. A save also rewrites the chat's answer.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, ContextText, FreshnessBadge, FreshnessStatus } from "../lib/api";

const STATE: Record<FreshnessStatus, { label: string; cls: string }> = {
  ok: { label: "On time", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  stale: { label: "Late", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  stuck: { label: "Stuck", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  never: { label: "Never read", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
};

const input =
  "w-full px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm";

export default function ContextSources({ version = 0 }: { version?: number }) {
  const [badges, setBadges] = useState<FreshnessBadge[] | null>(null);
  const [words, setWords] = useState<Record<string, ContextText>>({});
  const [draft, setDraft] = useState<Record<string, ContextText> | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .freshness()
      .then((r) => setBadges(r.sources))
      .catch((e) => setError((e as ApiError).detail || "Could not load the sheets."));
    api
      .qualityTexts()
      .then((r) => setWords(Object.fromEntries(r.context.map((c) => [c.key, c]))))
      .catch((e) => setError((e as ApiError).detail || "Could not load the words."));
  }, [version]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError("");
    try {
      const r = await api.saveQualityTexts("context", Object.values(draft));
      setWords(Object.fromEntries(r.context.map((c) => [c.key, c])));
      setDraft(null);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">Context — what the app reads</h3>
          <p className="text-xs text-gray-500">
            The sheets every decision is made from, and when each was last read in full.
          </p>
        </div>
        <EditButtons
          editing={draft !== null}
          saving={saving}
          onEdit={() => setDraft({ ...words })}
          onSave={save}
          onCancel={() => setDraft(null)}
        />
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-5 py-2">Sheet</th>
              <th className="px-5 py-2">Used for</th>
              <th className="px-5 py-2">Last read in full</th>
              <th className="px-5 py-2">Expected</th>
              <th className="px-5 py-2">State</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {badges?.map((b) => (
              <tr key={b.source}>
                {draft && draft[b.source] ? (
                  <>
                    <td className="px-5 py-2">
                      <input
                        className={input}
                        value={draft[b.source].label}
                        maxLength={80}
                        onChange={(e) =>
                          setDraft({ ...draft, [b.source]: { ...draft[b.source], label: e.target.value } })
                        }
                      />
                    </td>
                    <td className="px-5 py-2">
                      <textarea
                        className={input}
                        rows={2}
                        value={draft[b.source].used_for}
                        maxLength={1000}
                        onChange={(e) =>
                          setDraft({ ...draft, [b.source]: { ...draft[b.source], used_for: e.target.value } })
                        }
                      />
                    </td>
                  </>
                ) : (
                  <>
                    <td className="px-5 py-2 text-gray-900 dark:text-white whitespace-nowrap">
                      {words[b.source]?.label ?? b.label}
                    </td>
                    <td className="px-5 py-2 text-gray-600 dark:text-gray-300">
                      {words[b.source]?.used_for ?? ""}
                    </td>
                  </>
                )}
                <td className="px-5 py-2 text-gray-600 dark:text-gray-300 whitespace-nowrap">
                  {b.last_success_at ? new Date(b.last_success_at).toLocaleString("en-IN") : "Never"}
                </td>
                <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                  every {b.expected_every_minutes} min
                </td>
                <td className="px-5 py-2">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${STATE[b.status].cls}`}>
                    {STATE[b.status].label}
                  </span>
                  {b.status === "stuck" && (
                    <div className="text-xs text-gray-500 mt-1">
                      {b.unfinished_runs} run(s) started but never finished
                    </div>
                  )}
                  {b.error && <div className="text-xs text-red-600 dark:text-red-400 mt-1">{b.error}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Edit → Save / Cancel, the same on Context, Harness and Guardrails. */
export function EditButtons({
  editing,
  saving,
  onEdit,
  onSave,
  onCancel,
}: {
  editing: boolean;
  saving: boolean;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  if (!editing) {
    return (
      <button
        onClick={onEdit}
        className="shrink-0 text-sm text-eko hover:underline flex items-center gap-1"
      >
        <i className="fas fa-pen text-xs"></i> Edit
      </button>
    );
  }
  return (
    <div className="shrink-0 flex items-center gap-2">
      <button
        onClick={onSave}
        disabled={saving}
        className="px-3 py-1 rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm"
      >
        {saving ? "Saving…" : "Save"}
      </button>
      <button
        onClick={onCancel}
        disabled={saving}
        className="px-3 py-1 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
      >
        Cancel
      </button>
    </div>
  );
}
