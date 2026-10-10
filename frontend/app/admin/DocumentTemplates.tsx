"use client";

/**
 * Admin — Document Templates
 *
 * Upload a .docx, say what fills each placeholder, edit the wording, and
 * activate it. A template decides what every CSP's official documents say,
 * so two refusals are enforced by the backend and surfaced here rather than
 * hidden: a template with an unmapped placeholder cannot be activated, and
 * an edit that deletes a placeholder is rejected.
 *
 * Editing the wording rewrites the text run by run inside the existing file.
 * The layout, text boxes, photo frame and embedded signature are untouched.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  TemplateDetail,
  TemplateSummary,
} from "../lib/api";

export default function DocumentTemplates() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [selected, setSelected] = useState<TemplateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [showUpload, setShowUpload] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);

  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<"fields" | "wording">("fields");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listTemplates();
      setTemplates(data.templates);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load templates.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function open(code: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const detail = await api.getTemplate(code);
      setSelected(detail);
      setMapping(
        Object.fromEntries(detail.placeholders.map((p) => [p.text, p.field]))
      );
      setEdits({});
      setTab("fields");
    } catch (e) {
      setError((e as ApiError).detail || "Could not open that template.");
    } finally {
      setBusy(false);
    }
  }

  async function saveMapping() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await api.updateTemplate(selected.code, { placeholder_map: mapping });
      setNotice("Field mapping saved.");
      await open(selected.code);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the mapping.");
    } finally {
      setBusy(false);
    }
  }

  async function saveWording() {
    if (!selected || Object.keys(edits).length === 0) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api.editTemplateContent(selected.code, edits);
      setSelected(updated);
      setEdits({});
      setNotice(`Wording saved — now version ${updated.version}.`);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the wording.");
    } finally {
      setBusy(false);
    }
  }

  async function setActive(active: boolean) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await api.updateTemplate(selected.code, { active });
      setNotice(active ? "Template activated." : "Template deactivated.");
      await open(selected.code);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not change that.");
    } finally {
      setBusy(false);
    }
  }

  async function upload() {
    if (!newFile || !newCode.trim() || !newName.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.uploadTemplate(
        newCode.trim(),
        newName.trim(),
        newFile
      );
      setNotice(result.message);
      setShowUpload(false);
      setNewCode("");
      setNewName("");
      setNewFile(null);
      await load();
      await open(result.code);
    } catch (e) {
      setError((e as ApiError).detail || "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  const unmapped = selected
    ? selected.placeholders.filter((p) => !mapping[p.text]).length
    : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">
            Document Templates
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            The documents this system can issue. Upload a .docx, map its
            placeholders, then activate it.
          </p>
        </div>
        <button
          onClick={() => setShowUpload((v) => !v)}
          className="px-4 py-2 bg-eko hover:bg-eko-dark text-white text-sm font-medium rounded-lg shadow-sm flex items-center gap-2"
        >
          <i className="fas fa-plus text-xs" /> Add Template
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          <i className="fas fa-circle-exclamation mr-2" />
          {error}
        </div>
      )}
      {notice && (
        <div className="px-4 py-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-sm text-green-700 dark:text-green-300">
          <i className="fas fa-circle-check mr-2" />
          {notice}
        </div>
      )}

      {/* Upload form */}
      {showUpload && (
        <div className="p-5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 space-y-4">
          <h3 className="font-bold text-gray-900 dark:text-white">
            Upload a new document template
          </h3>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Code
              </label>
              <input
                value={newCode}
                onChange={(e) => setNewCode(e.target.value)}
                placeholder="APPOINTMENT_LETTER"
                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Display name
              </label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Appointment Letter"
                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                File (.docx)
              </label>
              <input
                type="file"
                accept=".docx"
                onChange={(e) => setNewFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-gray-600 dark:text-gray-400 file:mr-3 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:text-sm file:bg-gray-100 dark:file:bg-gray-700 dark:file:text-gray-200"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={upload}
              disabled={busy || !newFile || !newCode.trim() || !newName.trim()}
              className="px-4 py-2 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium rounded-lg"
            >
              {busy ? "Reading the file…" : "Upload"}
            </button>
            <button
              onClick={() => setShowUpload(false)}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:underline"
            >
              Cancel
            </button>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Placeholders are read out of the file. Anything matching a known
            field name is mapped for you; the rest you map below. Nothing is
            issued from a template until every placeholder has a field.
          </p>
        </div>
      )}

      {/* The list */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead className="bg-gray-50 dark:bg-gray-900/40 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-3 font-semibold">Document</th>
              <th className="px-4 py-3 font-semibold">Code</th>
              <th className="px-4 py-3 font-semibold text-center">Placeholders</th>
              <th className="px-4 py-3 font-semibold text-center">Version</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && templates.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                  No templates yet.
                </td>
              </tr>
            )}
            {templates.map((t) => (
              <tr
                key={t.code}
                className={`hover:bg-gray-50 dark:hover:bg-gray-700/40 cursor-pointer ${
                  selected?.code === t.code ? "bg-gray-50 dark:bg-gray-700/40" : ""
                }`}
                onClick={() => open(t.code)}
              >
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900 dark:text-white">
                    {t.name}
                  </div>
                  {t.is_builtin && (
                    <span className="text-[11px] text-gray-500">supplied</span>
                  )}
                </td>
                <td className="px-4 py-3 text-sm font-mono text-gray-600 dark:text-gray-400">
                  {t.code}
                </td>
                <td className="px-4 py-3 text-center text-sm tabular-nums">
                  {t.error ? (
                    <span className="text-red-600" title={t.error}>
                      file missing
                    </span>
                  ) : (
                    <>
                      {t.placeholder_count}
                      {t.unmapped_count > 0 && (
                        <span className="ml-2 text-amber-600 font-medium">
                          {t.unmapped_count} unmapped
                        </span>
                      )}
                    </>
                  )}
                </td>
                <td className="px-4 py-3 text-center text-sm tabular-nums text-gray-600 dark:text-gray-400">
                  v{t.version}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                      t.active
                        ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                        : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                    }`}
                  >
                    {t.active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-eko text-sm font-medium">Configure</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* The editor */}
      {selected && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
          <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between flex-wrap gap-3">
            <div>
              <h3 className="font-bold text-gray-900 dark:text-white">
                {selected.name}
              </h3>
              <p className="text-xs text-gray-500">
                {selected.code} · v{selected.version}
                {selected.photo_marker && " · carries a photograph"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {selected.active ? (
                <button
                  onClick={() => setActive(false)}
                  disabled={busy}
                  className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  Deactivate
                </button>
              ) : (
                <button
                  onClick={() => setActive(true)}
                  disabled={busy || unmapped > 0}
                  title={
                    unmapped > 0
                      ? `${unmapped} placeholder(s) have no field — the document would print a blank there`
                      : undefined
                  }
                  className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-40 text-white font-medium"
                >
                  Activate
                </button>
              )}
              <button
                onClick={() => setSelected(null)}
                className="text-gray-400 hover:text-gray-600 px-2"
              >
                <i className="fas fa-times" />
              </button>
            </div>
          </div>

          <div className="px-5 pt-4 flex gap-1">
            {(["fields", "wording"] as const).map((key) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`px-4 py-2 text-sm font-medium rounded-t-lg ${
                  tab === key
                    ? "bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white"
                    : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                }`}
              >
                {key === "fields" ? "Fields" : "Wording"}
              </button>
            ))}
          </div>

          {/* Fields tab */}
          {tab === "fields" && (
            <div className="p-5 space-y-4">
              {unmapped > 0 && (
                <div className="px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm text-amber-800 dark:text-amber-300">
                  {unmapped} placeholder{unmapped === 1 ? "" : "s"} still need a
                  field. This template cannot be activated until every one has
                  one — otherwise the document prints a blank there.
                </div>
              )}
              <div className="space-y-2">
                {selected.placeholders.map((p) => (
                  <div
                    key={p.text}
                    className="grid md:grid-cols-2 gap-3 items-center"
                  >
                    <div className="text-sm">
                      <code className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-900 text-gray-800 dark:text-gray-200">
                        &ldquo;{p.text}&rdquo;
                      </code>
                      {p.guessed && mapping[p.text] && (
                        <span className="ml-2 text-[11px] text-gray-500">
                          matched automatically
                        </span>
                      )}
                    </div>
                    <select
                      value={mapping[p.text] || ""}
                      onChange={(e) =>
                        setMapping((m) => ({ ...m, [p.text]: e.target.value }))
                      }
                      className={`w-full px-3 py-2 text-sm rounded-lg border bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko ${
                        mapping[p.text]
                          ? "border-gray-300 dark:border-gray-600"
                          : "border-amber-400"
                      }`}
                    >
                      <option value="">— choose what fills this —</option>
                      {selected.fields.map((f) => (
                        <option key={f.field} value={f.field}>
                          {f.label}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              <button
                onClick={saveMapping}
                disabled={busy}
                className="px-4 py-2 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium rounded-lg"
              >
                Save mapping
              </button>
            </div>
          )}

          {/* Wording tab */}
          {tab === "wording" && (
            <div className="p-5 space-y-4">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Editing here changes only the words. The layout, text boxes,
                photo frame and signature are left exactly as they are. A
                placeholder cannot be deleted — that would stop a value
                printing on every future document.
              </p>
              <div className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
                {selected.paragraphs.map((p) => (
                  <div key={p.index} className="flex gap-2 items-start">
                    <span className="text-[11px] text-gray-400 w-8 pt-2 text-right tabular-nums shrink-0">
                      {p.index}
                    </span>
                    <textarea
                      value={edits[String(p.index)] ?? p.text}
                      onChange={(e) =>
                        setEdits((d) => ({
                          ...d,
                          [String(p.index)]: e.target.value,
                        }))
                      }
                      rows={Math.min(4, Math.ceil(p.text.length / 90) || 1)}
                      className={`flex-grow px-3 py-2 text-sm rounded-lg border bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko resize-y ${
                        p.has_placeholder
                          ? "border-eko/40"
                          : "border-gray-300 dark:border-gray-600"
                      }`}
                    />
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={saveWording}
                  disabled={busy || Object.keys(edits).length === 0}
                  className="px-4 py-2 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium rounded-lg"
                >
                  Save wording
                </button>
                {Object.keys(edits).length > 0 && (
                  <span className="text-xs text-gray-500">
                    {Object.keys(edits).length} paragraph
                    {Object.keys(edits).length === 1 ? "" : "s"} changed
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
