"use client";

/**
 * Settings → Appearance & Personalization (No. 240, SaaS upgrade Stage 2)
 *
 * Every signed-in person (RM, Admin, Super Admin) changes how the app looks
 * for THEMSELVES: light / dark, colours, font and sizes, layout and
 * accessibility. Saved to their own account (PUT /api/profile/appearance),
 * so it follows them to any computer and never reaches anyone else's screen.
 *
 * Every change shows at once on this page (live preview). Save keeps it;
 * "Undo changes" goes back to the last saved; "Back to the workspace look"
 * removes all their own choices. Leaving without saving puts the saved look
 * back. The choices offered come from the server (services/my_look.py),
 * which also refuses colours that would make text hard to read.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "../lib/api";
import type { ApiError } from "../lib/api";
import { applyMyLook, keepSavedLook, savedLook, WORKSPACE_LOCKABLE } from "../lib/myLook";
import type { Appearance, AppearanceOption } from "../lib/myLook";
import { useMyAccess } from "../lib/useMyAccess";
import { useSessionUser } from "../lib/useSessionUser";
import { useUrlParam } from "../lib/useUrlParam";
import MyNotifications from "./MyNotifications";

const TABS = [
  { key: "appearance", title: "Appearance & Personalization", icon: "fa-sliders-h" },
  { key: "notifications", title: "Notifications", icon: "fa-bell" },
];

const GROUPS: { key: AppearanceOption["group"]; title: string; icon: string; about: string }[] = [
  { key: "appearance", title: "Appearance", icon: "fa-palette",
    about: "Light or dark, and your own colours. Empty = the workspace's colour." },
  { key: "typography", title: "Typography", icon: "fa-font",
    about: "The font and how big, heavy and spaced the text is." },
  { key: "layout", title: "Layout", icon: "fa-table-columns",
    about: "The side menu, spacing, card corners and table rows." },
  { key: "accessibility", title: "Accessibility", icon: "fa-universal-access",
    about: "Easier to see, calmer to use, and clear with a keyboard." },
];

const ADMIN_ROLES = ["admin", "super_admin"];

function same(a: Appearance, b: Appearance): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]) as Set<keyof Appearance>;
  for (const k of keys) if (a[k] !== b[k]) return false;
  return true;
}

function Pick({ option, value, onChange }: {
  option: AppearanceOption; value: unknown; onChange: (v: unknown) => void; workspaceColour?: string;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={option.label}>
      {(option.values ?? []).map((v) => {
        const on = value === v.value;
        return (
          <button
            key={v.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? null : v.value)}
            className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
              on
                ? "bg-eko text-white border-eko"
                : "bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 border-gray-200 dark:border-gray-600 hover:border-eko"
            }`}
          >
            {v.name}
          </button>
        );
      })}
    </div>
  );
}

function NumberChoice({ option, value, onChange }: {
  option: AppearanceOption; value: unknown; onChange: (v: unknown) => void; workspaceColour?: string;
}) {
  const shown = typeof value === "number" ? value : 100;
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={option.low}
        max={option.high}
        step={option.step}
        value={shown}
        aria-label={option.label}
        onChange={(e) => {
          const n = Number(e.target.value);
          onChange(n === 100 ? null : n);
        }}
        className="flex-1 accent-eko"
      />
      <span className="w-14 text-right text-sm tabular-nums text-gray-700 dark:text-gray-200">
        {shown}{option.unit}
      </span>
    </div>
  );
}

function Switch({ option, value, onChange }: {
  option: AppearanceOption; value: unknown; onChange: (v: unknown) => void; workspaceColour?: string;
}) {
  const on = value === true;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={option.label}
      onClick={() => onChange(on ? null : true)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
        on ? "bg-eko" : "bg-gray-300 dark:bg-gray-600"
      }`}
    >
      <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
        on ? "translate-x-5" : "translate-x-0.5"}`} />
    </button>
  );
}

/** The typed #rrggbb box; remounted (key) when the colour changes elsewhere. */
function HexBox({ label, hex, onChange }: { label: string; hex: string; onChange: (v: unknown) => void }) {
  const [typed, setTyped] = useState(hex);
  return (
    <input
      type="text"
      value={typed}
      placeholder="Workspace's"
      aria-label={`${label} as #rrggbb`}
      maxLength={7}
      onChange={(e) => {
        setTyped(e.target.value);
        if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) onChange(e.target.value.toLowerCase());
      }}
      className="w-28 px-2 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-mono"
    />
  );
}

// What each colour is when the person has not chosen one (the app's own;
// accent and buttons follow the workspace's colour).
const IN_USE: Record<string, string> = {
  background: "#f9fafb", menu: "#0f172a", card: "#ffffff", border: "#e5e7eb",
};

function ColourChoice({ option, value, onChange, workspaceColour }: {
  option: AppearanceOption; value: unknown; onChange: (v: unknown) => void; workspaceColour: string;
}) {
  const hex = typeof value === "string" ? value : "";
  const inUse = IN_USE[option.key] ?? workspaceColour;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        type="color"
        value={hex || inUse}
        aria-label={`${option.label} colour`}
        title={hex ? hex : `The workspace's (${inUse})`}
        onChange={(e) => onChange(e.target.value)}
        className={`h-9 w-12 rounded border border-gray-200 dark:border-gray-600 bg-transparent cursor-pointer ${
          hex ? "" : "opacity-60"}`}
      />
      <HexBox key={hex} label={option.label} hex={hex} onChange={onChange} />
      {hex && (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 underline"
        >
          Use the workspace&apos;s
        </button>
      )}
    </div>
  );
}

const CONTROLS = { pick: Pick, number: NumberChoice, switch: Switch, colour: ColourChoice };

function Preview() {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-gray-500">Preview</div>
      <h3 className="text-xl font-bold text-gray-900 dark:text-white">Documents this week</h3>
      <p className="text-sm text-gray-600 dark:text-gray-300">
        Everything on this page — and every screen once you save — follows your choices.
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <button type="button" className="px-4 py-2 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white">
          Save
        </button>
        <span className="text-xs px-2 py-0.5 rounded-full bg-eko-light text-eko-dark">Sent</span>
        <a className="text-sm text-eko underline inline" href="#preview" onClick={(e) => e.preventDefault()}>A link</a>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500">
            <tr><th className="text-left px-3 py-2">CSP</th><th className="text-left px-3 py-2">Status</th></tr>
          </thead>
          <tbody className="text-gray-700 dark:text-gray-200">
            <tr className="border-t border-gray-200 dark:border-gray-700"><td className="px-3 py-2">Sample CSP 1</td><td className="px-3 py-2">Documents sent</td></tr>
            <tr className="border-t border-gray-200 dark:border-gray-700"><td className="px-3 py-2">Sample CSP 2</td><td className="px-3 py-2">Waiting for details</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const user = useSessionUser();
  // The workspace's look first (and, under it, this person's saved one).
  const access = useMyAccess(Boolean(user));

  const [options, setOptions] = useState<AppearanceOption[] | null>(null);
  const [saved, setSaved] = useState<Appearance>({});
  const [draft, setDraft] = useState<Appearance>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  // No. 240 (Stage 3): the workspace may keep colours and font its own.
  const [ownColours, setOwnColours] = useState(true);
  const [tab, setTab] = useUrlParam("tab", "appearance");

  useEffect(() => {
    if (user === null) router.replace("/auth/login");
  }, [user, router]);

  useEffect(() => {
    if (!user) return;
    let alive = true;
    api
      .myAppearance()
      .then((v) => {
        if (!alive) return;
        setOptions(v.options);
        setOwnColours(v.own_colours_allowed !== false);
        setSaved(v.appearance);
        setDraft(v.appearance);
      })
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load your settings."));
    return () => {
      alive = false;
    };
  }, [user]);

  // Live preview: the whole page shows the draft.
  useEffect(() => {
    if (options) applyMyLook(draft);
  }, [draft, options]);
  // Leaving without saving: the saved look comes back.
  useEffect(() => () => applyMyLook(savedLook()), []);

  const changed = useMemo(() => !same(draft, saved), [draft, saved]);
  const ownCount = Object.keys(saved).length;

  const set = (key: keyof Appearance, value: unknown) => {
    setMessage("");
    setWarnings([]);
    setDraft((d) => {
      const next = { ...d } as Record<string, unknown>;
      if (value === null || value === undefined) delete next[key];
      else next[key] = value;
      return next as Appearance;
    });
  };

  async function save() {
    setBusy(true);
    setError("");
    try {
      const v = await api.saveAppearance(draft);
      keepSavedLook(v.appearance);
      setSaved(v.appearance);
      setDraft(v.appearance);
      setWarnings(v.warnings);
      setMessage("Saved. This is your look on every screen and computer — nobody else's changes.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Remove all your own choices and use the workspace's look again?")) return;
    setBusy(true);
    setError("");
    try {
      const v = await api.resetAppearance();
      keepSavedLook(v.appearance);
      setSaved(v.appearance);
      setDraft(v.appearance);
      setWarnings([]);
      setMessage("Back to the workspace's look.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not reset.");
    } finally {
      setBusy(false);
    }
  }

  const back = () => {
    const toAdmin = user && (ADMIN_ROLES.includes(user.role) || access?.admin_area);
    router.push(toAdmin ? "/admin" : "/rm");
  };

  if (!user) return null;

  return (
    <div className="flex flex-col h-full overflow-hidden bg-gray-50 dark:bg-navy-900">
      <header className="h-[calc(4rem+env(safe-area-inset-top))] pt-[env(safe-area-inset-top)] bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-3 px-3 sm:px-6 shrink-0">
        <button
          type="button"
          onClick={back}
          className="px-3 py-1.5 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
        >
          <i className="fas fa-arrow-left mr-2"></i>Back
        </button>
        <h1 className="text-lg font-bold text-gray-900 dark:text-white">Settings</h1>
      </header>

      <main id="main" className="flex-grow overflow-y-auto px-3 sm:px-6 lg:px-8 pt-4 lg:pt-8 pb-[calc(6rem+env(safe-area-inset-bottom))]">
        <div className="max-w-6xl mx-auto space-y-6">
          <nav className="flex gap-1 border-b border-gray-200 dark:border-gray-700 overflow-x-auto" role="tablist" aria-label="Settings sections">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => setTab(t.key === "appearance" ? null : t.key)}
                className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${
                  tab === t.key
                    ? "font-semibold text-eko border-eko"
                    : "text-gray-600 dark:text-gray-300 border-transparent hover:text-gray-900 dark:hover:text-white"}`}
              >
                <i className={`fas ${t.icon} mr-2`}></i>{t.title}
              </button>
            ))}
          </nav>

          {tab === "notifications" && <MyNotifications />}

          {tab !== "notifications" && (<>
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
            <div>
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">Your look</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Only for you, on every computer you sign in on. Anything you leave as it is follows the
                workspace{access?.look?.name ? ` (${access.look.name})` : ""}.
              </p>
            </div>
            {ownCount > 0 && (
              <button
                type="button"
                disabled={busy}
                onClick={reset}
                className="self-start px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
              >
                <i className="fas fa-rotate-left mr-2"></i>Back to the workspace look
              </button>
            )}
          </div>

          {error && (
            <div role="alert" className="text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
          {message && (
            <div role="status" className="text-sm text-eko-dark dark:text-eko bg-eko-light dark:bg-eko/10 rounded-lg px-3 py-2">
              {message}
            </div>
          )}
          {warnings.map((w) => (
            <div key={w} className="text-sm text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-3 py-2">
              {w}
            </div>
          ))}

          {!options && !error && (
            <div className="grid gap-4 lg:grid-cols-2" aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-48 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 animate-pulse" />
              ))}
            </div>
          )}

          {options && (
            <div className="grid gap-6 lg:grid-cols-[1fr_22rem] items-start">
              <div className="space-y-6">
                {GROUPS.map((g) => (
                  <section key={g.key} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
                    <div>
                      <h3 className="text-base font-bold text-gray-900 dark:text-white">
                        <i className={`fas ${g.icon} mr-2 text-eko`}></i>{g.title}
                      </h3>
                      <p className="text-xs text-gray-500 dark:text-gray-400">{g.about}</p>
                    </div>
                    {g.key === "appearance" && !ownColours && (
                      <p className="text-xs text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-3 py-2">
                        Your workspace sets the colours and font for everyone. Light / dark, sizes, layout and
                        accessibility are still yours.
                      </p>
                    )}
                    {options.filter((o) => o.group === g.key).map((o) => {
                      const Control = CONTROLS[o.kind];
                      const locked = !ownColours && (WORKSPACE_LOCKABLE as readonly string[]).includes(o.key);
                      if (locked) {
                        return (
                          <div key={o.key} className="grid gap-2 sm:grid-cols-[12rem_1fr] sm:items-center opacity-60">
                            <div className="text-sm font-medium text-gray-800 dark:text-gray-100">{o.label}</div>
                            <div className="text-xs text-gray-500 dark:text-gray-400">
                              <i className="fas fa-lock mr-1"></i>Set by your workspace
                            </div>
                          </div>
                        );
                      }
                      return (
                        <div key={o.key} className="grid gap-2 sm:grid-cols-[12rem_1fr] sm:items-center">
                          <div>
                            <div className="text-sm font-medium text-gray-800 dark:text-gray-100">{o.label}</div>
                            {o.help && <div className="text-xs text-gray-500 dark:text-gray-400">{o.help}</div>}
                          </div>
                          <Control
                            option={o}
                            value={draft[o.key]}
                            onChange={(v) => set(o.key, v)}
                            workspaceColour={/^#[0-9a-f]{6}$/i.test(access?.look?.color ?? "") ? access!.look.color : "#00b259"}
                          />
                        </div>
                      );
                    })}
                  </section>
                ))}
              </div>
              <div className="lg:sticky lg:top-0">
                <Preview />
              </div>
            </div>
          )}
          </>)}
        </div>
      </main>

      {options && changed && (
        <div className="sticky bottom-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 px-3 sm:px-6 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] flex flex-wrap items-center justify-end gap-3 z-10">
          <span className="text-sm text-gray-600 dark:text-gray-300 mr-auto">You are seeing a preview — not saved yet.</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setDraft(saved);
              setMessage("");
              setWarnings([]);
              setError("");
            }}
            className="px-4 py-2 rounded-lg text-sm border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Undo changes
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={save}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
