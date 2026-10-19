"use client";

/**
 * Admin — Knowledge Base (tracker No. 116)
 *
 * What the ask-anything chat answers process questions from ("What is a
 * BCP?", "Why is a request pending?"). There is no AI: a question is matched
 * to the entry whose question, other phrasings or keywords share the most
 * words with it, and that entry's answer is given exactly as written here.
 *
 * Also lists the questions the chat could not answer, most-asked first, so
 * the next entry to write is obvious. Admins and Super Admins.
 */

import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  KnowledgeEntry,
  KnowledgeEntryInput,
  KnowledgeMiss,
  KnowledgeTry,
} from "../lib/api";

const BLANK: KnowledgeEntryInput = {
  question: "",
  phrasings: "",
  keywords: "",
  answer: "",
  category: "General",
  active: true,
  from_miss: null,
};

function errorText(e: unknown, fallback: string): string {
  return (e as ApiError)?.detail || fallback;
}

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

const input =
  "w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-eko";
const card =
  "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";

function Editor({
  start,
  editingId,
  categories,
  onSaved,
  onCancel,
}: {
  start: KnowledgeEntryInput;
  editingId: string | null;
  categories: string[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<KnowledgeEntryInput>(start);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [check, setCheck] = useState<KnowledgeTry | null>(null);

  useEffect(() => setForm(start), [start]);

  const set = (k: keyof KnowledgeEntryInput, v: string | boolean) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    if (!form.question.trim() || !form.answer.trim()) {
      setError("A question and an answer are both needed.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (editingId) await api.knowledgeChange(editingId, form);
      else await api.knowledgeAdd(form);
      onSaved();
    } catch (e) {
      setError(errorText(e, "Could not save the entry."));
    } finally {
      setBusy(false);
    }
  }

  async function tryIt() {
    const q = form.phrasings.split("\n").find((l) => l.trim()) || form.question;
    if (!q.trim()) return;
    try {
      setCheck(await api.knowledgeTry(q));
    } catch (e) {
      setError(errorText(e, "Could not check the question."));
    }
  }

  return (
    <section className={`${card} p-5 space-y-4`}>
      <h3 className="font-semibold text-gray-900 dark:text-white">
        {editingId ? "Change entry" : "New entry"}
      </h3>
      <label className="block">
        <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">Question</span>
        <input
          className={input}
          value={form.question}
          maxLength={300}
          onChange={(e) => set("question", e.target.value)}
          placeholder="e.g. What is a BCP?"
        />
      </label>
      <label className="block">
        <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
          Other ways people ask it — one per line (English, Hinglish or Hindi)
        </span>
        <textarea
          className={input}
          rows={3}
          value={form.phrasings}
          onChange={(e) => set("phrasings", e.target.value)}
          placeholder={"bcp meaning\nbcp kya hai"}
        />
      </label>
      <div className="grid sm:grid-cols-2 gap-4">
        <label className="block">
          <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
            Keywords — comma-separated (optional)
          </span>
          <input
            className={input}
            value={form.keywords}
            maxLength={500}
            onChange={(e) => set("keywords", e.target.value)}
            placeholder="bcp, business correspondent"
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">Category</span>
          <input
            className={input}
            list="kb-categories"
            value={form.category}
            maxLength={100}
            onChange={(e) => set("category", e.target.value)}
          />
          <datalist id="kb-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
      </div>
      <label className="block">
        <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
          Answer — given exactly as written. **bold** and lines starting with “- ” work.
        </span>
        <textarea
          className={input}
          rows={5}
          value={form.answer}
          maxLength={4000}
          onChange={(e) => set("answer", e.target.value)}
        />
      </label>
      <label className="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
        <input
          type="checkbox"
          checked={form.active}
          onChange={(e) => set("active", e.target.checked)}
        />
        In use (switched-off entries are never given as an answer)
      </label>

      {check && (
        <div className="text-xs rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-3 space-y-1">
          <div className="text-gray-500">
            Best matches for that question (answered at {check.answer_at.toFixed(2)} or more):
          </div>
          {check.matches.length === 0 && <div>No entry matches yet.</div>}
          {check.matches.map((m) => (
            <div key={m.id} className="flex justify-between gap-3">
              <span className="text-gray-800 dark:text-gray-200">{m.question}</span>
              <span
                className={`tabular-nums ${
                  m.score >= check.answer_at ? "text-eko-dark dark:text-eko" : "text-gray-500"
                }`}
              >
                {m.score.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}
      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}

      <div className="flex flex-wrap gap-2">
        <button
          onClick={save}
          disabled={busy}
          className="px-4 py-2 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          onClick={tryIt}
          className="px-3 py-2 rounded-lg text-sm border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
          title="See which saved entries the first phrasing (or the question) matches"
        >
          Check matching
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:underline"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}

export default function KnowledgeBase() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [misses, setMisses] = useState<KnowledgeMiss[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<{ id: string | null; start: KnowledgeEntryInput } | null>(
    null
  );

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [list, missed] = await Promise.all([api.knowledgeList(), api.knowledgeMisses()]);
      setEntries(list.entries);
      setMisses(missed.misses);
    } catch (e) {
      setError(errorText(e, "Could not load the Knowledge Base."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const categories = useMemo(
    () => Array.from(new Set(entries.map((e) => e.category))).sort(),
    [entries]
  );
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return entries;
    return entries.filter((e) =>
      [e.question, e.phrasings, e.keywords, e.answer, e.category]
        .join(" ")
        .toLowerCase()
        .includes(f)
    );
  }, [entries, filter]);

  async function remove(e: KnowledgeEntry) {
    if (!window.confirm(`Delete “${e.question}”? The chat will stop giving this answer.`)) return;
    try {
      await api.knowledgeDelete(e.id);
      await load();
    } catch (err) {
      setError(errorText(err, "Could not delete the entry."));
    }
  }

  async function dismiss(m: KnowledgeMiss) {
    try {
      await api.knowledgeDismissMiss(m.id);
      setMisses((all) => all.filter((x) => x.id !== m.id));
    } catch (err) {
      setError(errorText(err, "Could not dismiss the question."));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Knowledge Base</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 max-w-2xl">
            The answers the chat gives to process questions. No AI: a question is matched to the
            entry that shares the most words with it, and the answer is given exactly as written
            here. Questions about a particular CSP are answered from its record instead.
          </p>
        </div>
        <button
          onClick={() => setEditing({ id: null, start: { ...BLANK } })}
          className="px-3 py-2 rounded-lg text-sm font-semibold bg-navy-900 text-white hover:bg-navy-800"
        >
          <i className="fas fa-plus mr-2"></i>Add
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {editing && (
        <Editor
          start={editing.start}
          editingId={editing.id}
          categories={categories}
          onSaved={() => {
            setEditing(null);
            load();
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      {misses.length > 0 && (
        <section className={card}>
          <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold text-gray-900 dark:text-white">
              Questions the chat could not answer ({misses.length})
            </h3>
            <p className="text-xs text-gray-500">Most-asked first. Write an answer, or dismiss.</p>
          </div>
          <ul className="divide-y divide-gray-100 dark:divide-gray-700">
            {misses.map((m) => (
              <li key={m.id} className="px-5 py-3 flex flex-wrap items-center gap-3">
                <div className="flex-1 min-w-[12rem]">
                  <div className="text-sm text-gray-900 dark:text-gray-100">{m.question}</div>
                  <div className="text-xs text-gray-500">
                    Asked {m.times_asked}× · last {when(m.last_asked_at)}
                    {m.last_asked_by ? ` by ${m.last_asked_by}` : ""}
                  </div>
                </div>
                <button
                  onClick={() =>
                    setEditing({
                      id: null,
                      start: { ...BLANK, question: m.question, from_miss: m.id },
                    })
                  }
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-eko hover:bg-eko-dark text-white"
                >
                  Write answer
                </button>
                <button
                  onClick={() => dismiss(m)}
                  className="px-3 py-1.5 rounded-lg text-xs border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"
                >
                  Dismiss
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={card}>
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex flex-wrap items-center gap-3">
          <h3 className="font-semibold text-gray-900 dark:text-white flex-1">
            Entries ({entries.length})
          </h3>
          <input
            className={`${input} max-w-xs`}
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        {loading ? (
          <div className="px-5 py-6 text-sm text-gray-500">
            <i className="fas fa-circle-notch fa-spin mr-2"></i>Loading…
          </div>
        ) : shown.length === 0 ? (
          <div className="px-5 py-6 text-sm text-gray-500">
            {entries.length === 0 ? "No entries yet — press Add to write the first one." : "Nothing matches the filter."}
          </div>
        ) : (
          <ul className="divide-y divide-gray-100 dark:divide-gray-700">
            {shown.map((e) => (
              <li key={e.id} className="px-5 py-3">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="flex-1 min-w-[12rem]">
                    <div className="text-sm font-semibold text-gray-900 dark:text-white">
                      {e.question}
                      {!e.active && (
                        <span className="ml-2 text-xs font-normal text-amber-700 dark:text-amber-400">
                          switched off
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {e.category}
                      {e.updated_by ? ` · last changed by ${e.updated_by}` : ""}
                      {e.updated_at ? `, ${when(e.updated_at)}` : ""}
                    </div>
                    <div className="text-sm text-gray-700 dark:text-gray-300 mt-1 whitespace-pre-wrap">
                      {e.answer}
                    </div>
                  </div>
                  <button
                    onClick={() =>
                      setEditing({
                        id: e.id,
                        start: {
                          question: e.question,
                          phrasings: e.phrasings,
                          keywords: e.keywords,
                          answer: e.answer,
                          category: e.category,
                          active: e.active,
                          from_miss: null,
                        },
                      })
                    }
                    className="px-3 py-1.5 rounded-lg text-xs border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => remove(e)}
                    className="px-3 py-1.5 rounded-lg text-xs border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
