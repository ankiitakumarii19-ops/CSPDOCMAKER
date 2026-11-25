"use client";

/**
 * Document Templates → Versions & test (No. 240, SaaS upgrade Stage 5)
 *
 *  * Test on a CSP: makes this document for one CSP exactly as the real path
 *    does and downloads it — nothing is stored, sent or counted.
 *  * Earlier versions: kept before every new upload, wording edit and
 *    restore; download one, or put it back (what is live now is kept first,
 *    so a restore can itself be undone).
 *  * Category and the mandatory fields (every mapped field must have a value
 *    or the document is not made).
 *
 * "Publish" is Activate on this screen: a new template stays switched off
 * until it is mapped, tested and activated.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, TemplateDetail, TemplateSummary, TemplateVersion } from "../lib/api";

const REASON: Record<string, string> = {
  new_upload: "before a new file was uploaded",
  wording_edit: "before the wording was edited",
  restore: "before an earlier version was put back",
};

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export default function TemplateVersions({
  template,
  summary,
  onChanged,
}: {
  template: TemplateDetail;
  summary?: TemplateSummary;
  onChanged: (message: string) => void | Promise<void>;
}) {
  const [versions, setVersions] = useState<TemplateVersion[] | null>(null);
  const [cspId, setCspId] = useState("");
  const [category, setCategory] = useState(summary?.category ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .templateVersions(template.code)
      .then((v) => alive && setVersions(v.versions))
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the versions."));
    return () => {
      alive = false;
    };
  }, [template.code, template.version]);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (e) {
      setError((e as ApiError).detail || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const test = (sample = false) =>
    run(async () => {
      const f = await api.testTemplate(template.code, sample ? "SAMPLE" : cspId.trim());
      save(f.blob, f.name);
      setMessage(
        sample
          ? `Made ${f.name} for a made-up CSP (Asha Verma) — downloaded. Nothing was stored or sent.`
          : `Made ${f.name} for ${cspId.trim()} — downloaded. Nothing was stored or sent.`
      );
    });

  const restore = (v: TemplateVersion) => {
    if (!window.confirm(`Put version ${v.version} back? What is live now (v${template.version}) is kept, so you can undo this.`))
      return;
    run(async () => {
      const r = await api.restoreTemplateVersion(template.code, v.id);
      await onChanged(
        r.active
          ? `Version ${r.restored_version} is back, as v${r.version}, and in use.`
          : `Version ${r.restored_version} is back, as v${r.version}. It is switched off — check its fields, test it, then Activate.`
      );
    });
  };

  const saveCategory = () =>
    run(async () => {
      await api.updateTemplate(template.code, { category });
      await onChanged(category.trim() ? `Category set to ${category.trim()}.` : "Category removed.");
    });

  return (
    <div className="p-5 space-y-6">
      {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div role="status" className="text-sm text-eko-dark dark:text-eko">{message}</div>}

      <section className="space-y-2">
        <h4 className="text-sm font-bold text-gray-900 dark:text-white">Test on a CSP</h4>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Makes this document (v{template.version}) for one CSP, exactly as it would be sent, and downloads it. Nothing
          is stored, sent or counted. Works while the template is switched off too — test, then Activate.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={cspId}
            onChange={(e) => setCspId(e.target.value)}
            placeholder="CSP code, e.g. 1A000101"
            aria-label="CSP code to test with"
            className="sm:w-64 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm"
          />
          <button
            type="button"
            disabled={busy || !cspId.trim()}
            onClick={() => test()}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
          >
            {busy ? "Working…" : "Make test document"}
          </button>
          {/* No. 247: no CSPs yet? A made-up one, never stored. */}
          <button
            type="button"
            disabled={busy}
            onClick={() => test(true)}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Test with a made-up CSP
          </button>
        </div>
      </section>

      <section className="space-y-2">
        <h4 className="text-sm font-bold text-gray-900 dark:text-white">Category</h4>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={category}
            maxLength={80}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="e.g. Certificates"
            aria-label="Category"
            className="sm:w-64 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm"
          />
          <button
            type="button"
            disabled={busy || category === (summary?.category ?? "")}
            onClick={saveCategory}
            className="px-4 py-2 rounded-lg text-sm border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Save category
          </button>
        </div>
      </section>

      {summary?.required_fields && summary.required_fields.length > 0 && (
        <section className="space-y-2">
          <h4 className="text-sm font-bold text-gray-900 dark:text-white">Mandatory fields</h4>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Every field this document prints must have a value, or it is not made (the CSP is asked for what is
            missing). Change them on the Fields tab.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {summary.required_fields.map((f) => (
              <span key={f} className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 font-mono">
                {f}
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h4 className="text-sm font-bold text-gray-900 dark:text-white">Earlier versions</h4>
        {!versions && !error && <div className="text-sm text-gray-500">Loading…</div>}
        {versions && versions.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            None yet. The version in use is kept here the first time it is changed.
          </p>
        )}
        {versions && versions.length > 0 && (
          <ul className="divide-y divide-gray-100 dark:divide-gray-700 rounded-lg border border-gray-200 dark:border-gray-700">
            {versions.map((v) => (
              <li key={v.id} className="px-3 py-2 flex flex-col sm:flex-row sm:items-center gap-2">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-900 dark:text-white">
                    v{v.version} <span className="text-gray-500">· kept {REASON[v.reason] ?? v.reason}</span>
                    {v.was_active && <span className="ml-2 text-xs text-green-700 dark:text-green-300">was in use</span>}
                  </div>
                  <div className="text-xs text-gray-500">
                    {v.saved_at ? new Date(v.saved_at).toLocaleString("en-IN") : ""}
                    {v.saved_by ? ` · ${v.saved_by}` : ""} · {Math.round(v.file_size / 1024)} KB
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        const f = await api.templateVersionFile(template.code, v.id);
                        save(f.blob, f.name);
                      })
                    }
                    className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Download
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => restore(v)}
                    className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Put back
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
