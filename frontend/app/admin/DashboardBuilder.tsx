"use client";

/**
 * Building a dashboard.
 *
 * A widget can only show a metric the system knows how to compute, so the
 * palette is the registry — there is no free-text metric box, and nothing
 * here can describe its own query.
 *
 * The widget kinds offered for a metric come from that metric, so a table
 * of recent submissions is never offered as a single number. The backend
 * refuses the mismatch anyway; this stops it being possible to choose.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError, DashboardSummary, MetricGroup, WidgetSpec,
} from "../lib/api";

const ICONS = [
  "fa-chart-simple", "fa-clipboard-check", "fa-camera", "fa-users",
  "fa-envelope", "fa-triangle-exclamation", "fa-list-check", "fa-gauge",
];

export default function DashboardBuilder({
  onBuilt,
  onCancel,
}: {
  onBuilt: (slug: string) => void;
  onCancel: () => void;
}) {
  const [groups, setGroups] = useState<MetricGroup[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState(ICONS[0]);
  const [widgets, setWidgets] = useState<WidgetSpec[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Dashboards that were hidden rather than deleted, so they can come back.
  const [retired, setRetired] = useState<DashboardSummary[]>([]);

  const loadRetired = useCallback(async () => {
    try {
      const all = await api.listDashboards(true);
      setRetired(all.dashboards.filter((d) => !d.active));
    } catch {
      // Not being able to list hidden dashboards must not stop someone
      // building a new one.
    }
  }, []);

  useEffect(() => {
    api
      .dashboardMetrics()
      .then((d) => setGroups(d.groups))
      .catch((e) =>
        setError((e as ApiError).detail || "Could not load the metrics.")
      );
    loadRetired();
  }, [loadRetired]);

  async function restore(slug: string) {
    setBusy(true);
    try {
      await api.updateDashboard(slug, { active: true });
      await loadRetired();
      onBuilt(slug);
    } catch (e) {
      setError((e as ApiError).detail || "Could not bring that back.");
    } finally {
      setBusy(false);
    }
  }

  async function removeForGood(slug: string) {
    setBusy(true);
    try {
      await api.deleteDashboard(slug);
      await loadRetired();
    } catch (e) {
      setError((e as ApiError).detail || "Could not delete that.");
    } finally {
      setBusy(false);
    }
  }

  function add(metricKey: string, label: string, kinds: string[]) {
    setWidgets((w) => [
      ...w,
      {
        metric: metricKey,
        // The first kind the metric supports is always a valid choice.
        kind: kinds[0] ?? "metric_card",
        title: label,
        width: kinds[0] === "metric_card" ? 1 : 2,
      },
    ]);
  }

  function update(index: number, patch: Partial<WidgetSpec>) {
    setWidgets((w) => w.map((x, i) => (i === index ? { ...x, ...patch } : x)));
  }

  function remove(index: number) {
    setWidgets((w) => w.filter((_, i) => i !== index));
  }

  function move(index: number, by: number) {
    setWidgets((w) => {
      const next = [...w];
      const target = index + by;
      if (target < 0 || target >= next.length) return w;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function kindsFor(metricKey: string): string[] {
    for (const g of groups) {
      const m = g.metrics.find((x) => x.key === metricKey);
      if (m) return m.widgets;
    }
    return ["metric_card"];
  }

  async function build() {
    if (!name.trim() || widgets.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const made = await api.createDashboard({
        name: name.trim(),
        description: description.trim() || undefined,
        icon,
        widgets,
      });
      onBuilt(made.slug);
    } catch (e) {
      setError((e as ApiError).detail || "Could not build that dashboard.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">
          Build a dashboard
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Pick what it should show. Anything built here can be retired later
          without losing the data behind it.
        </p>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {retired.length > 0 && (
        <div className="p-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60">
          <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">
            Retired dashboards
          </div>
          <p className="text-xs text-gray-500 mb-3">
            Hidden, not deleted. Everything they showed is still here.
          </p>
          <div className="space-y-2">
            {retired.map((d) => (
              <div
                key={d.slug}
                className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700"
              >
                <div>
                  <span className="text-sm font-medium text-gray-900 dark:text-white">
                    <i className={`fas ${d.icon} mr-2 text-gray-400`} />
                    {d.name}
                  </span>
                  <span className="ml-2 text-xs text-gray-500">
                    {d.widget_count} widget{d.widget_count === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => restore(d.slug)}
                    disabled={busy}
                    className="text-sm font-medium text-eko hover:underline disabled:opacity-50"
                  >
                    Bring back
                  </button>
                  <button
                    onClick={() => removeForGood(d.slug)}
                    disabled={busy}
                    className="text-xs text-gray-400 hover:text-red-600 disabled:opacity-50"
                    title="Delete permanently"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="md:col-span-2">
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
            Name
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Photo chase"
            className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
            Icon
          </label>
          <div className="flex flex-wrap gap-1">
            {ICONS.map((i) => (
              <button
                key={i}
                onClick={() => setIcon(i)}
                className={`w-9 h-9 rounded-lg border text-sm ${
                  icon === i
                    ? "border-eko bg-eko/10 text-eko"
                    : "border-gray-300 dark:border-gray-600 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-700"
                }`}
              >
                <i className={`fas ${i}`} />
              </button>
            ))}
          </div>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
          Description (optional)
        </label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* The palette */}
        <div className="space-y-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">
            What it can show
          </h3>
          {groups.map((group) => (
            <div key={group.group}>
              <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                {group.label}
              </p>
              <div className="space-y-1">
                {group.metrics.map((metric) => (
                  <button
                    key={metric.key}
                    onClick={() => add(metric.key, metric.label, metric.widgets)}
                    className="w-full text-left px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-eko hover:bg-eko/5 transition-colors"
                  >
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {metric.label}
                    </span>
                    <span className="block text-xs text-gray-500">
                      {metric.description}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* What has been chosen */}
        <div className="space-y-3">
          <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">
            On this dashboard ({widgets.length})
          </h3>
          {widgets.length === 0 && (
            <p className="text-sm text-gray-400 py-6">
              Nothing chosen yet. Pick from the left.
            </p>
          )}
          {widgets.map((widget, index) => (
            <div
              key={`${widget.metric}-${index}`}
              className="p-3 rounded-lg border border-gray-200 dark:border-gray-700 space-y-2"
            >
              <div className="flex items-start gap-2">
                <input
                  value={widget.title}
                  onChange={(e) => update(index, { title: e.target.value })}
                  className="flex-grow px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none"
                />
                <button
                  onClick={() => move(index, -1)}
                  className="text-gray-400 hover:text-gray-600 px-1"
                  title="Move up"
                >
                  <i className="fas fa-chevron-up text-xs" />
                </button>
                <button
                  onClick={() => move(index, 1)}
                  className="text-gray-400 hover:text-gray-600 px-1"
                  title="Move down"
                >
                  <i className="fas fa-chevron-down text-xs" />
                </button>
                <button
                  onClick={() => remove(index)}
                  className="text-red-500 hover:text-red-700 px-1"
                  title="Remove"
                >
                  <i className="fas fa-times text-xs" />
                </button>
              </div>
              <div className="flex gap-2 items-center text-xs">
                <select
                  value={widget.kind}
                  onChange={(e) => update(index, { kind: e.target.value })}
                  className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white"
                >
                  {kindsFor(widget.metric).map((k) => (
                    <option key={k} value={k}>
                      {k.replace("_", " ")}
                    </option>
                  ))}
                </select>
                <select
                  value={widget.width}
                  onChange={(e) =>
                    update(index, { width: Number(e.target.value) })
                  }
                  className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white"
                >
                  {[1, 2, 3, 4].map((w) => (
                    <option key={w} value={w}>
                      {w} column{w > 1 ? "s" : ""}
                    </option>
                  ))}
                </select>
                <span className="text-gray-400 font-mono">{widget.metric}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={build}
          disabled={busy || !name.trim() || widgets.length === 0}
          className="px-4 py-2 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium rounded-lg"
        >
          {busy ? "Building…" : "Build dashboard"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:underline"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
