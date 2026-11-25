"use client";

/**
 * Renders a built dashboard.
 *
 * Generic on purpose: it draws whatever widgets the dashboard was built
 * with, and knows nothing about what they mean. A widget whose metric
 * cannot be computed shows its own error rather than blanking the screen —
 * one broken card should not cost you the other nine.
 *
 * The permanent Document Operations dashboard does NOT come through here.
 * That screen has filters, drill-down and CSV export, and replacing it with
 * generic cards would be a downgrade.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  DashboardDetail,
  DashboardLayout,
  MetricRecords,
  WidgetData,
} from "../lib/api";

export default function DashboardView({
  slug,
  onRetired,
  canManage,
}: {
  slug: string;
  onRetired?: () => void;
  canManage: boolean;
}) {
  const [dashboard, setDashboard] = useState<DashboardDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);

  // Which number is open, and what it opened into. Held here rather than
  // in each card so only one list is on screen at a time.
  const [openWidget, setOpenWidget] = useState<WidgetData | null>(null);
  const [records, setRecords] = useState<MetricRecords | null>(null);
  const [recordsError, setRecordsError] = useState("");
  const [loadingRecords, setLoadingRecords] = useState(false);

  // `field` is set when a row of a table widget was clicked rather than a
  // whole number — it says which row.
  const [openTitle, setOpenTitle] = useState("");
  // No. 240 (Stage 5): this person's own arrangement (order, hidden,
  // columns). null = the workspace's, as built on Build a dashboard.
  const [mine, setMine] = useState<DashboardLayout | null>(null);
  const [draft, setDraft] = useState<DashboardLayout | null>(null);
  const [arrangeError, setArrangeError] = useState("");
  const [arrangeBusy, setArrangeBusy] = useState(false);

  // The list opens underneath the widgets, which on a tall dashboard is
  // below the fold — so clicking a number appeared to do nothing until you
  // scrolled. Bringing it into view is part of opening it.
  const listRef = useRef<HTMLDivElement | null>(null);

  const openRecords = useCallback(async (
    widget: WidgetData,
    field?: string,
    title?: string,
  ) => {
    setOpenWidget(widget);
    setOpenTitle(title || widget.title);
    setRecords(null);
    setRecordsError("");
    setLoadingRecords(true);
    try {
      setRecords(await api.metricRecords(widget.metric, field));
    } catch (e) {
      setRecordsError(
        (e as ApiError).detail || "Could not list what that number counted."
      );
    } finally {
      setLoadingRecords(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDashboard(await api.readDashboard(slug));
      setError("");
      // One's own arrangement; failing to read it only means the
      // workspace's arrangement is shown.
      api
        .myDashboardLayout(slug)
        .then((r) => setMine(r.layout))
        .catch((e) => console.warn("DashboardView: own arrangement not read", e));
    } catch (e) {
      setError((e as ApiError).detail || "Could not load that dashboard.");
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!openWidget) return;
    // After the panel has rendered, not before.
    const id = window.requestAnimationFrame(() =>
      listRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
    );
    return () => window.cancelAnimationFrame(id);
  }, [openWidget, records]);

  async function retire() {
    try {
      // Hidden, not deleted. The records, submissions and history behind
      // this screen are untouched, and switching it back on brings the
      // whole thing with it.
      await api.updateDashboard(slug, { active: false });
      onRetired?.();
    } catch (e) {
      setError((e as ApiError).detail || "Could not retire that dashboard.");
    }
  }

  const layout = draft ?? mine;
  const arranging = draft !== null;
  const shown = useMemo(() => {
    const all = dashboard?.widgets ?? [];
    if (!layout) return all;
    const at = new Map(layout.order.map((id, i) => [id, i]));
    const ordered = [...all].sort((a, b) => {
      const x = at.has(a.id) ? at.get(a.id)! : layout.order.length + a.position;
      const y = at.has(b.id) ? at.get(b.id)! : layout.order.length + b.position;
      return x - y;
    });
    return arranging ? ordered : ordered.filter((w) => !layout.hidden.includes(w.id));
  }, [dashboard, layout, arranging]);
  const columns = layout?.columns ?? 4;

  function move(id: string, by: number) {
    const ids = shown.map((w) => w.id);
    const i = ids.indexOf(id);
    const j = i + by;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setDraft((d) => ({ ...(d ?? { order: [], hidden: [] }), order: ids }));
  }

  function toggle(id: string) {
    setDraft((d) => {
      const base = d ?? { order: shown.map((w) => w.id), hidden: [] };
      const hidden = base.hidden.includes(id) ? base.hidden.filter((h) => h !== id) : [...base.hidden, id];
      return { ...base, hidden };
    });
  }

  async function saveArrangement() {
    if (!draft) return;
    setArrangeBusy(true);
    setArrangeError("");
    try {
      const r = await api.saveDashboardLayout(slug, { ...draft, order: shown.map((w) => w.id) });
      setMine(r.layout);
      setDraft(null);
    } catch (e) {
      setArrangeError((e as ApiError).detail || "Could not save your arrangement.");
    } finally {
      setArrangeBusy(false);
    }
  }

  async function backToWorkspace() {
    if (!window.confirm("Show this dashboard as your workspace arranged it?")) return;
    setArrangeBusy(true);
    setArrangeError("");
    try {
      await api.resetDashboardLayout(slug);
      setMine(null);
      setDraft(null);
    } catch (e) {
      setArrangeError((e as ApiError).detail || "Could not reset.");
    } finally {
      setArrangeBusy(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-500 py-12 text-center">Loading…</p>;
  }
  if (error) {
    return (
      <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
        {error}
      </div>
    );
  }
  if (!dashboard) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">
            {dashboard.name}
          </h2>
          {dashboard.description && (
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-2xl">
              {dashboard.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {!arranging && (
            <button
              onClick={() => setDraft({ order: shown.map((w) => w.id), hidden: mine?.hidden ?? [], columns: mine?.columns })}
              className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              <i className="fas fa-grip mr-2 text-xs" />
              Arrange my view
            </button>
          )}
          {!arranging && mine && (
            <button
              onClick={backToWorkspace}
              disabled={arrangeBusy}
              className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:underline"
            >
              Workspace layout
            </button>
          )}
        </div>
        {canManage && dashboard.can_remove && (
          <div className="flex items-center gap-2">
            {confirming ? (
              <>
                <span className="text-xs text-gray-500">
                  Hide this? Nothing is deleted — you can bring it back from
                  Build a dashboard.
                </span>
                <button
                  onClick={retire}
                  className="px-3 py-1.5 text-sm rounded-lg bg-red-600 hover:bg-red-700 text-white"
                >
                  Retire
                </button>
                <button
                  onClick={() => setConfirming(false)}
                  className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:underline"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={() => setConfirming(true)}
                className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <i className="fas fa-eye-slash mr-2 text-xs" />
                Retire
              </button>
            )}
          </div>
        )}
      </div>

      {arranging && (
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-eko/40 bg-eko-light dark:bg-gray-800 px-4 py-3">
          <span className="text-sm text-gray-800 dark:text-gray-100 mr-auto">
            Arranging your own view — move, hide or show widgets. Only your screen changes.
          </span>
          <label className="text-sm text-gray-700 dark:text-gray-200 flex items-center gap-2">
            Columns
            <select
              value={draft?.columns ?? 4}
              onChange={(e) => setDraft((d) => ({ ...(d as DashboardLayout), columns: Number(e.target.value) }))}
              className="px-2 py-1 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm"
            >
              {[4, 3, 2, 1].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <button
            onClick={() => setDraft(null)}
            disabled={arrangeBusy}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-white dark:hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            onClick={saveArrangement}
            disabled={arrangeBusy}
            className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark text-white font-semibold disabled:opacity-50"
          >
            {arrangeBusy ? "Saving…" : "Save my view"}
          </button>
        </div>
      )}
      {arrangeError && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{arrangeError}</div>}

      <div className={`grid gap-4 ${GRID[columns] ?? GRID[4]}`}>
        {shown.map((widget, i) => {
          const hidden = Boolean(layout?.hidden.includes(widget.id));
          return (
            <Widget
              key={widget.id}
              widget={widget}
              columns={columns}
              dimmed={arranging && hidden}
              controls={
                arranging ? (
                  <div className="flex items-center gap-1 mb-2">
                    <button
                      type="button"
                      aria-label={`Move ${widget.title} earlier`}
                      disabled={i === 0}
                      onClick={() => move(widget.id, -1)}
                      className="w-8 h-8 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 disabled:opacity-30"
                    >
                      <i className="fas fa-arrow-left text-xs" />
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${widget.title} later`}
                      disabled={i === shown.length - 1}
                      onClick={() => move(widget.id, 1)}
                      className="w-8 h-8 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 disabled:opacity-30"
                    >
                      <i className="fas fa-arrow-right text-xs" />
                    </button>
                    <button
                      type="button"
                      aria-pressed={!hidden}
                      onClick={() => toggle(widget.id)}
                      className="ml-auto px-2 h-8 rounded-lg border border-gray-200 dark:border-gray-600 text-xs text-gray-700 dark:text-gray-200"
                    >
                      <i className={`fas ${hidden ? "fa-eye" : "fa-eye-slash"} mr-1`} />
                      {hidden ? "Show" : "Hide"}
                    </button>
                  </div>
                ) : null
              }
              onOpen={!arranging && widget.drillable ? () => openRecords(widget) : undefined}
              onOpenRow={
                !arranging && widget.drillable
                  ? (field, title) => openRecords(widget, field, title)
                  : undefined
              }
            />
          );
        })}
      </div>
      {!arranging && layout && shown.length === 0 && dashboard.widgets.length > 0 && (
        <p className="text-sm text-gray-500 py-6 text-center">
          You have hidden every widget. Arrange my view → Show, or Workspace layout.
        </p>
      )}

      {dashboard.widgets.length === 0 && (
        <p className="text-sm text-gray-500 py-10 text-center">
          This dashboard has no widgets yet.
        </p>
      )}

      {openWidget && (
        <div ref={listRef}>
          <RecordList
          title={openTitle || openWidget.title}
          records={records}
          loading={loadingRecords}
          error={recordsError}
            onClose={() => setOpenWidget(null)}
          />
        </div>
      )}
    </div>
  );
}

/** What one number counted, listed out.
 *
 *  The columns come from the server because they differ by metric: the
 *  completeness numbers name the blank fields, and "Documents generated"
 *  counts documents rather than CSPs, so it carries a document column.
 */
function RecordList({
  title,
  records,
  loading,
  error,
  onClose,
}: {
  title: string;
  records: MetricRecords | null;
  loading: boolean;
  error: string;
  onClose: () => void;
}) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-100 dark:border-gray-700">
        <div className="min-w-0">
          <h3 className="font-bold text-gray-900 dark:text-white">{title}</h3>
          {records && (
            <p className="text-xs text-gray-500">
              {records.count === 0
                ? "Nothing matched."
                : `${records.count} record${records.count === 1 ? "" : "s"}`}
              {records.truncated && " — showing the first 500"}
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:underline shrink-0"
        >
          Close
        </button>
      </div>

      <div className="p-5">
        {loading && <p className="text-sm text-gray-500">Loading…</p>}
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
        {records && records.rows.length === 0 && !loading && (
          <p className="text-sm text-gray-400">
            Nothing matched — which is what the zero means.
          </p>
        )}
        {records && records.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-gray-500">
                <tr>
                  {records.columns.map((c) => (
                    <th key={c.key} className="pb-2 pr-4 font-semibold">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {records.rows.map((row, i) => (
                  <tr key={`${row.csp_id ?? i}-${i}`}>
                    {records.columns.map((c) => (
                      <td
                        key={c.key}
                        className="py-2 pr-4 text-gray-700 dark:text-gray-300"
                      >
                        {row[c.key] || "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// No. 240 (Stage 5): the grid for the number of columns a person chose
// (4 = as the workspace built it).
const GRID: Record<number, string> = {
  4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4",
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
  2: "grid-cols-1 sm:grid-cols-2",
  1: "grid-cols-1",
};

function spanFor(width: number, columns: number): string {
  const w = Math.min(width, columns);
  if (columns === 4) return w >= 4 ? "lg:col-span-4" : w === 3 ? "lg:col-span-3" : w === 2 ? "lg:col-span-2" : "";
  if (columns === 3) return w >= 3 ? "sm:col-span-2 lg:col-span-3" : w === 2 ? "lg:col-span-2" : "";
  if (columns === 2) return w >= 2 ? "sm:col-span-2" : "";
  return "";
}

function Widget({
  widget,
  onOpen,
  onOpenRow,
  columns = 4,
  dimmed = false,
  controls = null,
}: {
  widget: WidgetData;
  onOpen?: () => void;
  onOpenRow?: (field: string, title: string) => void;
  columns?: number;
  dimmed?: boolean;
  controls?: React.ReactNode;
}) {
  const span = spanFor(widget.width, columns);

  const shell = `p-5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 ${span} ${dimmed ? "opacity-40" : ""}`;

  if (widget.error) {
    return (
      <div className={shell}>{controls}
        <p className="text-xs font-medium text-gray-500">{widget.title}</p>
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">
          {widget.error}
        </p>
      </div>
    );
  }

  const data = widget.data;

  // One number. Clickable when the server says the number opens into a
  // list — rendered as a real button so it is reachable by keyboard and
  // announced as something that can be activated.
  if (data && typeof data === "object" && "value" in data) {
    const value = (data as { value: number }).value;
    const body = (
      <>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
          {widget.title}
        </p>
        <p className="mt-2 text-3xl font-bold text-gray-900 dark:text-white tabular-nums">
          {value}
        </p>
      </>
    );

    if (!onOpen) {
      return <div className={shell}>{controls}{body}</div>;
    }
    return (
      <button
        type="button"
        onClick={onOpen}
        title={`Show the records behind ${widget.title}`}
        className={`${shell} text-left w-full transition hover:border-eko hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-eko group`}
      >
        {body}
        <span className="mt-2 inline-flex items-center gap-1 text-xs text-gray-400 group-hover:text-eko">
          {value === 0 ? "Check the list" : "See which"}
          <i className="fas fa-arrow-right text-xs" />
        </span>
      </button>
    );
  }

  // A breakdown.
  if (Array.isArray(data)) {
    return (
      <div className={shell}>{controls}
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
          {widget.title}
        </p>
        <div className="space-y-2">
          {data.map((row) => (
            <div
              key={row.key ?? row.label}
              className="flex items-center justify-between text-sm"
            >
              <span className="text-gray-700 dark:text-gray-300 pr-3">
                {row.label}
              </span>
              <span className="font-semibold tabular-nums text-gray-900 dark:text-white">
                {row.value}
              </span>
            </div>
          ))}
          {data.length === 0 && (
            <p className="text-sm text-gray-400">Nothing yet.</p>
          )}
        </div>
      </div>
    );
  }

  // A table.
  if (data && typeof data === "object" && "rows" in data) {
    const table = data as {
      columns: Array<{ key: string; label: string }>;
      rows: Array<Record<string, unknown>>;
    };
    return (
      <div className={shell}>{controls}
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
          {widget.title}
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                {table.columns.map((c) => (
                  <th key={c.key} className="pb-2 pr-4 font-semibold">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {table.rows.map((row, i) => {
                // A row opens its own list when it carries a key saying
                // which row it is. Rows without one are not clickable.
                const field = row.key ? String(row.key) : "";
                const clickable = Boolean(onOpenRow && field);
                const label = String(row[table.columns[0].key] ?? "");
                return (
                  <tr
                    key={field || i}
                    onClick={
                      clickable ? () => onOpenRow!(field, label) : undefined
                    }
                    tabIndex={clickable ? 0 : undefined}
                    role={clickable ? "button" : undefined}
                    title={clickable ? `Show who answered: ${label}` : undefined}
                    onKeyDown={
                      clickable
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onOpenRow!(field, label);
                            }
                          }
                        : undefined
                    }
                    className={
                      clickable
                        ? "cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 focus:outline-none focus:bg-gray-50 dark:focus:bg-gray-700/50"
                        : undefined
                    }
                  >
                    {table.columns.map((c) => (
                      <td
                        key={c.key}
                        className="py-2 pr-4 text-gray-700 dark:text-gray-300"
                      >
                        {String(row[c.key] ?? "")}
                      </td>
                    ))}
                  </tr>
                );
              })}
              {table.rows.length === 0 && (
                <tr>
                  <td
                    colSpan={table.columns.length}
                    className="py-4 text-gray-400"
                  >
                    Nothing yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <div className={shell}>{controls}
      <p className="text-xs font-medium text-gray-500">{widget.title}</p>
      <p className="mt-2 text-sm text-gray-400">No data.</p>
    </div>
  );
}
