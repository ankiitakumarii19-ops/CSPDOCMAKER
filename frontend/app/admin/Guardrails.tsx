"use client";

/**
 * Data quality → Guardrails (No. 171): the rules the app never breaks, in
 * words. Admins and Super Admins edit the list; a save also rewrites the
 * chat's answer ("What rules does the app never break?"). The rules
 * themselves are kept by the code — editing the words does not change
 * what the app does.
 */

import { useEffect, useState } from "react";

import { EditButtons } from "./ContextSources";
import { api } from "../lib/api";
import type { ApiError, Guardrail } from "../lib/api";

const input =
  "w-full px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm";

export default function Guardrails({ version = 0 }: { version?: number }) {
  const [rules, setRules] = useState<Guardrail[] | null>(null);
  const [draft, setDraft] = useState<Guardrail[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .qualityTexts()
      .then((r) => setRules(r.guardrails))
      .catch((e) => setError((e as ApiError).detail || "Could not load the guardrails."));
  }, [version]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError("");
    try {
      const r = await api.saveQualityTexts(
        "guardrails",
        draft.filter((g) => g.title.trim())
      );
      setRules(r.guardrails);
      setDraft(null);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const change = (i: number, field: keyof Guardrail, value: string) =>
    setDraft((d) => d && d.map((g, j) => (j === i ? { ...g, [field]: value } : g)));

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">Guardrails — rules the app never breaks</h3>
          <p className="text-xs text-gray-500">
            In words, for people and the chat. The app keeps these rules in its code; editing the
            words does not change what it does.
          </p>
        </div>
        <EditButtons
          editing={draft !== null}
          saving={saving}
          onEdit={() => rules && setDraft(rules.map((g) => ({ ...g })))}
          onSave={save}
          onCancel={() => setDraft(null)}
        />
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {draft ? (
        <div className="p-5 space-y-2">
          {draft.map((g, i) => (
            <div key={i} className="flex gap-2 items-start">
              <span className="pt-1.5 w-6 text-right text-sm text-gray-400 tabular-nums">{i + 1}.</span>
              <input
                className={`${input} md:w-1/3`}
                placeholder="Rule"
                value={g.title}
                maxLength={200}
                onChange={(e) => change(i, "title", e.target.value)}
              />
              <input
                className={input}
                placeholder="Detail (optional)"
                value={g.detail}
                maxLength={1000}
                onChange={(e) => change(i, "detail", e.target.value)}
              />
              <button
                onClick={() => setDraft(draft.filter((_, j) => j !== i))}
                className="pt-1.5 px-2 text-gray-400 hover:text-red-600"
                title="Remove this rule"
              >
                <i className="fas fa-trash text-xs"></i>
              </button>
            </div>
          ))}
          <button
            onClick={() => setDraft([...draft, { title: "", detail: "" }])}
            className="ml-8 text-sm text-eko hover:underline"
          >
            <i className="fas fa-plus text-xs mr-1"></i> Add a rule
          </button>
        </div>
      ) : (
        <ol className="px-5 py-3 space-y-1.5 text-sm list-decimal list-inside">
          {rules?.map((g, i) => (
            <li key={i} className="text-gray-900 dark:text-white">
              <span className="font-medium">{g.title}</span>
              {g.detail && <span className="text-gray-500 dark:text-gray-400"> — {g.detail}</span>}
            </li>
          ))}
          {rules?.length === 0 && <p className="text-gray-500">No guardrails written down.</p>}
        </ol>
      )}
    </section>
  );
}
