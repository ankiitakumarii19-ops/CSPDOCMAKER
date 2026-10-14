"use client";

/**
 * The sheets behind the system. A Super Admin sees every sheet and decides
 * which are read; an Admin or RM sees and edits the CSP tabs only — never
 * the access sheet (No. 104, enforced by the server, not only here).
 *
 * Every other screen in this product shows records that came from a sheet.
 * This one shows the sheet: the tabs it has, the rows in them, and lets a
 * Super Admin correct, add or remove a row without leaving the application.
 *
 * Three things the design is deliberate about.
 *
 * Row numbers are the spreadsheet's own. An edit addresses the row a
 * person can see in Google Sheets, not a position in this table — which
 * would move the moment anyone else inserted a row.
 *
 * Tabs are whatever the spreadsheet has at this moment. The list is read
 * on every load, so a tab created or deleted in Google Sheets shows up
 * here without anything having to be told about it.
 *
 * Deleting is the only thing in this product that destroys something
 * nothing here can bring back. So it asks, it names the CSP it is about
 * to remove, and afterwards it shows what it deleted — because the only
 * recovery is somebody typing it back or using the spreadsheet's history.
 */

import { useCallback, useEffect, useState } from "react";

import CspPhoto from "../components/CspPhoto";
import { api } from "../lib/api";
import type { ApiError, SheetSource, SheetTabData } from "../lib/api";
import { withBase } from "../lib/basePath";

export default function Sheets({ canManage = false }: { canManage?: boolean }) {
  const [sources, setSources] = useState<SheetSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [open, setOpen] = useState<{ source: SheetSource; tab: string } | null>(
    null
  );
  const [data, setData] = useState<SheetTabData | null>(null);
  const [loadingRows, setLoadingRows] = useState(false);

  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [adding, setAdding] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deleted, setDeleted] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [registering, setRegistering] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSources((await api.listSheets()).sheets);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the sheets.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openTab = useCallback(async (source: SheetSource, tab: string) => {
    setOpen({ source, tab });
    setData(null);
    setEditing(null);
    setAdding(false);
    setConfirmDelete(null);
    setDeleted(null);
    setLoadingRows(true);
    setError("");
    try {
      setData(await api.readSheetTab(source.id, tab));
    } catch (e) {
      setError((e as ApiError).detail || `Could not read ${tab}.`);
    } finally {
      setLoadingRows(false);
    }
  }, []);

  async function refreshRows() {
    if (!open) return;
    try {
      setData(await api.readSheetTab(open.source.id, open.tab));
    } catch (e) {
      setError((e as ApiError).detail || "Could not reload the rows.");
    }
  }

  async function saveRow(rowNumber: number) {
    if (!open) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.updateSheetRow(
        open.source.id,
        open.tab,
        rowNumber,
        draft
      );
      setNotice(
        `Row ${rowNumber} updated in the sheet` +
          (r.unknown_columns.length
            ? ` — these columns do not exist and were skipped: ${r.unknown_columns.join(
                ", "
              )}`
            : "")
      );
      setEditing(null);
      setDraft({});
      await refreshRows();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save that row.");
    } finally {
      setBusy(false);
    }
  }

  async function addRow() {
    if (!open) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.addSheetRow(open.source.id, open.tab, draft);
      setNotice(`Added as row ${r.row_number} in the sheet.`);
      setAdding(false);
      setDraft({});
      await refreshRows();
    } catch (e) {
      setError((e as ApiError).detail || "Could not add that row.");
    } finally {
      setBusy(false);
    }
  }

  async function removeRow(rowNumber: number) {
    if (!open) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.deleteSheetRow(open.source.id, open.tab, rowNumber);
      setDeleted(r.deleted);
      setNotice("");
      setConfirmDelete(null);
      await refreshRows();
    } catch (e) {
      setError((e as ApiError).detail || "Could not delete that row.");
    } finally {
      setBusy(false);
    }
  }

  // The first two or three columns identify a row well enough to confirm a
  // deletion against, whatever the tab is.
  function describe(cells: Record<string, string>) {
    if (!data) return "";
    return data.columns
      .slice(0, 3)
      .map((c) => cells[c])
      .filter(Boolean)
      .join(" · ");
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">
          Sheets
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 max-w-3xl">
          The data every other screen is built from. What you change here is
          written to the Google Sheet itself — anyone with it open will see it,
          and the next sync will read it.
        </p>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      {deleted && (
        <div className="rounded-xl border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 p-5">
          <h3 className="text-sm font-bold text-red-900 dark:text-red-300">
            Deleted — this cannot be undone here
          </h3>
          <p className="text-xs text-red-800 dark:text-red-400 mt-1 mb-3">
            Shown so you can put it back by hand. The spreadsheet&rsquo;s own
            version history in Google Sheets is the real recovery.
          </p>
          <div className="grid gap-1 sm:grid-cols-2 text-xs">
            {Object.entries(deleted)
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  <span className="text-red-700 dark:text-red-400">{k}: </span>
                  <span className="text-gray-900 dark:text-white">{v}</span>
                </div>
              ))}
          </div>
          <button
            onClick={() => setDeleted(null)}
            className="mt-3 text-xs text-red-700 dark:text-red-400 hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* The registered sheets, each with the tabs it really has */}
      {loading && (
        <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>
      )}

      {/* One card per SPREADSHEET, not per source.
          Two sources — CSP records and the territory directory — live in
          the same spreadsheet, so listing them separately showed the same
          file and the same tabs twice over. Grouping says what is actually
          true: one spreadsheet, these tabs, read for these purposes. */}
      <div className="space-y-3">
        {groupBySpreadsheet(sources).map((group) => (
          <div
            key={group.spreadsheet_id}
            className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5"
          >
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="min-w-0">
                <h3 className="font-bold text-gray-900 dark:text-white">
                  {group.title || group.sources[0].name}
                </h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  read for{" "}
                  {group.sources.map((s) => s.purpose).join(", ")}
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {canManage && group.sources.map((s) => (
                  <button
                    key={s.id}
                    onClick={async () => {
                      if (
                        !confirm(
                          `Stop reading "${s.name}"? The spreadsheet itself is not changed.`
                        )
                      )
                        return;
                      try {
                        await api.unregisterSheet(s.id);
                        setNotice(`${s.name} is no longer being read.`);
                        await load();
                      } catch (e) {
                        setError(
                          (e as ApiError).detail || "Could not remove it."
                        );
                      }
                    }}
                    className="text-xs text-gray-400 hover:text-red-600"
                  >
                    Stop reading {s.purpose}
                  </button>
                ))}
              </div>
            </div>

            {group.error && (
              <p className="mt-3 text-sm text-red-600 dark:text-red-400">
                {group.error}
              </p>
            )}

            {group.tabs && (
              <div className="mt-3 flex flex-wrap gap-2">
                {group.tabs.map((t) => {
                  // Which source, if any, actually reads this tab. That is
                  // the one an edit should be made through.
                  const owner =
                    group.sources.find((s) =>
                      s.tabs_configured.includes(t.title)
                    ) || group.sources[0];
                  const isRead = group.sources.some((s) =>
                    s.tabs_configured.includes(t.title)
                  );
                  const isOpen =
                    open?.source.id === owner.id && open?.tab === t.title;
                  return (
                    <button
                      key={t.tab_id}
                      onClick={() => openTab(owner, t.title)}
                      className={`px-3 py-1.5 rounded-lg text-sm border transition ${
                        isOpen
                          ? "bg-eko text-white border-eko"
                          : "border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:border-eko"
                      }`}
                      title={
                        isRead
                          ? `Read by this system as "${owner.purpose}"`
                          : "Present in the spreadsheet; not read by this system"
                      }
                    >
                      {t.title}
                      {isRead && (
                        <span className="ml-1.5 text-[10px] opacity-70">
                          ● read
                        </span>
                      )}
                    </button>
                  );
                })}
                {group.tabs.length === 0 && (
                  <p className="text-sm text-gray-400">No tabs.</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {canManage && (
      <AddSheet
        open={registering}
        onOpen={() => setRegistering(true)}
        onClose={() => setRegistering(false)}
        onDone={async (name) => {
          setRegistering(false);
          setNotice(`${name} added.`);
          await load();
        }}
        onError={setError}
      />
      )}

      {/* The rows of whichever tab is open */}
      {open && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-100 dark:border-gray-700 flex-wrap">
            <div>
              <h3 className="font-bold text-gray-900 dark:text-white">
                {open.source.name} — {open.tab}
              </h3>
              {data && (
                <p className="text-xs text-gray-500">
                  {data.rows.length} row{data.rows.length === 1 ? "" : "s"},{" "}
                  {data.columns.length} columns
                  {data.truncated && " — showing the first 2000"}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  setAdding(true);
                  setEditing(null);
                  setDraft({});
                }}
                className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark text-white font-medium"
              >
                Add a row
              </button>
              <button
                onClick={() => setOpen(null)}
                className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:underline"
              >
                Close
              </button>
            </div>
          </div>

          <div className="p-5">
            {loadingRows && <p className="text-sm text-gray-500">Loading…</p>}

            {adding && data && (
              <div className="mb-5 p-4 rounded-lg border border-eko/40 bg-eko-light/40 dark:bg-gray-700/40">
                <p className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
                  New row — it will be added at the end of {open.tab}
                </p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {data.columns.map((c) => (
                    <label key={c} className="text-xs">
                      <span className="text-gray-600 dark:text-gray-300">
                        {c}
                      </span>
                      <input
                        value={draft[c] ?? ""}
                        onChange={(e) =>
                          setDraft({ ...draft, [c]: e.target.value })
                        }
                        className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                      />
                    </label>
                  ))}
                </div>
                <div className="flex items-center gap-3 mt-4">
                  <button
                    onClick={addRow}
                    disabled={busy}
                    className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium"
                  >
                    {busy ? "Adding…" : "Add to the sheet"}
                  </button>
                  <button
                    onClick={() => {
                      setAdding(false);
                      setDraft({});
                    }}
                    className="text-sm text-gray-600 dark:text-gray-300 hover:underline"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {data && data.rows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase text-gray-500">
                    <tr>
                      <th className="pb-2 pr-3 font-semibold">Row</th>
                      {data.columns.map((c) => (
                        <th
                          key={c}
                          className="pb-2 pr-4 font-semibold whitespace-nowrap"
                        >
                          {c}
                        </th>
                      ))}
                      <th className="pb-2 font-semibold"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {data.rows.map((row) => {
                      const isEditing = editing === row.row_number;
                      return (
                        <tr key={row.row_number} className="align-top">
                          <td className="py-2 pr-3 text-gray-400 tabular-nums">
                            {row.row_number}
                          </td>
                          {data.columns.map((c) => (
                            <td key={c} className="py-2 pr-4">
                              {isEditing ? (
                                <input
                                  value={draft[c] ?? ""}
                                  onChange={(e) =>
                                    setDraft({ ...draft, [c]: e.target.value })
                                  }
                                  className="w-40 px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                                />
                              ) : (
                                <Cell
                                  column={c}
                                  value={row.cells[c]}
                                  cspCode={row.cells["CSP Code"]}
                                />
                              )}
                            </td>
                          ))}
                          <td className="py-2 whitespace-nowrap">
                            {isEditing ? (
                              <>
                                <button
                                  onClick={() => saveRow(row.row_number)}
                                  disabled={busy}
                                  className="text-xs text-eko font-semibold hover:underline disabled:opacity-50"
                                >
                                  {busy ? "Saving…" : "Save"}
                                </button>
                                <button
                                  onClick={() => {
                                    setEditing(null);
                                    setDraft({});
                                  }}
                                  className="ml-3 text-xs text-gray-500 hover:underline"
                                >
                                  Cancel
                                </button>
                              </>
                            ) : confirmDelete === row.row_number ? (
                              <>
                                <span className="text-xs text-red-700 dark:text-red-400 mr-2">
                                  Delete {describe(row.cells)}?
                                </span>
                                <button
                                  onClick={() => removeRow(row.row_number)}
                                  disabled={busy}
                                  className="text-xs text-white bg-red-600 hover:bg-red-700 px-2 py-1 rounded disabled:opacity-50"
                                >
                                  Yes, delete
                                </button>
                                <button
                                  onClick={() => setConfirmDelete(null)}
                                  className="ml-2 text-xs text-gray-500 hover:underline"
                                >
                                  Cancel
                                </button>
                              </>
                            ) : (
                              <>
                                <button
                                  onClick={() => {
                                    setEditing(row.row_number);
                                    setAdding(false);
                                    setDraft({ ...row.cells });
                                  }}
                                  className="text-xs text-gray-600 dark:text-gray-300 hover:underline"
                                >
                                  Edit
                                </button>
                                <button
                                  onClick={() => {
                                    setConfirmDelete(row.row_number);
                                    setEditing(null);
                                  }}
                                  className="ml-3 text-xs text-gray-400 hover:text-red-600"
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {data && data.rows.length === 0 && !loadingRows && (
              <p className="text-sm text-gray-400">
                This tab has a header but no rows yet.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** One entry per spreadsheet, however many sources point at it. */
function groupBySpreadsheet(sources: SheetSource[]) {
  const byId = new Map<
    string,
    {
      spreadsheet_id: string;
      title: string;
      sources: SheetSource[];
      tabs: SheetSource["tabs_live"];
      error: string | null;
    }
  >();

  for (const s of sources) {
    const existing = byId.get(s.spreadsheet_id);
    if (existing) {
      existing.sources.push(s);
      // Every tab any of its sources shows, once each. For an Admin or RM
      // each source lists only the tabs it is read from (No. 104), so
      // taking the first source's list alone would hide the others'.
      if (s.tabs_live) {
        const seen = new Set((existing.tabs ?? []).map((t) => t.title));
        existing.tabs = [
          ...(existing.tabs ?? []),
          ...s.tabs_live.filter((t) => !seen.has(t.title)),
        ];
      }
      existing.error = existing.error ?? s.error ?? null;
      existing.title = existing.title || s.title || "";
      continue;
    }
    byId.set(s.spreadsheet_id, {
      spreadsheet_id: s.spreadsheet_id,
      title: s.title || "",
      sources: [s],
      tabs: s.tabs_live,
      error: s.error ?? null,
    });
  }
  return [...byId.values()];
}

/** Register another spreadsheet for this workspace to read. */
function AddSheet({
  open,
  onOpen,
  onClose,
  onDone,
  onError,
}: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onDone: (name: string) => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [spreadsheetId, setSpreadsheetId] = useState("");
  const [tab, setTab] = useState("");
  const [purpose, setPurpose] = useState("records");
  const [busy, setBusy] = useState(false);

  if (!open) {
    return (
      <button
        onClick={onOpen}
        className="px-3 py-2 text-sm rounded-lg border border-dashed border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:border-eko hover:text-eko w-full"
      >
        + Add another sheet
      </button>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-3">
      <h3 className="font-bold text-gray-900 dark:text-white">
        Add a sheet
      </h3>
      <p className="text-xs text-gray-500">
        The spreadsheet must be shared with the service account, or it cannot
        be opened. The id is the long string in its URL between{" "}
        <code>/d/</code> and <code>/edit</code>.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" value={name} onChange={setName} />
        <Field
          label="Spreadsheet id"
          value={spreadsheetId}
          onChange={setSpreadsheetId}
        />
        <Field label="Tab" value={tab} onChange={setTab} />
        <label className="text-xs">
          <span className="text-gray-600 dark:text-gray-300">What it is for</span>
          <select
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
          >
            <option value="records">Records — the CSPs themselves</option>
            <option value="directory">Directory — territory and contacts</option>
            <option value="authorization">Authorization — who may sign in</option>
          </select>
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={async () => {
            setBusy(true);
            try {
              await api.registerSheet({
                name,
                spreadsheet_id: spreadsheetId.trim(),
                tab: tab.trim(),
                purpose,
              });
              setName("");
              setSpreadsheetId("");
              setTab("");
              onDone(name);
            } catch (e) {
              onError((e as ApiError).detail || "Could not add that sheet.");
            } finally {
              setBusy(false);
            }
          }}
          disabled={busy || !name || !spreadsheetId || !tab}
          className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium"
        >
          {busy ? "Checking…" : "Add"}
        </button>
        <button
          onClick={onClose}
          className="text-sm text-gray-600 dark:text-gray-300 hover:underline"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="text-xs">
      <span className="text-gray-600 dark:text-gray-300">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
      />
    </label>
  );
}

/** A Photo cell names a file. Showing the path tells a person nothing, so
 *  the picture itself is fetched and shown. Anything that is not an image
 *  path falls through to plain text.
 *
 *  In a CSP tab the Photo column shows the app's photo of that row's CSP —
 *  the passport version (No. 102). Google returns a cell holding a picture
 *  as empty, so the cell alone could never show it. */
function Cell({
  column,
  value,
  cspCode,
}: {
  column: string;
  value: string;
  cspCode?: string;
}) {
  const code = (cspCode || "").trim();
  if (column.trim().toLowerCase() === "photo" && code) {
    return <CspPhoto cspId={code} className="h-16 w-[50px]" />;
  }
  const text = (value || "").trim();
  if (!text) return <span className="text-gray-300 dark:text-gray-600"></span>;

  const looksLikeImage = /\.(jpe?g|png|gif|webp|bmp)$/i.test(text);
  if (!looksLikeImage) {
    return <span className="text-gray-700 dark:text-gray-300">{text}</span>;
  }

  return (
    <SheetPhoto path={text} alt={column} />
  );
}

function SheetPhoto({ path, alt }: { path: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  const src = withBase(`/api/admin/sheets/_photo?path=${encodeURIComponent(path)}`);

  if (failed) {
    // Said plainly rather than showing a broken frame: the cell has a
    // path and the file behind it is not there.
    return (
      <span className="text-xs text-amber-700 dark:text-amber-500">
        photo missing
      </span>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      title={path}
      onError={() => setFailed(true)}
      className="h-16 w-[50px] object-cover rounded border border-gray-200 dark:border-gray-600"
    />
  );
}

function Banner({
  kind,
  children,
}: {
  kind: "ok" | "error";
  children: React.ReactNode;
}) {
  const style =
    kind === "ok"
      ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-700 dark:text-green-300"
      : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300";
  return (
    <div className={`px-4 py-3 rounded-lg border text-sm ${style}`}>
      {children}
    </div>
  );
}
