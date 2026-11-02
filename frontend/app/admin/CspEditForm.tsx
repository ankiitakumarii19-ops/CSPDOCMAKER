"use client";

/**
 * Database → Edit (No. 175): one CSP's whole sheet row as a form, read from
 * the sheet when it opens. Save writes only the changed columns to the
 * Google Sheet (and the record), after the same checks the server makes: a
 * CSP Name and mobile cannot be blank, a phone column needs a 10-digit Indian
 * mobile (two in one cell are fine), an email column an email address. If
 * the sheet changed since the form opened, the save is refused for that
 * column rather than overwriting it. Changing the RM moves the CSP to them.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, CspEditColumn } from "../lib/api";

const EMAIL = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/;

/** The same check as the server (csp_editor.check), for instant feedback. */
function problem(c: CspEditColumn, value: string): string {
  const v = value.trim();
  if (c.required && !v) return "Cannot be blank.";
  if (!v) return "";
  if (c.kind === "email" && !EMAIL.test(v)) return "Not an email address.";
  if (c.kind === "phone") {
    const parts = v.split(/[/,;|]+/).map((p) => p.trim()).filter(Boolean);
    const ok = parts.length > 0 && parts.every((p) => {
      const d = p.replace(/\D/g, "");
      return d.length === 10 || (d.length === 11 && d.startsWith("0")) ||
        (d.length === 12 && d.startsWith("91"));
    });
    if (!ok) return "Not a 10-digit Indian mobile number.";
  }
  return "";
}

const isRmColumn = (c: CspEditColumn) => c.field === "rm_name";

export default function CspEditForm({
  cspId,
  onClose,
  onSaved,
}: {
  cspId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [columns, setColumns] = useState<CspEditColumn[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [where, setWhere] = useState("");
  const [error, setError] = useState("");
  const [serverProblems, setServerProblems] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .databaseEditForm(cspId)
      .then((f) => {
        setColumns(f.columns);
        setValues(Object.fromEntries(f.columns.map((c) => [c.column, c.value])));
        setWhere(`${f.tab}, row ${f.row_number}`);
      })
      .catch((e) => setError((e as ApiError).detail || "Could not open the form."));
  }, [cspId]);

  const changed = (columns ?? []).filter((c) => (values[c.column] ?? "").trim() !== c.value.trim());
  const problems = Object.fromEntries(
    changed.map((c) => [c.column, problem(c, values[c.column] ?? "")]).filter(([, p]) => p)
  );
  const rmChange = changed.find(isRmColumn);

  const save = async () => {
    if (!columns || changed.length === 0 || Object.keys(problems).length) return;
    if (rmChange && !window.confirm(
      `Changing the RM to "${values[rmChange.column]}" moves this CSP to that RM. Continue?`
    )) return;
    setSaving(true);
    setError("");
    setServerProblems({});
    try {
      await api.databaseSave(cspId, {
        changes: Object.fromEntries(changed.map((c) => [c.column, values[c.column]])),
        seen: Object.fromEntries(changed.map((c) => [c.column, c.value])),
      });
      onSaved();
    } catch (e) {
      const err = e as ApiError;
      const data = err.data as { message?: string; problems?: Record<string, string> } | undefined;
      setServerProblems(data?.problems ?? {});
      setError(data?.message || err.detail || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const input =
    "w-full px-2 py-1.5 rounded border bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white disabled:bg-gray-100 dark:disabled:bg-gray-800 disabled:text-gray-500";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose}></div>
      <aside className="relative w-full max-w-2xl h-full overflow-y-auto bg-white dark:bg-gray-800 shadow-xl pb-[env(safe-area-inset-bottom)]">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 px-4 sm:px-6 py-4 pt-[calc(1rem+env(safe-area-inset-top))] sm:pt-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">Edit {cspId}</h3>
            <p className="text-xs text-gray-500">
              Saved to the Google Sheet{where && ` (${where})`}. {changed.length} change{changed.length === 1 ? "" : "s"}.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={save}
              disabled={saving || changed.length === 0 || Object.keys(problems).length > 0}
              className="px-4 py-1.5 rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm"
            >
              {saving ? "Saving…" : "Save to sheet"}
            </button>
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700">
              Cancel
            </button>
          </div>
        </div>
        <div className="px-6 py-5 space-y-3">
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          {!columns && !error && <p className="text-sm text-gray-500">Reading the sheet…</p>}
          {columns?.map((c) => {
            const wrong = problems[c.column] || serverProblems[c.column];
            const isChanged = (values[c.column] ?? "").trim() !== c.value.trim();
            return (
              <div key={c.column}>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-0.5">
                  {c.column}
                  {c.required && <span className="text-red-500"> *</span>}
                  {c.locked && <span className="text-gray-400"> — cannot be changed here</span>}
                  {isChanged && <span className="text-eko"> — changed (was &ldquo;{c.value || "blank"}&rdquo;)</span>}
                </label>
                <input
                  type={c.kind === "email" ? "email" : c.kind === "phone" ? "tel" : "text"}
                  value={values[c.column] ?? ""}
                  disabled={c.locked}
                  onChange={(e) => setValues({ ...values, [c.column]: e.target.value })}
                  className={`${input} ${wrong ? "border-red-400" : isChanged ? "border-eko" : "border-gray-300 dark:border-gray-600"}`}
                />
                {wrong && <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">{wrong}</p>}
                {isRmColumn(c) && isChanged && (
                  <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
                    Changing the RM moves this CSP to the RM named here.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
