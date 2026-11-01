"use client";

/**
 * Data quality → "Upload document" (No. 171). A PDF, Word or text file is
 * read on the server and split into Context, Harness, Guardrails and
 * Knowledge Base by its headings (fixed rules, no AI). Everything found is
 * shown here to check and edit; nothing is saved until "Save". Lines that
 * fit nowhere are listed so nothing disappears unseen.
 */

import { useRef, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, ExtractedTexts, Guardrail } from "../lib/api";

const input =
  "w-full px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm";

type Picked<T> = T & { keep: boolean };

function keep<T>(items: T[]): Picked<T>[] {
  return items.map((x) => ({ ...x, keep: true }));
}

export default function QualityUpload({ onSaved }: { onSaved: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [found, setFound] = useState<ExtractedTexts | null>(null);
  const [context, setContext] = useState<Picked<ExtractedTexts["context"][number]>[]>([]);
  const [harness, setHarness] = useState<Picked<ExtractedTexts["harness"][number]>[]>([]);
  const [rules, setRules] = useState<Picked<Guardrail>[]>([]);
  const [replaceRules, setReplaceRules] = useState(false);
  const [answers, setAnswers] = useState<Picked<ExtractedTexts["knowledge"][number]>[]>([]);

  const read = async (file: File) => {
    setReading(true);
    setError("");
    setDone("");
    try {
      const r = await api.extractQualityTexts(file);
      setFound(r);
      setContext(keep(r.context));
      setHarness(keep(r.harness));
      setRules(keep(r.guardrails));
      setReplaceRules(false);
      setAnswers(keep(r.knowledge));
    } catch (e) {
      setError((e as ApiError).detail || "The file could not be read.");
    } finally {
      setReading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const save = async () => {
    setSaving(true);
    setError("");
    const saved: string[] = [];
    try {
      const pickedContext = context.filter((c) => c.keep);
      const pickedHarness = harness.filter((h) => h.keep);
      const pickedRules = rules.filter((g) => g.keep && g.title.trim());
      const pickedAnswers = answers.filter((a) => a.keep && a.question.trim() && a.answer.trim());

      if (pickedContext.length) {
        const now = (await api.qualityTexts()).context;
        const mine = Object.fromEntries(pickedContext.map((c) => [c.key, c]));
        await api.saveQualityTexts(
          "context",
          now.map((c) => ({ key: c.key, label: mine[c.key]?.label ?? c.label, used_for: mine[c.key]?.used_for ?? c.used_for }))
        );
        saved.push(`${pickedContext.length} context row(s)`);
      }
      if (pickedHarness.length) {
        const now = (await api.qualityHarness()).checks;
        const mine = Object.fromEntries(pickedHarness.map((h) => [h.key, h]));
        await api.saveQualityTexts(
          "harness",
          now.map(({ key, name, watches, how }) => mine[key]
            ? { key, name: mine[key].name, watches: mine[key].watches, how: mine[key].how }
            : { key, name, watches, how })
        );
        saved.push(`${pickedHarness.length} harness check(s)`);
      }
      if (pickedRules.length) {
        const fresh = pickedRules.map(({ title, detail }) => ({ title, detail }));
        let list = fresh;
        if (!replaceRules) {
          const now = (await api.qualityTexts()).guardrails;
          const have = new Set(now.map((g) => g.title.trim().toLowerCase()));
          list = [...now, ...fresh.filter((g) => !have.has(g.title.trim().toLowerCase()))];
        }
        await api.saveQualityTexts("guardrails", list);
        saved.push(`${pickedRules.length} guardrail(s)`);
      }
      for (const a of pickedAnswers) {
        await api.knowledgeAdd({
          question: a.question,
          answer: a.answer,
          category: a.category || "General",
          phrasings: "",
          keywords: "",
          active: true,
        });
      }
      if (pickedAnswers.length) saved.push(`${pickedAnswers.length} Knowledge Base answer(s)`);

      setDone(saved.length ? `Saved: ${saved.join(", ")}.` : "Nothing was chosen, so nothing was saved.");
      setFound(null);
      onSaved();
    } catch (e) {
      setError(
        `${(e as ApiError).detail || "Could not save."}${saved.length ? ` Already saved: ${saved.join(", ")}.` : ""}`
      );
      if (saved.length) onSaved();
    } finally {
      setSaving(false);
    }
  };

  const section = "rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2";
  const tick = "mt-1.5 accent-eko";
  const nothing =
    found &&
    !found.context.length && !found.harness.length && !found.guardrails.length && !found.knowledge.length;

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">Upload document</h3>
          <p className="text-xs text-gray-500 max-w-2xl">
            A PDF, Word (.docx) or text file with headings such as Context, Harness, Guardrails and
            Knowledge Base. What it says is shown below to check before anything is saved.
          </p>
        </div>
        <label className={`shrink-0 px-3 py-1.5 rounded-lg text-sm text-white cursor-pointer ${reading ? "bg-gray-400" : "bg-eko hover:bg-eko-dark"}`}>
          <i className="fas fa-upload text-xs mr-1"></i>
          {reading ? "Reading…" : "Upload document"}
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="hidden"
            disabled={reading}
            onChange={(e) => e.target.files?.[0] && read(e.target.files[0])}
          />
        </label>
      </div>

      {error && <p className="px-5 pb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {done && <p className="px-5 pb-3 text-sm text-green-700 dark:text-green-400">{done}</p>}

      {found && (
        <div className="px-5 pb-5 space-y-4 border-t border-gray-200 dark:border-gray-700 pt-4">
          <p className="text-sm text-gray-700 dark:text-gray-300">
            From <span className="font-medium">{found.file}</span>. Untick anything you do not want, edit
            the words, then Save.
            {!found.headings_found && " No section headings were found, so lines were placed by their shape."}
          </p>
          {nothing && (
            <p className="text-sm text-amber-700 dark:text-amber-400">
              Nothing in the file fitted a section. Add headings (Context, Harness, Guardrails,
              Knowledge Base) and upload it again.
            </p>
          )}

          {context.length > 0 && (
            <div className={section}>
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Context</h4>
              {context.map((c, i) => (
                <div key={c.key} className="flex gap-2 items-start">
                  <input type="checkbox" className={tick} checked={c.keep}
                    onChange={(e) => setContext(context.map((x, j) => j === i ? { ...x, keep: e.target.checked } : x))} />
                  <input className={`${input} md:w-1/4`} value={c.label}
                    onChange={(e) => setContext(context.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
                  <textarea className={input} rows={2} value={c.used_for}
                    onChange={(e) => setContext(context.map((x, j) => j === i ? { ...x, used_for: e.target.value } : x))} />
                </div>
              ))}
            </div>
          )}

          {harness.length > 0 && (
            <div className={section}>
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Harness</h4>
              {harness.map((h, i) => (
                <div key={h.key} className="flex gap-2 items-start">
                  <input type="checkbox" className={tick} checked={h.keep}
                    onChange={(e) => setHarness(harness.map((x, j) => j === i ? { ...x, keep: e.target.checked } : x))} />
                  <input className={`${input} md:w-1/4`} value={h.name}
                    onChange={(e) => setHarness(harness.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                  <textarea className={input} rows={2} value={h.watches} placeholder="What it watches"
                    onChange={(e) => setHarness(harness.map((x, j) => j === i ? { ...x, watches: e.target.value } : x))} />
                  <textarea className={input} rows={2} value={h.how} placeholder="How"
                    onChange={(e) => setHarness(harness.map((x, j) => j === i ? { ...x, how: e.target.value } : x))} />
                </div>
              ))}
            </div>
          )}

          {rules.length > 0 && (
            <div className={section}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Guardrails</h4>
                <div className="flex gap-3 text-xs text-gray-600 dark:text-gray-300">
                  <label className="flex items-center gap-1">
                    <input type="radio" className="accent-eko" checked={!replaceRules} onChange={() => setReplaceRules(false)} />
                    Add to the current list
                  </label>
                  <label className="flex items-center gap-1">
                    <input type="radio" className="accent-eko" checked={replaceRules} onChange={() => setReplaceRules(true)} />
                    Replace the current list
                  </label>
                </div>
              </div>
              {rules.map((g, i) => (
                <div key={i} className="flex gap-2 items-start">
                  <input type="checkbox" className={tick} checked={g.keep}
                    onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, keep: e.target.checked } : x))} />
                  <input className={`${input} md:w-1/3`} value={g.title}
                    onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} />
                  <input className={input} value={g.detail} placeholder="Detail (optional)"
                    onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, detail: e.target.value } : x))} />
                </div>
              ))}
            </div>
          )}

          {answers.length > 0 && (
            <div className={section}>
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white">
                Knowledge Base <span className="font-normal text-xs text-gray-500">— added as new answers</span>
              </h4>
              {answers.map((a, i) => (
                <div key={i} className="flex gap-2 items-start">
                  <input type="checkbox" className={tick} checked={a.keep}
                    onChange={(e) => setAnswers(answers.map((x, j) => j === i ? { ...x, keep: e.target.checked } : x))} />
                  <div className="flex-1 grid gap-1 md:grid-cols-[1fr_2fr_10rem]">
                    <input className={input} value={a.question} placeholder="Question"
                      onChange={(e) => setAnswers(answers.map((x, j) => j === i ? { ...x, question: e.target.value } : x))} />
                    <textarea className={input} rows={2} value={a.answer} placeholder="Answer"
                      onChange={(e) => setAnswers(answers.map((x, j) => j === i ? { ...x, answer: e.target.value } : x))} />
                    <input className={input} value={a.category} placeholder="Category"
                      onChange={(e) => setAnswers(answers.map((x, j) => j === i ? { ...x, category: e.target.value } : x))} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {found.unplaced.length > 0 && (
            <details className={section}>
              <summary className="text-sm text-gray-600 dark:text-gray-300 cursor-pointer">
                {found.unplaced.length} line(s) not placed — not saved
              </summary>
              <ul className="text-xs text-gray-500 space-y-0.5 mt-2 max-h-48 overflow-y-auto">
                {found.unplaced.map((u, i) => <li key={i}>{u}</li>)}
              </ul>
            </details>
          )}

          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={saving || !!nothing}
              className="px-4 py-1.5 rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setFound(null)}
              disabled={saving}
              className="px-4 py-1.5 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
