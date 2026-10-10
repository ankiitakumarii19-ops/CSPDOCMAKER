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

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  DashboardDetail,
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

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {dashboard.widgets.map((widget) => (
          <Widget
            key={widget.id}
            widget={widget}
            onOpen={widget.drillable ? () => openRecords(widget) : undefined}
            onOpenRow={
              widget.drillable
                ? (field, title) => openRecords(widget, field, title)
                : undefined
            }
          />
        ))}
      </div>

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

function Widget({
  widget,
  onOpen,
  onOpenRow,
}: {
  widget: WidgetData;
  onOpen?: () => void;
  onOpenRow?: (field: string, title: string) => void;
}) {
  const span =
    widget.width >= 4
      ? "lg:col-span-4"
      : widget.width === 3
      ? "lg:col-span-3"
      : widget.width === 2
      ? "lg:col-span-2"
      : "";

  const shell = `p-5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 ${span}`;

  if (widget.error) {
    return (
      <div className={shell}>
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
      return <div className={shell}>{body}</div>;
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
          <i className="fas fa-arrow-right text-[10px]" />
        </span>
      </button>
    );
  }

  // A breakdown.
  if (Array.isArray(data)) {
    return (
      <div className={shell}>
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
      <div className={shell}>
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
    <div className={shell}>
      <p className="text-xs font-medium text-gray-500">{widget.title}</p>
      <p className="mt-2 text-sm text-gray-400">No data.</p>
    </div>
  );
}
