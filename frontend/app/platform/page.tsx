"use client";

/**
 * The Supreme Owner's console (No. 240, SaaS upgrade Stage 6) — /platform
 *
 * Above every workspace: totals, health, each workspace's usage and plan,
 * suspend / reactivate, plans, announcements. Only for the platform's
 * Supreme Owner (server setting SUPREME_OWNER_EMAILS); a workspace's own
 * Super Admin is refused by the server, and this page sends them back.
 *
 * Counts and health only: nothing here shows a CSP's details, a document,
 * a photo or a message. Nothing is charged: prices are for information.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "../lib/api";
import type {
  ApiError,
  PlatformAnnouncement,
  PlatformOverview,
  PlatformPlan,
  PlatformWorkspace,
} from "../lib/api";
import { useMyAccess } from "../lib/useMyAccess";
import { useSessionUser } from "../lib/useSessionUser";
import { useUrlParam } from "../lib/useUrlParam";

const TABS = [
  { key: "overview", title: "Overview", icon: "fa-gauge" },
  { key: "workspaces", title: "Workspaces", icon: "fa-building" },
  { key: "plans", title: "Plans", icon: "fa-layer-group" },
  { key: "announcements", title: "Announcements", icon: "fa-bullhorn" },
];
const STATUSES = ["trial", "active", "past_due", "cancelled", "unlimited"];

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";
const input = "px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm";
const btn = "px-3 py-1.5 rounded-lg text-sm disabled:opacity-50";

function bytes(n: number | undefined): string {
  const v = n ?? 0;
  if (v < 1024 * 1024) return `${Math.round(v / 1024)} KB`;
  if (v < 1024 * 1024 * 1024) return `${(v / 1024 / 1024).toFixed(1)} MB`;
  return `${(v / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function n(v: number | undefined | null): string {
  return (v ?? 0).toLocaleString("en-IN");
}

function Tile({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "bad" }) {
  return (
    <div className={`${card} p-4`}>
      <div className="text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${tone === "bad" ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-white"}`}>
        {value}
      </div>
      {note && <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{note}</div>}
    </div>
  );
}

function Overview({ data }: { data: PlatformOverview }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Tile label="Workspaces" value={n(data.workspaces)} note={`${n(data.active_workspaces)} active · ${n(data.inactive_workspaces)} off`} />
        <Tile label="People" value={n(data.people)} note="Active members, counted once" />
        <Tile label="Documents" value={n(data.documents)} note={`${n(data.documents_this_month)} this month`} />
        <Tile label="Storage" value={bytes(data.storage_bytes)} note="Documents, photos, templates, logos" />
        <Tile label="Failed generations" value={n(data.failed_generations)} tone={data.failed_generations ? "bad" : undefined} note="Jobs that stopped making or converting a document" />
        <Tile label="WhatsApp failed, 24 h" value={n(data.whatsapp_failed_24h)} tone={data.whatsapp_failed_24h ? "bad" : undefined} />
        <Tile label="Email failed, 24 h" value={n(data.email_failed_24h)} tone={data.email_failed_24h ? "bad" : undefined} />
      </div>
      <section className={`${card} p-5`}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white mb-3">System health</h3>
        <ul className="grid gap-2 sm:grid-cols-3">
          {Object.entries(data.health).map(([k, v]) => (
            <li key={k} className="flex items-center gap-2 text-sm">
              <span className={`w-2.5 h-2.5 rounded-full ${v === "ok" ? "bg-green-500" : "bg-amber-500"}`} aria-hidden />
              <span className="capitalize text-gray-700 dark:text-gray-200">{k}</span>
              <span className="text-gray-500 dark:text-gray-400">— {v}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SubscriptionEditor({
  ws,
  plans,
  onSaved,
  onCancel,
}: {
  ws: PlatformWorkspace;
  plans: PlatformPlan[];
  onSaved: (rows: PlatformWorkspace[]) => void;
  onCancel: () => void;
}) {
  const [plan, setPlan] = useState(ws.subscription?.plan_key ?? plans[0]?.key ?? "unlimited");
  const [status, setStatus] = useState(ws.subscription?.status ?? "active");
  const [trial, setTrial] = useState(ws.subscription?.trial_ends_at?.slice(0, 10) ?? "");
  const [domain, setDomain] = useState(ws.subscription?.custom_domain ?? "");
  const [whiteLabel, setWhiteLabel] = useState(ws.subscription?.white_label ?? false);
  const [notes, setNotes] = useState(ws.subscription?.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      const r = await api.platformSetSubscription(ws.id, {
        plan_key: plan,
        status,
        trial_ends_at: trial ? `${trial}T23:59:59+05:30` : null,
        custom_domain: domain.trim() || null,
        white_label: whiteLabel,
        notes: notes.trim() || null,
      });
      onSaved(r.workspaces);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-900/40">
      <label className="text-sm text-gray-700 dark:text-gray-200 grid gap-1">
        Plan
        <select className={input} value={plan} onChange={(e) => setPlan(e.target.value)}>
          {plans.map((p) => (
            <option key={p.key} value={p.key}>{p.name}</option>
          ))}
        </select>
      </label>
      <label className="text-sm text-gray-700 dark:text-gray-200 grid gap-1">
        Status
        <select className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s.replace("_", " ")}</option>
          ))}
        </select>
      </label>
      <label className="text-sm text-gray-700 dark:text-gray-200 grid gap-1">
        Trial ends
        <input type="date" className={input} value={trial} onChange={(e) => setTrial(e.target.value)} />
      </label>
      <label className="text-sm text-gray-700 dark:text-gray-200 grid gap-1">
        Own web address (later)
        <input className={input} value={domain} placeholder="docs.example.com" onChange={(e) => setDomain(e.target.value)} />
      </label>
      <label className="text-sm text-gray-700 dark:text-gray-200 flex items-center gap-2 mt-6">
        <input type="checkbox" checked={whiteLabel} onChange={(e) => setWhiteLabel(e.target.checked)} />
        White-label (later)
      </label>
      <label className="text-sm text-gray-700 dark:text-gray-200 grid gap-1">
        Notes
        <input className={input} value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {error && <div role="alert" className="sm:col-span-2 lg:col-span-3 text-sm text-red-600 dark:text-red-400">{error}</div>}
      <div className="sm:col-span-2 lg:col-span-3 flex gap-2 justify-end">
        <button type="button" className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" disabled={busy} className={`${btn} bg-eko hover:bg-eko-dark text-white font-semibold`} onClick={save}>
          {busy ? "Saving…" : "Save plan"}
        </button>
      </div>
    </div>
  );
}

function Workspaces({
  rows,
  plans,
  setRows,
}: {
  rows: PlatformWorkspace[];
  plans: PlatformPlan[];
  setRows: (rows: PlatformWorkspace[]) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  async function onOff(ws: PlatformWorkspace) {
    const turningOn = !ws.active;
    if (!window.confirm(turningOn
      ? `Switch “${ws.name}” back on? Its people can sign in again.`
      : `Suspend “${ws.name}”? Its people cannot sign in and its jobs stop until you switch it back on. Nothing is deleted.`))
      return;
    setBusy(true);
    setError("");
    try {
      await api.platformSuspend(ws.id, turningOn);
      setRows((await api.platformWorkspaces()).workspaces);
    } catch (e) {
      setError((e as ApiError).detail || "Could not change it.");
    } finally {
      setBusy(false);
    }
  }

  const shown = rows.filter((w) => !query.trim() || `${w.name} ${w.slug} ${w.owner_email}`.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <div className="space-y-4">
      <input
        className={`${input} w-full sm:w-80`}
        placeholder="Find a workspace"
        aria-label="Find a workspace"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {shown.length === 0 && <p className="text-sm text-gray-500">No workspace matches.</p>}
      <div className="space-y-3">
        {shown.map((w) => (
          <div key={w.id} className={`${card} p-4`}>
            <div className="flex flex-col lg:flex-row lg:items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-gray-900 dark:text-white">{w.name}</span>
                  {w.is_eko && <span className="text-xs px-2 py-0.5 rounded-full bg-eko-light text-eko-dark">original</span>}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${w.active ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" : "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`}>
                    {w.active ? "Active" : "Suspended"}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                    {w.subscription
                      ? w.subscription.status.toLowerCase() === w.subscription.plan_name.toLowerCase()
                        ? w.subscription.plan_name
                        : `${w.subscription.plan_name} · ${w.subscription.status.replace("_", " ")}`
                      : "No plan (no limits)"}
                  </span>
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 break-all">
                  {w.slug} · owner {w.owner_email}
                  {w.created_at ? ` · since ${new Date(w.created_at).toLocaleDateString("en-IN")}` : ""}
                </div>
                <dl className="mt-3 grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-x-4 gap-y-2 text-sm">
                  <div><dt className="text-xs text-gray-500">People</dt><dd className="tabular-nums">{n(w.usage.people)}{w.subscription?.limits?.max_users ? ` / ${w.subscription.limits.max_users}` : ""}</dd></div>
                  <div><dt className="text-xs text-gray-500">Records</dt><dd className="tabular-nums">{n(w.usage.records)}</dd></div>
                  <div><dt className="text-xs text-gray-500">Documents this month</dt><dd className="tabular-nums">{n(w.usage.documents_this_month)}{w.subscription?.limits?.max_documents_month ? ` / ${w.subscription.limits.max_documents_month}` : ""}</dd></div>
                  <div><dt className="text-xs text-gray-500">Storage</dt><dd className="tabular-nums">{bytes(w.usage.storage_bytes)}{w.subscription?.limits?.max_storage_mb ? ` / ${w.subscription.limits.max_storage_mb} MB` : ""}</dd></div>
                  <div><dt className="text-xs text-gray-500">Last sheet read</dt><dd>{w.health.last_sheet_read}</dd></div>
                  <div>
                    <dt className="text-xs text-gray-500">Failures</dt>
                    <dd className={(w.health.failed_generations || w.health.whatsapp_failed_24h || w.health.email_failed_24h) ? "text-red-600 dark:text-red-400" : ""}>
                      {n(w.health.failed_generations)} docs · {n(w.health.whatsapp_failed_24h)} WA · {n(w.health.email_failed_24h)} email
                    </dd>
                  </div>
                </dl>
              </div>
              <div className="flex gap-2 shrink-0">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setEditing(editing === w.id ? null : w.id)}
                  className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
                >
                  Plan
                </button>
                {!w.is_eko && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onOff(w)}
                    className={`${btn} ${w.active ? "border border-red-300 text-red-700 dark:border-red-800 dark:text-red-300" : "bg-eko hover:bg-eko-dark text-white"}`}
                  >
                    {w.active ? "Suspend" : "Reactivate"}
                  </button>
                )}
              </div>
            </div>
            {editing === w.id && (
              <SubscriptionEditor
                ws={w}
                plans={plans}
                onCancel={() => setEditing(null)}
                onSaved={(r) => {
                  setRows(r);
                  setEditing(null);
                }}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const EMPTY_PLAN = { name: "", description: "", price: "", docs: "", storage: "", users: "", trial: "" };

function Plans({ plans, note, reload }: { plans: PlatformPlan[]; note: string; reload: () => Promise<void> }) {
  const [form, setForm] = useState(EMPTY_PLAN);
  const [editKey, setEditKey] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const num = (v: string) => (v.trim() === "" ? null : Math.max(0, Math.round(Number(v))));

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.platformSavePlan({
        name: form.name.trim(),
        description: form.description.trim() || null,
        price_monthly_paise: form.price.trim() === "" ? null : Math.round(Number(form.price) * 100),
        max_documents_month: num(form.docs),
        max_storage_mb: num(form.storage),
        max_users: num(form.users),
        trial_days: num(form.trial),
      }, editKey);
      setForm(EMPTY_PLAN);
      setEditKey(undefined);
      await reload();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the plan.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Limits apply only to workspaces you put on a plan; blank or 0 = no limit. {note}.
      </p>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500 bg-gray-50 dark:bg-gray-900/40">
            <tr>
              <th className="px-3 py-2">Plan</th>
              <th className="px-3 py-2">Price / month</th>
              <th className="px-3 py-2">Documents / month</th>
              <th className="px-3 py-2">Storage</th>
              <th className="px-3 py-2">People</th>
              <th className="px-3 py-2">Trial</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {plans.map((p) => (
              <tr key={p.key}>
                <td className="px-3 py-2"><div className="font-medium text-gray-900 dark:text-white">{p.name}</div><div className="text-xs text-gray-500">{p.description}</div></td>
                <td className="px-3 py-2 tabular-nums">{p.price_monthly_paise == null ? "—" : `${p.currency} ${(p.price_monthly_paise / 100).toLocaleString("en-IN")}`}</td>
                <td className="px-3 py-2 tabular-nums">{p.max_documents_month || "No limit"}</td>
                <td className="px-3 py-2 tabular-nums">{p.max_storage_mb ? `${p.max_storage_mb} MB` : "No limit"}</td>
                <td className="px-3 py-2 tabular-nums">{p.max_users || "No limit"}</td>
                <td className="px-3 py-2 tabular-nums">{p.trial_days ? `${p.trial_days} days` : "—"}</td>
                <td className="px-3 py-2 text-right">
                  {p.key !== "unlimited" && (
                    <button
                      type="button"
                      className="text-eko text-sm"
                      onClick={() => {
                        setEditKey(p.key);
                        setForm({
                          name: p.name,
                          description: p.description ?? "",
                          price: p.price_monthly_paise == null ? "" : String(p.price_monthly_paise / 100),
                          docs: p.max_documents_month ? String(p.max_documents_month) : "",
                          storage: p.max_storage_mb ? String(p.max_storage_mb) : "",
                          users: p.max_users ? String(p.max_users) : "",
                          trial: p.trial_days ? String(p.trial_days) : "",
                        });
                      }}
                    >
                      Change
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section className={`${card} p-4 space-y-3`}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">{editKey ? "Change plan" : "New plan"}</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {([
            ["name", "Name", "e.g. Starter"],
            ["description", "About", "Who it is for"],
            ["price", "Price a month (₹, information only)", "e.g. 999"],
            ["docs", "Documents a month", "blank = no limit"],
            ["storage", "Storage (MB)", "blank = no limit"],
            ["users", "People", "blank = no limit"],
            ["trial", "Trial days", "e.g. 14"],
          ] as const).map(([key, label, hint]) => (
            <label key={key} className="text-sm text-gray-700 dark:text-gray-200 grid gap-1">
              {label}
              <input
                className={input}
                value={form[key]}
                placeholder={hint}
                inputMode={key === "name" || key === "description" ? "text" : "numeric"}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
        <div className="flex gap-2 justify-end">
          {editKey && (
            <button type="button" className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`} onClick={() => { setEditKey(undefined); setForm(EMPTY_PLAN); }}>
              Cancel
            </button>
          )}
          <button type="button" disabled={busy || form.name.trim().length < 2} onClick={save} className={`${btn} bg-eko hover:bg-eko-dark text-white font-semibold`}>
            {busy ? "Saving…" : editKey ? "Save plan" : "Add plan"}
          </button>
        </div>
      </section>
    </div>
  );
}

function Announcements({ rows, workspaces, reload }: { rows: PlatformAnnouncement[]; workspaces: PlatformWorkspace[]; reload: () => Promise<void> }) {
  const [message, setMessage] = useState("");
  const [level, setLevel] = useState("info");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function post() {
    setBusy(true);
    setError("");
    try {
      await api.platformAnnounce({ message, level, workspace_id: target || null });
      setMessage("");
      await reload();
    } catch (e) {
      setError((e as ApiError).detail || "Could not post it.");
    } finally {
      setBusy(false);
    }
  }

  async function end(a: PlatformAnnouncement) {
    if (!window.confirm("End this announcement? It disappears from everyone's screen.")) return;
    setBusy(true);
    try {
      await api.platformEndAnnouncement(a.id);
      await reload();
    } catch (e) {
      setError((e as ApiError).detail || "Could not end it.");
    } finally {
      setBusy(false);
    }
  }

  const name = (id: string | null) => (id ? workspaces.find((w) => w.id === id)?.name ?? "one workspace" : "Every workspace");
  return (
    <div className="space-y-4">
      <section className={`${card} p-4 space-y-3`}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">New announcement</h3>
        <textarea
          className={`${input} w-full`}
          rows={2}
          maxLength={500}
          placeholder="e.g. The app will be updated on Sunday at 10 pm for 15 minutes."
          aria-label="Announcement"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <div className="flex flex-col sm:flex-row gap-2">
          <select className={input} value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Kind">
            <option value="info">Information</option>
            <option value="warning">Warning</option>
          </select>
          <select className={input} value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Who sees it">
            <option value="">Every workspace</option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>
          <button type="button" disabled={busy || message.trim().length < 3} onClick={post} className={`${btn} bg-eko hover:bg-eko-dark text-white font-semibold sm:ml-auto`}>
            Post
          </button>
        </div>
        {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      </section>
      {rows.length === 0 && <p className="text-sm text-gray-500">No announcements yet.</p>}
      <ul className="space-y-2">
        {rows.map((a) => (
          <li key={a.id} className={`${card} p-3 flex flex-col sm:flex-row sm:items-center gap-2 ${a.active ? "" : "opacity-60"}`}>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-gray-900 dark:text-white">{a.message}</div>
              <div className="text-xs text-gray-500">
                {a.level === "warning" ? "Warning" : "Information"} · {name(a.workspace_id)} ·{" "}
                {a.created_at ? new Date(a.created_at).toLocaleString("en-IN") : ""} · {a.active ? "showing" : "ended"}
              </div>
            </div>
            {a.active && (
              <button type="button" disabled={busy} onClick={() => end(a)} className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}>
                End
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PlatformPage() {
  const router = useRouter();
  const user = useSessionUser();
  useMyAccess(Boolean(user));
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [tab, setTab] = useUrlParam("tab", "overview");
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [rows, setRows] = useState<PlatformWorkspace[]>([]);
  const [plans, setPlans] = useState<PlatformPlan[]>([]);
  const [note, setNote] = useState("");
  const [announcements, setAnnouncements] = useState<PlatformAnnouncement[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (user === null) router.replace("/auth/login");
  }, [user, router]);

  const load = useCallback(async () => {
    try {
      const [o, w, p, a] = await Promise.all([
        api.platformOverview(),
        api.platformWorkspaces(),
        api.platformPlans(),
        api.platformAnnouncements(),
      ]);
      setOverview(o);
      setRows(w.workspaces);
      setPlans(p.plans);
      setNote(p.payment_gateway);
      setAnnouncements(a.announcements);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the console.");
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let alive = true;
    api
      .mePlatform()
      .then((r) => {
        if (!alive) return;
        setAllowed(r.supreme_owner);
        if (r.supreme_owner) void load();
      })
      .catch(() => alive && setAllowed(false));
    return () => {
      alive = false;
    };
  }, [user, load]);

  if (!user) return null;

  return (
    <div className="flex flex-col h-full overflow-hidden bg-gray-50 dark:bg-navy-900">
      <header className="h-[calc(4rem+env(safe-area-inset-top))] pt-[env(safe-area-inset-top)] bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-3 px-3 sm:px-6 shrink-0">
        <button
          type="button"
          onClick={() => router.push(["admin", "super_admin"].includes(user.role) ? "/admin" : "/rm")}
          className="px-3 py-1.5 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
        >
          <i className="fas fa-arrow-left mr-2"></i>Back
        </button>
        <h1 className="text-lg font-bold text-gray-900 dark:text-white">Supreme Owner console</h1>
      </header>
      <main className="flex-grow overflow-y-auto px-3 sm:px-6 lg:px-8 pt-4 lg:pt-8 pb-[calc(6rem+env(safe-area-inset-bottom))]">
        <div className="max-w-7xl mx-auto space-y-6">
          {allowed === null && <p className="text-sm text-gray-500">Checking…</p>}
          {allowed === false && (
            <div role="alert" className={`${card} p-6 text-sm text-gray-700 dark:text-gray-200`}>
              <i className="fas fa-lock mr-2 text-gray-400"></i>
              Only the platform&apos;s Supreme Owner may open this console. A workspace&apos;s Super Admin manages their
              own workspace from Setup.
            </div>
          )}
          {allowed && (
            <>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Every workspace at a glance — counts and health only. No CSP&apos;s details, documents or messages are
                shown here.
              </p>
              <nav className="flex gap-1 border-b border-gray-200 dark:border-gray-700 overflow-x-auto" role="tablist" aria-label="Console sections">
                {TABS.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    role="tab"
                    aria-selected={tab === t.key}
                    onClick={() => setTab(t.key === "overview" ? null : t.key)}
                    className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${
                      tab === t.key ? "font-semibold text-eko border-eko" : "text-gray-600 dark:text-gray-300 border-transparent"}`}
                  >
                    <i className={`fas ${t.icon} mr-2`}></i>{t.title}
                  </button>
                ))}
              </nav>
              {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
              {!overview && !error && (
                <div className="grid gap-4 grid-cols-2 lg:grid-cols-4" aria-busy="true">
                  {[0, 1, 2, 3].map((i) => <div key={i} className={`${card} h-24 animate-pulse`} />)}
                </div>
              )}
              {overview && tab === "overview" && <Overview data={overview} />}
              {overview && tab === "workspaces" && (
                <Workspaces rows={rows} plans={plans} setRows={(r) => { setRows(r); void load(); }} />
              )}
              {overview && tab === "plans" && <Plans plans={plans} note={note} reload={load} />}
              {overview && tab === "announcements" && (
                <Announcements rows={announcements} workspaces={rows} reload={load} />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
