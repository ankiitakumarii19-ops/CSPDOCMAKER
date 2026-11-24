"use client";

/**
 * Setup — Settings (No. 204, Stage 1 of the configurable product plan)
 *
 * Every timing, limit and switch this workspace's Super Admin may choose for
 * themselves, in groups, with the standard (Eko's) value beside each. Saving
 * first shows what changes; every change goes into the history, where it
 * can be undone. The Super Admin can hand a group to Admins. The server
 * checks every value; the checks here only save a round trip.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  SettingChange,
  SettingsSheetChange,
  SettingValue,
  WorkspaceSettingItem,
  WorkspaceSettingsView,
} from "../lib/api";

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";
const input =
  "px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-eko disabled:opacity-60";
const btn = "px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50";

function show(s: WorkspaceSettingItem, v: SettingValue): string {
  if (s.kind === "bool") return v ? "On" : "Off";
  if (s.kind === "int" && s.unit) return `${v} ${s.unit}`;
  return String(v);
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const VIA: Record<string, string> = {
  sheet: "from the settings sheet",
  screen: "on this screen",
  chat: "by chat",
  undo: "undo",
  standard: "back to standard",
};

function SettingRow({
  s,
  onSaved,
}: {
  s: WorkspaceSettingItem;
  onSaved: (msg: string) => void;
}) {
  const [draft, setDraft] = useState<SettingValue>(s.value);
  const [confirming, setConfirming] = useState<"save" | "standard" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const edited = draft !== s.value;

  function localProblem(): string {
    if (s.kind === "int") {
      const n = Number(draft);
      if (!Number.isInteger(n)) return "Give a whole number.";
      if (s.min !== null && n < s.min) return `At least ${s.min}.`;
      if (s.max !== null && n > s.max) return `At most ${s.max}.`;
    }
    if (s.kind === "text" && !String(draft).trim()) return "Cannot be empty.";
    return "";
  }

  async function run(what: "save" | "standard") {
    setBusy(true);
    setError("");
    try {
      const out =
        what === "save"
          ? await api.changeSetting(s.key, s.kind === "int" ? Number(draft) : draft)
          : await api.settingToStandard(s.key);
      setConfirming(null);
      onSaved(
        out.unchanged
          ? `${s.label}: nothing changed.`
          : `Saved: ${s.label} is now ${out.value_text}.`
      );
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const problem = edited ? localProblem() : "";

  return (
    <div className="py-4 border-t border-gray-100 dark:border-gray-700 first:border-t-0">
      <div className="flex flex-col md:flex-row md:items-start gap-3">
        <div className="md:w-1/2 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-gray-900 dark:text-white">{s.label}</span>
            {s.changed && (
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                Changed
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{s.help}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Standard (Eko&apos;s) value: <strong>{s.standard_text}</strong>
            {s.own && s.changed_by && (
              <>
                {" "}
                · set by {s.changed_by} {when(s.changed_at)}
              </>
            )}
          </p>
        </div>
        <div className="md:w-1/2 flex flex-wrap items-center gap-2">
          {s.kind === "bool" ? (
            <label className="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={Boolean(draft)}
                disabled={!s.can_change || busy}
                onChange={(e) => setDraft(e.target.checked)}
              />
              {draft ? "On" : "Off"}
            </label>
          ) : s.kind === "choice" ? (
            <select
              className={input}
              value={String(draft)}
              disabled={!s.can_change || busy}
              onChange={(e) => setDraft(e.target.value)}
            >
              {s.choices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          ) : s.kind === "int" ? (
            <>
              <input
                type="number"
                className={`${input} w-28`}
                min={s.min ?? undefined}
                max={s.max ?? undefined}
                value={String(draft)}
                disabled={!s.can_change || busy}
                onChange={(e) => setDraft(e.target.value === "" ? "" : Number(e.target.value))}
              />
              <span className="text-sm text-gray-500">{s.unit}</span>
            </>
          ) : (
            <input
              className={`${input} w-full sm:w-64`}
              value={String(draft)}
              maxLength={s.max ?? undefined}
              disabled={!s.can_change || busy}
              onChange={(e) => setDraft(e.target.value)}
            />
          )}
          {s.can_change && edited && !confirming && (
            <button
              className={`${btn} bg-eko hover:bg-eko-dark text-white`}
              disabled={busy || Boolean(problem)}
              onClick={() => setConfirming("save")}
            >
              Save…
            </button>
          )}
          {s.can_change && edited && !confirming && (
            <button
              className={`${btn} text-gray-600 dark:text-gray-300 hover:underline`}
              onClick={() => setDraft(s.value)}
            >
              Cancel
            </button>
          )}
          {s.can_change && s.own && !edited && !confirming && (
            <button
              className={`${btn} text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600`}
              onClick={() => setConfirming("standard")}
              title="Use the standard (Eko's) value again"
            >
              Back to standard
            </button>
          )}
          {!s.can_change && (
            <span className="text-xs text-gray-400">
              <i className="fas fa-lock mr-1"></i>Super Admin only
            </span>
          )}
        </div>
      </div>
      {problem && <div className="text-xs text-red-600 dark:text-red-400 mt-1 md:ml-[50%]">{problem}</div>}
      {confirming && (
        <div className="mt-3 rounded-lg border border-eko/40 bg-eko/5 p-3 text-sm text-gray-800 dark:text-gray-100">
          <div>
            <strong>{s.label}</strong>: {s.value_text} →{" "}
            <strong>{confirming === "save" ? show(s, s.kind === "int" ? Number(draft) : draft) : s.standard_text}</strong>
          </div>
          <div className="text-xs text-gray-600 dark:text-gray-300 mt-1">What this changes: {s.effect}</div>
          <div className="flex gap-2 mt-2">
            <button
              className={`${btn} bg-eko hover:bg-eko-dark text-white`}
              disabled={busy}
              onClick={() => run(confirming)}
            >
              {busy ? "Saving…" : "Yes, save"}
            </button>
            <button
              className={`${btn} text-gray-600 dark:text-gray-300 hover:underline`}
              disabled={busy}
              onClick={() => setConfirming(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && <div className="text-xs text-red-600 dark:text-red-400 mt-2">{error}</div>}
    </div>
  );
}

export default function Settings() {
  const [view, setView] = useState<WorkspaceSettingsView | null>(null);
  const [changes, setChanges] = useState<SettingChange[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [busyGroup, setBusyGroup] = useState("");
  const [undoing, setUndoing] = useState<number | null>(null);
  // ZU-07 (No. 215): the settings sheet uploaded, and what it would change.
  const [sheetFile, setSheetFile] = useState<File | null>(null);
  const [sheetChanges, setSheetChanges] = useState<SettingsSheetChange[] | null>(null);
  const [sheetBusy, setSheetBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, h] = await Promise.all([api.workspaceSettings(), api.settingHistory()]);
      setView(v);
      setChanges(h.changes);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the settings.");
    }
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([api.workspaceSettings(), api.settingHistory()])
      .then(([v, h]) => {
        if (!alive) return;
        setView(v);
        setChanges(h.changes);
      })
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the settings."));
    return () => {
      alive = false;
    };
  }, []);

  const visible = useMemo(() => {
    if (!view) return [];
    const q = query.trim().toLowerCase();
    return view.settings.filter(
      (s) =>
        (!onlyChanged || s.changed) &&
        (!q || `${s.label} ${s.help} ${s.unit}`.toLowerCase().includes(q))
    );
  }, [view, query, onlyChanged]);

  async function saved(msg: string) {
    setMessage(msg);
    await load();
  }

  async function toggleGroup(key: string, on: boolean) {
    if (!view) return;
    const now = view.groups.filter((g) => g.admins_may_change).map((g) => g.key);
    const next = on ? [...now, key] : now.filter((k) => k !== key);
    setBusyGroup(key);
    try {
      await api.setSettingsAdminGroups(next);
      await saved(on ? "Admins may now change this group." : "Only you can change this group now.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusyGroup("");
    }
  }

  async function downloadSheet() {
    setSheetBusy(true);
    try {
      const blob = await api.settingsSheet();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Settings - ${view?.workspace?.name ?? "workspace"}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as ApiError).detail || "Could not download.");
    } finally {
      setSheetBusy(false);
    }
  }

  async function checkSheet(file: File) {
    setSheetBusy(true);
    setError("");
    try {
      const out = await api.uploadSettingsSheet(file, false);
      setSheetFile(file);
      setSheetChanges(out.changes);
    } catch (e) {
      setError((e as ApiError).detail || "Could not read that file.");
    } finally {
      setSheetBusy(false);
    }
  }

  async function applySheet() {
    if (!sheetFile) return;
    setSheetBusy(true);
    try {
      const out = await api.uploadSettingsSheet(sheetFile, true);
      setSheetChanges(null);
      setSheetFile(null);
      await saved(`Saved ${out.applied.length} change(s) from the sheet.`);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setSheetBusy(false);
    }
  }

  async function undo(c: SettingChange) {
    setUndoing(c.id);
    try {
      const out = await api.undoSettingChange(c.id);
      await saved(`Undone: ${out.label} is now ${out.value_text}.`);
    } catch (e) {
      setError((e as ApiError).detail || "Could not undo.");
    } finally {
      setUndoing(null);
    }
  }

  if (!view) {
    return (
      <div className="text-sm text-gray-500">
        {error ? (
          <span className="text-red-600 dark:text-red-400">{error}</span>
        ) : (
          <>
            <i className="fas fa-circle-notch fa-spin mr-2"></i>Loading…
          </>
        )}
      </div>
    );
  }

  const changedCount = view.settings.filter((s) => s.changed).length;
  const canChangeAny = view.settings.some((s) => s.can_change);

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Settings</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          How <strong>{view.workspace?.name ?? "this workspace"}</strong> works: timings, limits and
          switches. {view.note}
          {!canChangeAny && " You can see them; the Super Admin changes them."}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          You can also change a setting in the chat, e.g. <em>set feedback delay to 30 minutes</em>.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
          disabled={sheetBusy}
          onClick={downloadSheet}
        >
          <i className="fas fa-file-excel mr-1"></i>Download settings (Excel)
        </button>
        {canChangeAny && (
          <label className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 cursor-pointer`}>
            <i className="fas fa-upload mr-1"></i>Upload changed settings
            <input
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) checkSheet(f);
              }}
            />
          </label>
        )}
      </div>
      {sheetChanges && (
        <section className="rounded-xl border border-eko/40 bg-eko/5 p-4 space-y-2">
          <h3 className="text-sm font-bold text-gray-900 dark:text-white">
            {sheetChanges.length === 0 ? "The sheet changes nothing." : "The sheet would change:"}
          </h3>
          {sheetChanges.map((c, i) => (
            <div key={`${c.key}:${i}`} className="text-sm text-gray-800 dark:text-gray-100">
              <strong>{c.label}</strong>
              {c.now || c.new ? `: ${c.now} → ${c.new}` : ""}
              {c.problem && <span className="text-red-600 dark:text-red-400"> — refused: {c.problem}</span>}
            </div>
          ))}
          <div className="flex gap-2 pt-1">
            {sheetChanges.some((c) => !c.problem && c.key) && (
              <button className={`${btn} bg-eko hover:bg-eko-dark text-white`} disabled={sheetBusy} onClick={applySheet}>
                Save these changes
              </button>
            )}
            <button
              className={`${btn} text-gray-600 dark:text-gray-300 hover:underline`}
              onClick={() => {
                setSheetChanges(null);
                setSheetFile(null);
              }}
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
        <input
          className={`${input} w-full sm:w-80`}
          placeholder="Search settings…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
          Only changed ({changedCount})
        </label>
      </div>

      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div className="text-sm text-eko-dark dark:text-eko">{message}</div>}

      {view.groups.map((g) => {
        const items = visible.filter((s) => s.group === g.key);
        if (items.length === 0) return null;
        return (
          <section key={g.key} className={card}>
            <div className="px-5 pt-4 pb-2 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
              <div>
                <h3 className="text-base font-bold text-gray-900 dark:text-white">{g.title}</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">{g.about}</p>
              </div>
              {view.is_owner ? (
                <label className="inline-flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300 shrink-0">
                  <input
                    type="checkbox"
                    checked={g.admins_may_change}
                    disabled={busyGroup === g.key}
                    onChange={(e) => toggleGroup(g.key, e.target.checked)}
                  />
                  Admins may change this group
                </label>
              ) : (
                g.admins_may_change && (
                  <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">Admins may change this group</span>
                )
              )}
            </div>
            <div className="px-5 pb-2">
              {items.map((s) => (
                <SettingRow key={`${s.key}:${String(s.value)}`} s={s} onSaved={saved} />
              ))}
            </div>
          </section>
        );
      })}
      {visible.length === 0 && <div className="text-sm text-gray-500">No setting matches.</div>}

      <section className={card}>
        <div className="px-5 pt-4 pb-2">
          <h3 className="text-base font-bold text-gray-900 dark:text-white">History</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Every change, newest first. Undo puts a setting back to what it was before that change.
          </p>
        </div>
        <div className="px-5 pb-4">
          {changes.length === 0 && <div className="text-sm text-gray-500 py-2">Nothing changed yet.</div>}
          {changes.map((c) => {
            const s = view.settings.find((x) => x.key === c.key);
            return (
              <div
                key={c.id}
                className="py-2 border-t border-gray-100 dark:border-gray-700 first:border-t-0 flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3 text-sm"
              >
                <div className="flex-1 min-w-0 text-gray-800 dark:text-gray-100">
                  <strong>{c.label}</strong>: {c.before} → {c.after}
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {c.by} · {VIA[c.via] ?? c.via} · {when(c.at)}
                    {c.note ? ` · ${c.note}` : ""}
                  </div>
                </div>
                {c.can_undo && s?.can_change && (
                  <button
                    className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 self-start sm:self-auto`}
                    disabled={undoing === c.id}
                    onClick={() => undo(c)}
                  >
                    {undoing === c.id ? "Undoing…" : "Undo"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
