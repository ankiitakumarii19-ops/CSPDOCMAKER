"use client";

/**
 * Setup — Feature access (No. 206, Stage 2 of the configurable product plan)
 *
 * The Super Admin ticks which features each role has (RM, Admin, and the
 * workspace's own roles), makes own roles (a copy of another, built on RM
 * or Admin), chooses which CSPs an RM-type role may act on, and makes
 * exceptions for one person. Nothing changed = today's access. The server
 * refuses a feature that is switched off; this page only shows it.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type {
  AccessChange,
  AccessFeature,
  FeatureAccessPerson,
  AccessRoleItem,
  ApiError,
  FeatureAccessView,
} from "../lib/api";

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";
const input =
  "px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-eko disabled:opacity-60";
const btn = "px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50";

function when(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const KIND: Record<string, string> = { rm: "RM", admin: "Admin" };

function RoleHeader({
  role,
  busy,
  onChange,
}: {
  role: AccessRoleItem;
  busy: boolean;
  onChange: (fn: () => Promise<FeatureAccessView>, msg: string) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(role.name);
  return (
    <div className="space-y-1">
      {renaming ? (
        <div className="flex flex-col gap-1">
          <input className={`${input} w-36`} value={name} onChange={(e) => setName(e.target.value)} />
          <div className="flex gap-1">
            <button
              className={`${btn} bg-eko text-white text-xs`}
              disabled={busy}
              onClick={() => {
                setRenaming(false);
                onChange(() => api.changeAccessRole(role.key, { name }), `Renamed to ${name}.`);
              }}
            >
              Save
            </button>
            <button className={`${btn} text-xs text-gray-500`} onClick={() => setRenaming(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="font-semibold text-gray-900 dark:text-white">{role.name}</div>
      )}
      <div className="text-[11px] font-normal text-gray-500 dark:text-gray-400">
        {role.built_in ? "built-in" : `built on ${KIND[role.base_role]}`} · {role.members} member
        {role.members === 1 ? "" : "s"}
      </div>
      {role.base_role === "rm" ? (
        <select
          className="text-[11px] font-normal rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-gray-200 px-1 py-0.5"
          value={role.record_scope}
          disabled={busy}
          title="Which CSPs people in this role may act on"
          onChange={(e) => {
            const v = e.target.value as "own" | "all";
            onChange(
              () => api.changeAccessRole(role.key, { record_scope: v }),
              v === "all" ? `${role.name} may now act on every CSP.` : `${role.name} acts on their own CSPs again.`
            );
          }}
        >
          <option value="own">CSPs: own + unowned</option>
          <option value="all">CSPs: every CSP</option>
        </select>
      ) : (
        <div className="text-[11px] font-normal text-gray-500">CSPs: every CSP</div>
      )}
      {!role.built_in && !renaming && (
        <div className="flex gap-2 text-[11px] font-normal">
          <button className="text-eko-dark dark:text-eko hover:underline" onClick={() => setRenaming(true)}>
            Rename
          </button>
          <button
            className="text-red-600 dark:text-red-400 hover:underline"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`Remove the role “${role.name}”? Its ticks go with it.`)) {
                onChange(() => api.deleteAccessRole(role.key), `Removed the role ${role.name}.`);
              }
            }}
          >
            Remove
          </button>
        </div>
      )}
    </div>
  );
}

function PersonRow({
  person,
  view,
  busy,
  onChange,
}: {
  person: FeatureAccessPerson;
  view: FeatureAccessView;
  busy: boolean;
  onChange: (fn: () => Promise<FeatureAccessView>, msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const roles = view.roles.filter((r) => r.base_role === person.role);
  const exceptions = Object.keys(person.overrides).length;
  const roleKey = person.own_role ?? person.role;
  const changeable = view.features.filter(
    (f) => view.grid[roleKey]?.[f.key]?.can_change
  );
  return (
    <div className="py-3 border-t border-gray-100 dark:border-gray-700 first:border-t-0">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-gray-900 dark:text-white truncate">
            {person.name || person.email}
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
            {person.email} · {KIND[person.role]}
          </div>
        </div>
        <select
          className={`${input} sm:w-48`}
          value={roleKey}
          disabled={busy}
          onChange={(e) => {
            const v = e.target.value;
            onChange(
              () => api.setMemberAccessRole(person.email, v === person.role ? null : v),
              `${person.email}: role changed.`
            );
          }}
        >
          {roles.map((r) => (
            <option key={r.key} value={r.key}>
              {r.name}
            </option>
          ))}
        </select>
        <button
          className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
          onClick={() => setOpen(!open)}
        >
          Exceptions{exceptions ? ` (${exceptions})` : ""} {open ? "▲" : "▼"}
        </button>
      </div>
      {open && (
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
          {changeable.map((f) => {
            const o = person.overrides[f.key];
            const value = o === undefined ? "role" : o ? "on" : "off";
            const fromRole = view.grid[roleKey]?.[f.key]?.allowed;
            return (
              <label key={f.key} className="flex items-center justify-between gap-2 text-sm">
                <span className="text-gray-700 dark:text-gray-200 min-w-0 truncate">{f.title}</span>
                <select
                  className="text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-gray-200 px-1 py-1"
                  value={value}
                  disabled={busy}
                  onChange={(e) => {
                    const v = e.target.value;
                    onChange(
                      () =>
                        api.setPersonFeature(person.email, f.key, v === "role" ? null : v === "on"),
                      `${person.email}: ${f.title} ${v === "role" ? "as their role" : v === "on" ? "given" : "taken away"}.`
                    );
                  }}
                >
                  <option value="role">As their role ({fromRole ? "has it" : "not"})</option>
                  <option value="on">Given</option>
                  <option value="off">Taken away</option>
                </select>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function FeatureAccess() {
  const [view, setView] = useState<FeatureAccessView | null>(null);
  const [changes, setChanges] = useState<AccessChange[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [copyFrom, setCopyFrom] = useState("rm");

  useEffect(() => {
    let alive = true;
    Promise.all([api.featureAccess(), api.featureAccessHistory()])
      .then(([v, h]) => {
        if (!alive) return;
        setView(v);
        setChanges(h.changes);
      })
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load Feature access."));
    return () => {
      alive = false;
    };
  }, []);

  const change = useCallback(async (fn: () => Promise<FeatureAccessView>, msg: string) => {
    setBusy(true);
    setError("");
    try {
      const v = await fn();
      setView(v);
      setMessage(msg);
      const h = await api.featureAccessHistory();
      setChanges(h.changes);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }, []);

  const byGroup = useMemo(() => {
    const out: Record<string, AccessFeature[]> = {};
    view?.features.forEach((f) => (out[f.group] ||= []).push(f));
    return out;
  }, [view]);

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

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Feature access</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Tick what each role may use. {view.note}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          You can also ask the chat, e.g. <em>give RMs the dashboard</em> or{" "}
          <em>take whatsapp messages from admins</em>.
        </p>
      </div>

      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div className="text-sm text-eko-dark dark:text-eko">{message}</div>}

      <section className={`${card} p-4`}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">New role</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          Starts as a copy of another role: its kind (RM or Admin), its ticks and its CSPs.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            className={`${input} sm:w-64`}
            placeholder="e.g. Field officer"
            value={newName}
            maxLength={60}
            onChange={(e) => setNewName(e.target.value)}
          />
          <select className={`${input} sm:w-48`} value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}>
            {view.roles.map((r) => (
              <option key={r.key} value={r.key}>
                Copy of {r.name}
              </option>
            ))}
          </select>
          <button
            className={`${btn} bg-eko hover:bg-eko-dark text-white`}
            disabled={busy || newName.trim().length < 2}
            onClick={() => {
              const name = newName.trim();
              setNewName("");
              change(() => api.createAccessRole(name, copyFrom), `Made the role ${name}.`);
            }}
          >
            Add role
          </button>
        </div>
      </section>

      <section className={`${card} overflow-x-auto`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left align-top border-b border-gray-200 dark:border-gray-700">
              <th className="p-3 min-w-[16rem] text-gray-900 dark:text-white">Feature</th>
              {view.roles.map((r) => (
                <th key={r.key} className="p-3 min-w-[9rem]">
                  <RoleHeader role={r} busy={busy} onChange={change} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.groups.map((g) =>
              (byGroup[g.key] || []).length === 0 ? null : (
                <GroupRows key={g.key} title={g.title} features={byGroup[g.key]} view={view} busy={busy} onChange={change} />
              )
            )}
          </tbody>
        </table>
      </section>

      <section className={`${card} p-4`}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">People</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
          Give someone one of your roles, or make an exception for one feature. Super Admins always
          keep everything.
        </p>
        {view.people.length === 0 && <div className="text-sm text-gray-500 py-2">No RMs or Admins yet.</div>}
        {view.people.map((p) => (
          <PersonRow key={p.email} person={p} view={view} busy={busy} onChange={change} />
        ))}
      </section>

      <section className={`${card} p-4`}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">History</h3>
        {changes.length === 0 && <div className="text-sm text-gray-500 py-2">Nothing changed yet.</div>}
        {changes.map((c) => (
          <div key={c.id} className="py-2 border-t border-gray-100 dark:border-gray-700 first:border-t-0 text-sm">
            <div className="text-gray-800 dark:text-gray-100">
              <strong>{c.what}</strong>: {c.before} → {c.after}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400">
              {c.by} · {c.via === "chat" ? "by chat" : "on this page"} · {when(c.at)}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

function GroupRows({
  title,
  features,
  view,
  busy,
  onChange,
}: {
  title: string;
  features: AccessFeature[];
  view: FeatureAccessView;
  busy: boolean;
  onChange: (fn: () => Promise<FeatureAccessView>, msg: string) => void;
}) {
  return (
    <>
      <tr className="bg-gray-50 dark:bg-gray-900/40">
        <td colSpan={view.roles.length + 1} className="px-3 py-2 text-xs font-bold uppercase tracking-wider text-gray-500">
          {title}
        </td>
      </tr>
      {features.map((f) => (
        <tr key={f.key} className="border-t border-gray-100 dark:border-gray-700 align-top">
          <td className="p-3">
            <div className="font-medium text-gray-900 dark:text-white">
              {f.locked && <i className="fas fa-lock text-gray-400 mr-1"></i>}
              {f.title}
            </div>
            {f.about && <div className="text-xs text-gray-500 dark:text-gray-400">{f.about}</div>}
            {f.all_csps && (
              <div className="text-[11px] text-amber-700 dark:text-amber-400 mt-0.5">Shows every CSP</div>
            )}
          </td>
          {view.roles.map((r) => {
            const cell = view.grid[r.key]?.[f.key];
            if (!cell) return <td key={r.key} />;
            return (
              <td key={r.key} className="p-3">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={cell.allowed}
                    disabled={busy || !cell.can_change}
                    title={cell.can_change ? "" : f.locked ? "Stays with the Super Admin" : `Cannot be given to ${KIND[r.base_role]}s`}
                    onChange={(e) =>
                      onChange(
                        () => api.setRoleFeature(r.key, f.key, e.target.checked),
                        `${r.name}: ${f.title} ${e.target.checked ? "given" : "taken away"}.`
                      )
                    }
                  />
                  {cell.set && (
                    <button
                      className="text-[11px] text-amber-700 dark:text-amber-400 hover:underline"
                      disabled={busy}
                      title="Put back to today's access"
                      onClick={() =>
                        onChange(() => api.setRoleFeature(r.key, f.key, null), `${r.name}: ${f.title} as before.`)
                      }
                    >
                      changed ↺
                    </button>
                  )}
                </div>
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}
