"use client";

/**
 * Database — every CSP's complete record in one place (tracker No. 47 / 89).
 *
 * RM, Admin and Super Admin (No. 104). One row per CSP; open a row to see every
 * column of the CSP sheet, what the app records about them, their photo
 * (as obtained, and the passport version on the documents) and every
 * stored PDF with its versions. Since No. 175 a CSP can be edited from here
 * (CspEditForm — written to the sheet; RMs their own CSPs) and its edit
 * history is shown.
 */

import { useEffect, useState } from "react";

import CspEditForm from "./CspEditForm";

import CspPhoto from "../components/CspPhoto";
import { api } from "../lib/api";
import type { ApiError, DatabaseRecord, DatabaseRow } from "../lib/api";

const PAGE = 50;

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function kb(bytes: number): string {
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function Database() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<DatabaseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [openId, setOpenId] = useState<string | null>(null);
  const [record, setRecord] = useState<DatabaseRecord | null>(null);
  const [photoUrls, setPhotoUrls] = useState<Record<string, string>>({});
  const [recordError, setRecordError] = useState("");
  // The edit form (No. 175), and a counter to read the record again.
  const [editing, setEditing] = useState(false);
  const [reload, setReload] = useState(0);

  // First page on arrival.
  useEffect(() => {
    let off = false;
    api
      .databaseList("", 0, PAGE)
      .then((r) => {
        if (off) return;
        setRows(r.items);
        setTotal(r.total);
      })
      .catch((e) => !off && setError((e as ApiError).detail || "Could not load the database."))
      .finally(() => !off && setLoading(false));
    return () => {
      off = true;
    };
  }, []);

  async function search(offset = 0) {
    setLoading(true);
    setError("");
    try {
      const r = await api.databaseList(query.trim(), offset, PAGE);
      setRows((prev) => (offset === 0 ? r.items : [...prev, ...r.items]));
      setTotal(r.total);
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the database.");
    } finally {
      setLoading(false);
    }
  }

  // The open record, and its photos as images the browser can show.
  useEffect(() => {
    if (!openId) return;
    let off = false;
    const made: string[] = [];
    api
      .databaseRecord(openId)
      .then(async (rec) => {
        if (off) return;
        setRecord(rec);
        setRecordError("");
        const urls: Record<string, string> = {};
        for (const p of rec.photos) {
          try {
            const blob = await api.databaseFile(rec.csp_id, `photo/${p.kind}`);
            const url = URL.createObjectURL(blob);
            made.push(url);
            urls[p.kind] = url;
          } catch {
            // The record still shows; that photo just has no preview.
          }
        }
        if (!off) setPhotoUrls(urls);
      })
      .catch((e) => !off && setRecordError((e as ApiError).detail || "Could not open this record."));
    return () => {
      off = true;
      made.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [openId, reload]);

  function toggle(cspId: string) {
    setRecord(null);
    setPhotoUrls({});
    setRecordError("");
    setOpenId((cur) => (cur === cspId ? null : cspId));
  }

  async function openPdf(cspId: string, documentId: string) {
    // Opened first, filled after: a window opened after waiting is blocked.
    const tab = window.open("", "_blank");
    try {
      const blob = await api.databaseFile(cspId, `documents/${documentId}`);
      const url = URL.createObjectURL(blob);
      if (tab) tab.location.replace(url);
      else window.open(url, "_blank");
    } catch (e) {
      tab?.close();
      setRecordError((e as ApiError).detail || "Could not open the document.");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Database</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Every CSP&apos;s complete record: all sheet columns, the photo and the
          stored documents. Open a CSP to edit it — saved straight to the sheet (RMs: their own
          CSPs).
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          search(0);
        }}
        className="flex gap-2"
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by CSP code, name, district, state or RM"
          className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 bg-eko hover:bg-eko-dark text-white text-sm font-medium rounded-lg shadow-sm disabled:opacity-50"
        >
          <i className="fas fa-magnifying-glass mr-2 text-xs" />
          Search
        </button>
      </form>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          <i className="fas fa-circle-exclamation mr-2" />
          {error}
        </div>
      )}

      {/* Phones (No. 176): one card per CSP, a tap opens it. */}
      <div className="sm:hidden space-y-2">
        {rows.map((r) => (
          <button
            key={r.csp_id}
            onClick={() => toggle(r.csp_id)}
            className="w-full text-left rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-sm font-semibold text-gray-900 dark:text-white">{r.csp_code || r.csp_id}</span>
              {r.level && (
                <span className="px-2 py-0.5 rounded text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">{r.level}</span>
              )}
            </div>
            <div className="text-sm text-gray-800 dark:text-gray-200 mt-0.5">{show(r.name)}</div>
            <div className="text-sm text-gray-500">
              {[r.district, r.rm_name && `RM ${r.rm_name}`].filter(Boolean).join(" · ") || "—"}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {r.documents.length ? r.documents.join(", ") : "No documents yet"}
            </div>
          </button>
        ))}
        {!loading && rows.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-gray-500">No CSPs match.</p>
        )}
      </div>

      {/* Tablets and up: the table; it scrolls inside its box with the code
          and name kept in view (No. 176). */}
      <div className="hidden sm:block rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-900 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="text-left px-4 py-3 sticky left-0 z-10 min-w-[7.5rem] bg-gray-50 dark:bg-gray-900">CSP Code</th>
              <th className="text-left px-4 py-3 sticky left-[7.5rem] z-10 min-w-[10rem] bg-gray-50 dark:bg-gray-900">Name</th>
              <th className="text-left px-4 py-3">Level</th>
              <th className="text-left px-4 py-3">District</th>
              <th className="text-left px-4 py-3">State</th>
              <th className="text-left px-4 py-3">RM</th>
              <th className="text-left px-4 py-3">Photo</th>
              <th className="text-left px-4 py-3">Documents</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {rows.map((r) => (
              <tr
                key={r.csp_id}
                onClick={() => toggle(r.csp_id)}
                className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                  openId === r.csp_id ? "bg-gray-50 dark:bg-gray-700/50" : ""
                }`}
              >
                <td className="px-4 py-3 font-medium text-gray-900 dark:text-white sticky left-0 z-10 min-w-[7.5rem] bg-white dark:bg-gray-800">
                  {r.csp_code || r.csp_id}
                </td>
                <td className="px-4 py-3 text-gray-700 dark:text-gray-300 sticky left-[7.5rem] z-10 min-w-[10rem] bg-white dark:bg-gray-800">{show(r.name)}</td>
                <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{show(r.level)}</td>
                <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{show(r.district)}</td>
                <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{show(r.state)}</td>
                <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{show(r.rm_name)}</td>
                <td className="px-4 py-3">
                  {r.photo.length ? (
                    <CspPhoto cspId={r.csp_id} className="w-[35px] h-[45px]" />
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                  {r.documents.length ? r.documents.join(", ") : <span className="text-gray-400">None yet</span>}
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                  No CSPs match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-gray-500">
        <span>
          {loading ? "Loading…" : `Showing ${rows.length} of ${total}`}
        </span>
        {rows.length < total && (
          <button
            onClick={() => search(rows.length)}
            disabled={loading}
            className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Show more
          </button>
        )}
      </div>

      {/* The record: full screen below 1024px (No. 176), its Close button
          at the top; in the page from there up. */}
      {openId && (
        <div className="fixed inset-0 z-40 overflow-y-auto bg-white dark:bg-gray-800 px-4 sm:px-6 pt-[calc(1.25rem+env(safe-area-inset-top))] pb-[calc(6rem+env(safe-area-inset-bottom))] lg:static lg:z-auto lg:p-5 lg:rounded-xl lg:border lg:border-gray-200 lg:dark:border-gray-700 space-y-6">
          {recordError && (
            <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
              <i className="fas fa-circle-exclamation mr-2" />
              {recordError}
            </div>
          )}
          {!record && !recordError && <p className="text-sm text-gray-500">Loading…</p>}
          {record && (
            <>
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                    {show(record.name)}
                  </h3>
                  <p className="text-sm text-gray-500">
                    {record.csp_id} {record.level && <>&bull; {record.level}</>}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {record.can_edit ? (
                    <button
                      onClick={() => setEditing(true)}
                      className="px-3 py-1.5 rounded-lg bg-eko hover:bg-eko-dark text-white text-sm"
                    >
                      <i className="fas fa-pen text-xs mr-1"></i> Edit
                    </button>
                  ) : (
                    <span className="text-xs text-gray-500">Another RM&apos;s CSP — view only</span>
                  )}
                  <button
                    onClick={() => toggle(record.csp_id)}
                    className="text-sm text-gray-500 hover:underline"
                  >
                    Close
                  </button>
                </div>
              </div>
              {editing && (
                <CspEditForm
                  cspId={record.csp_id}
                  onClose={() => setEditing(false)}
                  onSaved={() => {
                    setEditing(false);
                    setReload((n) => n + 1);
                  }}
                />
              )}

              <section>
                <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Photo</h4>
                {record.photos.length === 0 ? (
                  <p className="text-sm text-gray-500">No photo stored yet.</p>
                ) : (
                  <div className="flex gap-6 flex-wrap">
                    {(["passport", "original"] as const).map((kind) => {
                      const p = record.photos.find((x) => x.kind === kind);
                      if (!p) return null;
                      return (
                        <figure key={kind} className="text-center">
                          {photoUrls[kind] ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={photoUrls[kind]}
                              alt={`${kind} photo of ${record.csp_id}`}
                              className="h-40 w-auto rounded border border-gray-200 dark:border-gray-700 bg-white"
                            />
                          ) : (
                            <div className="h-40 w-32 rounded border border-gray-200 dark:border-gray-700 flex items-center justify-center text-xs text-gray-400">
                              Loading…
                            </div>
                          )}
                          <figcaption className="text-xs text-gray-500 mt-1">
                            {kind === "passport" ? "On documents (35 × 45 mm)" : "As obtained"} · {kb(p.size)}
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                )}
              </section>

              <section>
                <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Documents</h4>
                {record.documents.length === 0 ? (
                  <p className="text-sm text-gray-500">No documents stored yet.</p>
                ) : (
                  <div className="space-y-2">
                    {record.documents.map((d) => (
                      <div key={d.document_type} className="flex items-center gap-3 flex-wrap text-sm">
                        <span className="font-medium text-gray-900 dark:text-white w-48">{d.label}</span>
                        {d.versions.map((v, i) => (
                          <button
                            key={v.id}
                            onClick={() => openPdf(record.csp_id, v.id)}
                            className={`px-3 py-1.5 rounded-lg text-xs ${
                              i === 0
                                ? "bg-eko hover:bg-eko-dark text-white font-medium"
                                : "border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                            }`}
                            title={`${v.filename} · ${kb(v.size)}`}
                          >
                            <i className="fas fa-file-pdf mr-1" /> v{v.version}
                            {i === 0 ? " (latest)" : ""}
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {[
                { title: "CSP sheet columns", fields: record.sheet },
                { title: "Recorded by the app", fields: record.app },
              ].map((group) => (
                <section key={group.title}>
                  <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
                    {group.title}
                  </h4>
                  <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3 text-sm">
                    {group.fields.map((f) => (
                      <div key={f.key} className="border-b border-gray-100 dark:border-gray-700 pb-1">
                        <dt className="text-xs text-gray-500">{f.label}</dt>
                        <dd className="text-gray-900 dark:text-white break-words">{show(f.value)}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ))}

              {/* Every change, who made it and when (No. 175). */}
              <section>
                <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
                  Edit history
                </h4>
                {(record.edit_history ?? []).length === 0 ? (
                  <p className="text-sm text-gray-500">No edits made in the portal yet.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
                        <tr>
                          <th className="pr-4 py-1">When</th>
                          <th className="pr-4 py-1">Who</th>
                          <th className="pr-4 py-1">Field</th>
                          <th className="pr-4 py-1">Old value</th>
                          <th className="pr-4 py-1">New value</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                        {record.edit_history!.map((h, i) => (
                          <tr key={i} className="align-top">
                            <td className="pr-4 py-1 text-gray-500 whitespace-nowrap">
                              {h.at ? new Date(h.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                            </td>
                            <td className="pr-4 py-1 text-gray-700 dark:text-gray-300">
                              {h.by}
                              <span className="block text-xs text-gray-400">
                                {h.via === "sheets_tab" ? "Sheets tab" : "Database page"}
                              </span>
                            </td>
                            <td className="pr-4 py-1 text-gray-700 dark:text-gray-300">{h.column}</td>
                            <td className="pr-4 py-1 text-gray-500 break-words">{h.old || "—"}</td>
                            <td className="pr-4 py-1 text-gray-900 dark:text-white break-words">{h.new || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </div>
  );
}
