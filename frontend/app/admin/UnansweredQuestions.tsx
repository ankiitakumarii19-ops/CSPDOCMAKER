"use client";

/**
 * Data quality → Loop 3: unanswered chat questions (tracker No. 150).
 *
 * Questions the chat could not answer from the Knowledge Base. "Add answer"
 * writes a Knowledge Base entry for it (the same as Admin → Knowledge Base)
 * and removes it from this list; from then on the chat answers everyone
 * who asks. "Dismiss" removes a question that needs no answer.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, KnowledgeMiss } from "../lib/api";

export default function UnansweredQuestions({ onChanged }: { onChanged: () => void }) {
  const [misses, setMisses] = useState<KnowledgeMiss[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<{ id: string; answer: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api
      .knowledgeMisses()
      .then((r) => {
        setMisses(r.misses);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load the questions."));
  }, [version]);

  async function save(m: KnowledgeMiss) {
    if (!open?.answer.trim()) return;
    setBusy(m.id);
    try {
      await api.knowledgeAdd({
        question: m.question,
        phrasings: "",
        keywords: "",
        answer: open.answer.trim(),
        category: "General",
        active: true,
        from_miss: m.id,
      });
      setOpen(null);
      setVersion((v) => v + 1);
      onChanged();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the answer.");
    } finally {
      setBusy("");
    }
  }

  async function dismiss(m: KnowledgeMiss) {
    setBusy(m.id);
    try {
      await api.knowledgeDismissMiss(m.id);
      setVersion((v) => v + 1);
      onChanged();
    } catch (e) {
      setError((e as ApiError).detail || "Could not dismiss it.");
    } finally {
      setBusy("");
    }
  }

  const button = "px-2.5 py-1 rounded text-xs font-semibold disabled:opacity-50";

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white">
          Loop 3 — unanswered chat questions{" "}
          <span className="text-sm font-normal text-gray-500">({misses?.length ?? 0})</span>
        </h3>
        <p className="text-xs text-gray-500">
          Questions the chat could not answer. Add the answer once and the chat answers everyone who
          asks it; it is saved in the Knowledge Base, where you can change it later.
        </p>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="divide-y divide-gray-100 dark:divide-gray-700">
        {misses?.map((m) => (
          <div key={m.id} className="px-5 py-3 text-sm">
            <div className="flex flex-wrap items-start gap-3">
              <div className="flex-1 min-w-[16rem]">
                <div className="text-gray-900 dark:text-white">“{m.question}”</div>
                <div className="text-xs text-gray-500">
                  Asked {m.times_asked}×
                  {m.last_asked_at ? ` · last ${new Date(m.last_asked_at).toLocaleString("en-IN")}` : ""}
                </div>
              </div>
              {open?.id !== m.id && (
                <div className="flex gap-1">
                  <button
                    disabled={busy === m.id}
                    onClick={() => setOpen({ id: m.id, answer: "" })}
                    className={`${button} bg-eko/10 text-eko hover:bg-eko/20`}
                  >
                    <i className="fas fa-plus mr-1"></i>Add answer
                  </button>
                  <button
                    disabled={busy === m.id}
                    onClick={() => dismiss(m)}
                    className={`${button} text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700`}
                  >
                    Dismiss
                  </button>
                </div>
              )}
            </div>
            {open?.id === m.id && (
              <div className="mt-2 space-y-2">
                <textarea
                  autoFocus
                  rows={3}
                  value={open.answer}
                  onChange={(e) => setOpen({ id: m.id, answer: e.target.value })}
                  placeholder="The answer the chat should give"
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
                />
                <div className="flex gap-1">
                  <button
                    disabled={busy === m.id || !open.answer.trim()}
                    onClick={() => save(m)}
                    className={`${button} bg-navy-900 text-white hover:bg-navy-800`}
                  >
                    {busy === m.id ? "Saving…" : "Save to Knowledge Base"}
                  </button>
                  <button
                    onClick={() => setOpen(null)}
                    className={`${button} text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700`}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        {misses && misses.length === 0 && !error && (
          <p className="px-5 py-6 text-sm text-gray-500">Every question asked so far was answered.</p>
        )}
      </div>
    </section>
  );
}
